#!/usr/bin/env python3
"""Run a cached FastVLM Top-K POI reranking baseline.

The model is loaded once, receives only the photo and provider candidates, and
must select a candidate number or UNKNOWN. UNKNOWN, ambiguous output, missing
photos, and inference errors conservatively fall back to the nearest candidate.
Ground truth is used only after inference by run_algorithm._score.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import match_score as ms
import run_algorithm as ra

PROMPT_TEMPLATE = """Look at the image and identify its main photographed place.
Choose only from these nearby candidate places:
{candidates}

Use visible signs, logos, storefronts, entrances, architecture, or distinctive
landmarks as evidence. If the image does not clearly support one candidate,
answer UNKNOWN. Answer with only one candidate number or UNKNOWN. Do not explain.
"""


def build_prompt(candidates: List[Dict[str, Any]]) -> str:
    lines = [f"{i}. {c.get('name', '').strip()}" for i, c in enumerate(candidates, 1)]
    return PROMPT_TEMPLATE.format(candidates="\n".join(lines))


def _normalized_words(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", (text or "").casefold(), flags=re.UNICODE))


def parse_selection(raw: str, candidates: List[Dict[str, Any]]) -> Optional[int]:
    """Return a zero-based candidate index only for an unambiguous response.

    FastVLM-0.5B sometimes ignores the requested number-only format but clearly
    writes one candidate's name. Accept that only when exactly one normalized
    candidate name occurs in the response; otherwise retain the nearest fallback.
    """
    text = (raw or "").strip()
    if not text or re.search(r"\bUNKNOWN\b", text, flags=re.IGNORECASE):
        return None
    numbers = {
        int(token) for token in re.findall(r"(?<!\d)(\d+)(?!\d)", text)
        if 1 <= int(token) <= len(candidates)
    }
    if len(numbers) == 1:
        return next(iter(numbers)) - 1
    if numbers:
        return None

    normalized_output = f" {_normalized_words(text)} "
    name_matches = {
        i for i, candidate in enumerate(candidates)
        if (name := _normalized_words(str(candidate.get("name") or "")))
        and f" {name} " in normalized_output
    }
    return next(iter(name_matches)) if len(name_matches) == 1 else None


def photo_path(data_dir: Path, cfg: Dict[str, Any], dataset: str, photo: str) -> Optional[Path]:
    source = (cfg.get("sources") or {}).get(dataset) or {}
    rel_dir = source.get("photo_dir")
    if not rel_dir or not photo:
        return None
    candidate = (data_dir / rel_dir / photo).resolve()
    base = (data_dir / rel_dir).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
                cache[item["key"]] = item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return cache


def cache_key(case: Dict[str, Any], candidates: List[Dict[str, Any]], model_path: Path) -> str:
    evidence = {
        "dataset": case["_dataset"], "photo": case["_photo"],
        "candidates": [c.get("name", "") for c in candidates],
        "model": model_path.name, "prompt": PROMPT_TEMPLATE, "cache_schema": 2,
    }
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class FastVLM:
    def __init__(self, repo: Path, model_path: Path):
        sys.path.insert(0, str(repo))
        import torch
        from llava.constants import IMAGE_TOKEN_INDEX, DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
        from llava.conversation import conv_templates
        from llava.mm_utils import get_model_name_from_path, process_images, tokenizer_image_token
        from llava.model.builder import load_pretrained_model
        from llava.utils import disable_torch_init

        if not torch.backends.mps.is_available():
            raise RuntimeError("FastVLM baseline requires an available MPS device")
        self.torch = torch
        self.Image = __import__("PIL.Image", fromlist=["Image"])
        self.IMAGE_TOKEN_INDEX = IMAGE_TOKEN_INDEX
        self.DEFAULT_IMAGE_TOKEN = DEFAULT_IMAGE_TOKEN
        self.DEFAULT_IM_START_TOKEN = DEFAULT_IM_START_TOKEN
        self.DEFAULT_IM_END_TOKEN = DEFAULT_IM_END_TOKEN
        self.conv_templates = conv_templates
        self.process_images = process_images
        self.tokenizer_image_token = tokenizer_image_token

        generation = model_path / "generation_config.json"
        hidden_generation = model_path / ".generation_config.json"
        moved = generation.exists()
        if moved:
            generation.rename(hidden_generation)
        try:
            disable_torch_init()
            name = get_model_name_from_path(str(model_path))
            self.tokenizer, self.model, self.image_processor, self.context_len = load_pretrained_model(
                str(model_path), None, name, device="mps"
            )
        finally:
            if moved and hidden_generation.exists():
                hidden_generation.rename(generation)
        self.model.generation_config.pad_token_id = self.tokenizer.pad_token_id

    def infer(self, image_path: Path, prompt_text: str) -> str:
        qs = prompt_text
        if self.model.config.mm_use_im_start_end:
            qs = self.DEFAULT_IM_START_TOKEN + self.DEFAULT_IMAGE_TOKEN + self.DEFAULT_IM_END_TOKEN + "\n" + qs
        else:
            qs = self.DEFAULT_IMAGE_TOKEN + "\n" + qs
        conv = self.conv_templates["qwen_2"].copy()
        conv.append_message(conv.roles[0], qs)
        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()
        input_ids = self.tokenizer_image_token(
            prompt, self.tokenizer, self.IMAGE_TOKEN_INDEX, return_tensors="pt"
        ).unsqueeze(0).to(self.torch.device("mps"))
        image = self.Image.open(image_path).convert("RGB")
        image_tensor = self.process_images([image], self.image_processor, self.model.config)[0]
        with self.torch.inference_mode():
            output_ids = self.model.generate(
                input_ids, images=image_tensor.unsqueeze(0).half(), image_sizes=[image.size],
                do_sample=False, num_beams=1, max_new_tokens=64, use_cache=True,
            )
        return self.tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0].strip()


def write_tsv(path: Path, items: List[Dict[str, Any]]) -> None:
    fields = ["dataset", "photo", "prediction", "nearest", "selected_index", "decision",
              "raw_output", "latency_ms", "error"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=str(ROOT / "poi-data"))
    p.add_argument("--model-repo", default=str(ROOT / "poi-data/tools/ml-fastvlm"))
    p.add_argument("--model-path", default=str(ROOT / "poi-data/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3"))
    p.add_argument("--candidate-limit", type=int, default=5)
    p.add_argument("--limit", type=int, default=None, help="Smoke-test only: process first N eligible cases")
    p.add_argument("--cache", default=str(ROOT / "poi-data/generated/fastvlm_top5_cache.jsonl"))
    p.add_argument("--results-tsv", default=str(ROOT / "poi-data/fastvlm_results.tsv"))
    p.add_argument("--run-name", default="fastvlm-top5-reranker")
    args = p.parse_args()

    data_dir, model_repo, model_path = map(Path, (args.data_dir, args.model_repo, args.model_path))
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    rows = ms.read_rows(str(data_dir / "eval_set_reconciled.csv"))
    candidates_data = ms.load_candidates([str(data_dir / "generated/mapkit_candidates.jsonl")])
    cases = ra.build_cases(rows, cfg, candidates_data, "all", ["image", "nearby_candidates"], args.candidate_limit)
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        raise SystemExit("no eligible cases")

    cache_path = Path(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    model = None
    items: List[Dict[str, Any]] = []
    preds: List[Dict[str, Any]] = []

    for pos, case in enumerate(cases, 1):
        cands = case["input"].get("nearby_candidates") or []
        nearest = (cands[0].get("name") or "").strip() if cands else ""
        key = cache_key(case, cands, model_path)
        item = cache.get(key)
        if item is None:
            image = photo_path(data_dir, cfg, case["_dataset"], case["_photo"])
            started = time.monotonic()
            raw, error = "", ""
            if not cands:
                decision, selected, prediction = "no_candidates", None, ""
            elif image is None:
                decision, selected, prediction = "missing_image_nearest_fallback", None, nearest
            else:
                try:
                    if model is None:
                        model = FastVLM(model_repo, model_path)
                    raw = model.infer(image, build_prompt(cands))
                    selected = parse_selection(raw, cands)
                    if selected is None:
                        decision, prediction = "nearest_fallback", nearest
                    else:
                        prediction = (cands[selected].get("name") or "").strip()
                        decision = "vlm_agrees_nearest" if selected == 0 else "vlm_override"
                except Exception as exc:
                    error = repr(exc)
                    decision, selected, prediction = "inference_error_nearest_fallback", None, nearest
            item = {
                "key": key, "dataset": case["_dataset"], "photo": case["_photo"],
                "prediction": prediction, "nearest": nearest,
                "selected_index": (selected + 1) if selected is not None else "",
                "decision": decision, "raw_output": raw,
                "latency_ms": round((time.monotonic() - started) * 1000), "error": error,
            }
            with cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        items.append(item)
        preds.append({"prediction": item["prediction"], "reason": item["decision"], "error": None})
        print(f"[{pos}/{len(cases)}] {case['_photo']}: {item['decision']} -> {item['prediction']}", flush=True)

    write_tsv(Path(args.results_tsv), items)
    scored = ra._score(cases, preds, "exact")
    safe = ra._safe_name(args.run_name)
    runs_dir = data_dir / "generated/runs"
    version = ra._pick_version(str(runs_dir), safe, "new")
    record = {
        "name": args.run_name, "safe_name": safe, "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": "all" if args.limit is None else f"first-{args.limit}",
        "mode": "exact", "params": ["image", "nearby_candidates"],
        "candidate_limit": args.candidate_limit, "lang": "fastvlm-mps-batch",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
        "data_snapshot_sha256": ra.data_snapshot_sha256([
            str(data_dir / "eval_set_reconciled.csv"),
            str(data_dir / "dashboard_config.json"),
            str(data_dir / "generated/mapkit_candidates.jsonl"),
        ]),
        "script_text": Path(__file__).read_text(encoding="utf-8"),
        "metrics": {k: v for k, v in scored.items() if k != "cases"}, "cases": scored["cases"],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{safe}__v{version}.json"
    run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run": str(run_path), "metrics": record["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
