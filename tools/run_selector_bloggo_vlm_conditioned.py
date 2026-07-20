#!/usr/bin/env python3
"""Exploratory FastVLM candidate-conditioned correction layer for Bloggo.

The Bloggo winner remains the default.  For an ambiguous Bloggo candidate set,
FastVLM sees the top three Bloggo-ranked candidates and may nominate one only
when its terse selection parses unambiguously and a fresh candidate-specific
visual verification returns exactly YES.  This runner never sends ground truth
to the model and preserves the frozen MapKit Top-5 snapshot.

This is an exploratory replay: prompt/rule design was informed by inspection of
the frozen cohort.  It is not a held-out estimate of deployed accuracy.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "examples"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import match_score as ms
import run_algorithm as ra
from mapkit_weighted import resolve as bloggo_resolve
from run_vlm_topk_rerank import FastVLM, photo_path

# No free-form JSON: FastVLM-0.5B frequently exceeded the prior JSON output
# budget.  Candidate names are shown only after Bloggo marks the set ambiguous.
SELECT_PROMPT = """Look at the photo and choose the ONE listed candidate with the strongest visual support.
Candidates:
{candidates}

Use a readable sign, logo, distinctive landmark, or clearly identifying subject. Do not use proximity. If the photo does not support one candidate, choose 0.
Reply with exactly one character: 0, 1, 2, or 3. No explanation."""
VERIFY_PROMPT = """Look at the photo. Is there direct visual support for the venue {candidate_name!r} (readable name/logo, distinctive landmark, or uniquely identifying subject)?
Answer exactly YES or NO. Do not infer from proximity or merely from the candidate list."""
RULE_VERSION = "top3-conditioned-choice+exact-yes-v2-exploratory"
CACHE_SCHEMA = 1


def selection_prompt(candidates: List[Dict[str, Any]]) -> str:
    return SELECT_PROMPT.format(candidates="\n".join(
        f"{index}. {str(candidate.get('name') or '').strip()}" for index, candidate in enumerate(candidates, 1)
    ))


def parse_choice(raw: str, candidate_count: int) -> Optional[int]:
    """Return zero-based choice only for a single exact digit; 0 is abstention."""
    answer = (raw or "").strip()
    if answer == "0":
        return None
    if len(answer) == 1 and answer in "123" and int(answer) <= candidate_count:
        return int(answer) - 1
    return None


def exact_yes(raw: str) -> bool:
    return (raw or "").strip().casefold() == "yes"


def decide_without_model(raw_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    resolution = bloggo_resolve({"nearby_candidates": raw_candidates})
    ranked = resolution["candidates"]
    base = resolution["selected"]
    if base is None:
        decision = "no_usable_bloggo_candidate"
    elif resolution["decision"] != "ambiguous":
        decision = "bloggo_clear_winner_vlm_skipped"
    else:
        decision = "bloggo_ambiguous_vlm_eligible"
    return {"resolution": resolution, "ranked": ranked, "base": base, "decision": decision}


def _snapshot(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = ("name", "provider_place_id", "category", "distance_m", "lat", "lon", "rank")
    return [{field: candidate.get(field) for field in fields} for candidate in candidates]


def cache_key(case: Dict[str, Any], raw: List[Dict[str, Any]], ranked: List[Dict[str, Any]], model_path: Path) -> str:
    payload = {
        "dataset": case["_dataset"], "photo": case["_photo"],
        "raw_candidates": _snapshot(raw), "bloggo_ranked": _snapshot(ranked),
        "bloggo_policy_sha256": hashlib.sha256((ROOT / "examples/mapkit_weighted.py").read_bytes()).hexdigest(),
        "model": model_path.name, "select_prompt": SELECT_PROMPT,
        "verify_prompt": VERIFY_PROMPT, "rule_version": RULE_VERSION, "cache_schema": CACHE_SCHEMA,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and isinstance(item.get("key"), str):
                    cache[item["key"]] = item
            except json.JSONDecodeError:
                pass
    return cache


def append_cache(path: Path, item: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def process_case(case: Dict[str, Any], data_dir: Path, cfg: Dict[str, Any], model_repo: Path,
                 model_path: Path, model: Optional[FastVLM]) -> tuple[Dict[str, Any], Optional[FastVLM]]:
    raw = case["input"].get("nearby_candidates") or []
    policy = decide_without_model(raw)
    resolution, ranked, base = policy["resolution"], policy["ranked"], policy["base"]
    decision = policy["decision"]
    prediction = str(base.get("name") or "").strip() if base else ""
    choice_raw = verification_raw = error = ""
    nominated: Optional[Dict[str, Any]] = None
    started = time.monotonic()

    if base is not None and resolution["decision"] == "ambiguous":
        image = photo_path(data_dir, cfg, case["_dataset"], case["_photo"])
        choices = ranked[:3]
        if image is None:
            decision = "missing_image_bloggo_fallback"
        elif len(choices) < 2:
            decision = "insufficient_ranked_candidates_bloggo_fallback"
        else:
            try:
                if model is None:
                    model = FastVLM(model_repo, model_path)
                choice_raw = model.infer(image, selection_prompt(choices))
                selected_index = parse_choice(choice_raw, len(choices))
                if selected_index is None:
                    decision = "unusable_or_abstained_choice_bloggo_fallback"
                else:
                    nominated = choices[selected_index]
                    if nominated.get("provider_place_id") == base.get("provider_place_id") and nominated.get("name") == base.get("name"):
                        decision = "vlm_confirms_bloggo"
                    else:
                        verification_raw = model.infer(image, VERIFY_PROMPT.format(candidate_name=str(nominated.get("name") or "")))
                        if exact_yes(verification_raw):
                            prediction = str(nominated.get("name") or "").strip()
                            decision = "conditioned_choice_verified_override"
                        else:
                            decision = "choice_verification_failed_bloggo_fallback"
            except Exception as exc:
                error = repr(exc)
                decision = "inference_error_bloggo_fallback"

    item = {
        "dataset": case["_dataset"], "photo": case["_photo"], "prediction": prediction,
        "bloggo_winner": str(base.get("name") or "").strip() if base else "",
        "decision": decision, "bloggo_gap_m": resolution.get("gap_m"),
        "bloggo_threshold_m": resolution.get("ambiguity_threshold_m"),
        "ranked_candidates": json.dumps([str(c.get("name") or "") for c in ranked], ensure_ascii=False),
        "choice_candidates": json.dumps([str(c.get("name") or "") for c in ranked[:3]], ensure_ascii=False),
        "nominated_candidate": str(nominated.get("name") or "") if nominated else "",
        "choice_raw": choice_raw, "verification_raw": verification_raw,
        "latency_ms": round((time.monotonic() - started) * 1000), "error": error,
    }
    return item, model


def write_tsv(path: Path, items: List[Dict[str, Any]]) -> None:
    fields = ["dataset", "photo", "prediction", "bloggo_winner", "decision", "bloggo_gap_m", "bloggo_threshold_m",
              "ranked_candidates", "choice_candidates", "nominated_candidate", "choice_raw", "verification_raw", "latency_ms", "error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader(); writer.writerows(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "poi-data"))
    parser.add_argument("--model-repo", default=str(ROOT / "poi-data/tools/ml-fastvlm"))
    parser.add_argument("--model-path", default=str(ROOT / "poi-data/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3"))
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="Smoke-test only: process first N eligible cases")
    parser.add_argument("--cache", default=str(ROOT / "poi-data/generated/fastvlm_bloggo_conditioned_v2_cache.jsonl"))
    parser.add_argument("--results-tsv", default=str(ROOT / "poi-data/fastvlm_bloggo_conditioned_v2_results.tsv"))
    parser.add_argument("--run-name", default="selector-bloggo-vlm-conditioned")
    args = parser.parse_args()
    data_dir, model_repo, model_path = map(Path, (args.data_dir, args.model_repo, args.model_path))
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    cases = ra.build_cases(ms.read_rows(str(data_dir / "eval_set_reconciled.csv")), cfg,
                           ms.load_candidates([str(data_dir / "generated/mapkit_candidates.jsonl")]),
                           "all", ["image", "nearby_candidates"], args.candidate_limit)
    if args.limit is not None: cases = cases[:args.limit]
    if not cases: raise SystemExit("no eligible cases")
    cache_path = Path(args.cache); cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache, model, items, predictions = load_cache(cache_path), None, [], []
    for number, case in enumerate(cases, 1):
        raw = case["input"].get("nearby_candidates") or []
        policy = decide_without_model(raw); key = cache_key(case, raw, policy["ranked"], model_path)
        item = cache.get(key)
        if item is None:
            item, model = process_case(case, data_dir, cfg, model_repo, model_path, model)
            item["key"] = key; append_cache(cache_path, item)
        items.append(item); predictions.append({"prediction": item["prediction"], "reason": item["decision"], "error": None})
        print(f"[{number}/{len(cases)}] {case['_photo']}: {item['decision']} -> {item['prediction']}", flush=True)
    write_tsv(Path(args.results_tsv), items)
    scored = ra._score(cases, predictions, "exact")
    safe_name = ra._safe_name(args.run_name); runs_dir = data_dir / "generated/runs"
    version = ra._pick_version(str(runs_dir), safe_name, "new")
    record = {"name": args.run_name, "safe_name": safe_name, "version": version,
              "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
              "scope": "all" if args.limit is None else f"first-{args.limit}", "mode": "exact",
              "params": ["image", "nearby_candidates"], "candidate_limit": args.candidate_limit,
              "lang": "fastvlm-mps-bloggo-conditioned", "rule_version": RULE_VERSION,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
              "data_snapshot_sha256": ra.data_snapshot_sha256([str(data_dir / "eval_set_reconciled.csv"), str(data_dir / "dashboard_config.json"), str(data_dir / "generated/mapkit_candidates.jsonl"), str(ROOT / "examples/mapkit_weighted.py")]),
              "metrics": {key: value for key, value in scored.items() if key != "cases"}, "cases": scored["cases"]}
    runs_dir.mkdir(parents=True, exist_ok=True); run_path = runs_dir / f"{safe_name}__v{version}.json"
    run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run": str(run_path), "metrics": record["metrics"]}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
