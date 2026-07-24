"""Live FastVLM helpers for mapkit-baseline v2 (self-contained / bundleable).

No imports from repo ``tools/`` or ``examples/`` siblings — only stdlib and
installed packages (torch, PIL, llava via model-repo on sys.path).

Environment
-----------
POI_DATA_DIR          dataset root (photo dirs + optional model paths)
POI_FASTVLM_REPO      ml-fastvlm checkout (default: <data>/tools/ml-fastvlm)
POI_FASTVLM_MODEL     checkpoint dir (default: …/checkpoints/llava-fastvithd_0.5b_stage3)
POI_VLM_MODE          ``live`` (default) | ``off`` | ``cache_first``
POI_VLM_CACHE         JSONL write-through cache path (optional)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Prompt styles aligned with tools/run_vlm_topk_rerank.py (inlined for harness isolation).
PROMPTS = {
    "skill": """You pick the photographed place from the candidate list only.

Candidates:
{candidates}

Priority:
1) Readable name, logo, or menu text that matches one candidate
2) Distinctive architecture/landmark that uniquely matches one name
3) If a candidate is only an access label (Stop, Parking, Gift Shop, Entrance,
   Donation) and another candidate is the place it serves, prefer the place
4) Do not pick a nearby shop just because food/people are visible without its name

If none is clearly supported, answer UNKNOWN.
Answer with only one candidate number or UNKNOWN. No explanation.
""",
    "place_match": """You are given one photo and a short list of nearby places.
Do NOT rank by GPS distance. Ask only: could this photo have been taken at that place?
Pick the single place that most clearly matches what is visible in the photo.

Candidates:
{candidates}

Evidence to use (in order):
1) Business name, logo, or menu text readable in the photo
2) Unique building, interior, or landmark that fits only one candidate
3) If one candidate is just an access label (Stop, Parking, Gift Shop, Entrance)
   for another candidate, prefer the real place
4) Ignore pure proximity — a farther place can win if the photo shows it

Answer with only one candidate number (1-{n}). No UNKNOWN. No explanation.
""",
}

_model = None  # type: ignore
_model_error: Optional[str] = None
_cache: Optional[Dict[str, Dict[str, Any]]] = None
_cache_path: Optional[Path] = None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def vlm_mode() -> str:
    mode = (os.environ.get("POI_VLM_MODE") or "live").strip().lower()
    if mode in ("live", "off", "cache_first"):
        return mode
    return "live"


def data_root() -> Path:
    env = (os.environ.get("POI_DATA_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # Common layouts when harness did not inject POI_DATA_DIR.
    here = Path.cwd()
    for cand in (here / "poi-data", here, here.parent / "poi-data"):
        if (cand / "eval_set_reconciled.csv").is_file():
            return cand.resolve()
    return (here / "poi-data").resolve()


def model_paths() -> Tuple[Path, Path]:
    root = data_root()
    repo = Path(
        os.environ.get("POI_FASTVLM_REPO")
        or (root / "tools" / "ml-fastvlm")
    ).expanduser().resolve()
    model = Path(
        os.environ.get("POI_FASTVLM_MODEL")
        or (repo / "checkpoints" / "llava-fastvithd_0.5b_stage3")
    ).expanduser().resolve()
    return repo, model


def build_prompt(candidates: List[Dict[str, Any]], style: str = "place_match") -> str:
    lines = [f"{i}. {c.get('name', '').strip()}" for i, c in enumerate(candidates, 1)]
    template = PROMPTS.get(style) or PROMPTS["place_match"]
    return template.format(candidates="\n".join(lines), n=len(candidates))


def _normalized_words(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", (text or "").casefold(), flags=re.UNICODE))


def parse_selection(raw: str, candidates: List[Dict[str, Any]]) -> Optional[int]:
    """Zero-based candidate index, or None if ambiguous / UNKNOWN."""
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


def recover_name(raw: str, cands: List[Dict[str, Any]]) -> str:
    """Recover a candidate name from free-text VLM output (loop70 residual)."""
    idx = parse_selection(raw, cands)
    text = _norm(raw)
    quotes = re.findall(r'["“]([^"”]{3,80})["”]', raw or "")
    for q in quotes:
        nq = _norm(q)
        for c in cands:
            name = c.get("name") or ""
            nn = _norm(name)
            if nn and (nn == nq or (len(nq) >= 6 and (nq in nn or nn in nq))):
                return name
    hits = []
    for c in cands:
        name = c.get("name") or ""
        nn = _norm(name)
        if len(nn) >= 6 and nn in text:
            hits.append((len(nn), name))
    if hits:
        hits.sort(reverse=True)
        return hits[0][1]
    tokens = set(re.findall(r"[a-z0-9가-힣]{7,}", text))
    skip = {
        "parking", "restaurant", "building", "entrance", "suspension",
        "photographed", "architectural", "characteristic", "candidate",
    }
    for tok in sorted(tokens, key=len, reverse=True):
        if tok in skip:
            continue
        matches = [c.get("name") for c in cands if tok in _norm(c.get("name") or "")]
        if len(matches) == 1 and matches[0]:
            return matches[0]
    if idx is not None:
        return (cands[idx].get("name") or "").strip()
    return ""


def resolve_photo_path(case: Dict[str, Any]) -> Optional[Path]:
    """Resolve on-disk image path from case.photo + case.dataset + dashboard_config."""
    photo = (case.get("photo") or "").strip()
    if not photo:
        return None
    # Harness may inject an absolute path when image signal is selected.
    explicit = (case.get("image_path") or case.get("photo_path") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p.resolve()

    root = data_root()
    dataset = (case.get("dataset") or "").strip()
    cfg_path = root / "dashboard_config.json"
    photo_dirs: List[Path] = []
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
        sources = cfg.get("sources") or {}
        if dataset and dataset in sources:
            rel = (sources[dataset] or {}).get("photo_dir")
            if rel:
                photo_dirs.append(root / rel)
        for _ds, src in sources.items():
            rel = (src or {}).get("photo_dir")
            if rel:
                photo_dirs.append(root / rel)
    # Fallbacks used by the seed layout.
    for rel in (
        "photos",
        "linkedspaces-photos",
        "poi-dataset-20260708-photos",
        "union-city-trip/photos",
    ):
        photo_dirs.append(root / rel)

    seen = set()
    for d in photo_dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen:
            continue
        seen.add(key)
        candidate = (d / photo).resolve()
        try:
            candidate.relative_to(d.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


class FastVLM:
    """Minimal MPS FastVLM-0.5B wrapper (same contract as tools runner)."""

    def __init__(self, repo: Path, model_path: Path):
        import sys

        sys.path.insert(0, str(repo))
        import torch
        from llava.constants import (
            IMAGE_TOKEN_INDEX,
            DEFAULT_IMAGE_TOKEN,
            DEFAULT_IM_START_TOKEN,
            DEFAULT_IM_END_TOKEN,
        )
        from llava.conversation import conv_templates
        from llava.mm_utils import (
            get_model_name_from_path,
            process_images,
            tokenizer_image_token,
        )
        from llava.model.builder import load_pretrained_model
        from llava.utils import disable_torch_init

        if not torch.backends.mps.is_available():
            raise RuntimeError("FastVLM requires an available MPS device")
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
            self.tokenizer, self.model, self.image_processor, self.context_len = (
                load_pretrained_model(str(model_path), None, name, device="mps")
            )
        finally:
            if moved and hidden_generation.exists():
                hidden_generation.rename(generation)
        self.model.generation_config.pad_token_id = self.tokenizer.pad_token_id

    def infer(self, image_path: Path, prompt_text: str) -> str:
        qs = prompt_text
        if self.model.config.mm_use_im_start_end:
            qs = (
                self.DEFAULT_IM_START_TOKEN
                + self.DEFAULT_IMAGE_TOKEN
                + self.DEFAULT_IM_END_TOKEN
                + "\n"
                + qs
            )
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
        image_tensor = self.process_images(
            [image], self.image_processor, self.model.config
        )[0]
        with self.torch.inference_mode():
            output_ids = self.model.generate(
                input_ids,
                images=image_tensor.unsqueeze(0).half(),
                image_sizes=[image.size],
                do_sample=False,
                num_beams=1,
                max_new_tokens=64,
                use_cache=True,
            )
        return self.tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0].strip()


def _cache_key(
    dataset: str,
    photo: str,
    candidates: List[Dict[str, Any]],
    model_path: Path,
    prompt_style: str,
) -> str:
    template = PROMPTS.get(prompt_style) or PROMPTS["place_match"]
    evidence = {
        "dataset": dataset,
        "photo": photo,
        "candidates": [c.get("name", "") for c in candidates],
        "model": model_path.name,
        "prompt": template,
        "prompt_style": prompt_style,
        "cache_schema": 3,
    }
    return hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
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


def _ensure_cache() -> Tuple[Dict[str, Dict[str, Any]], Optional[Path]]:
    global _cache, _cache_path
    if _cache is not None:
        return _cache, _cache_path
    env = (os.environ.get("POI_VLM_CACHE") or "").strip()
    if env:
        path = Path(env).expanduser()
    else:
        path = data_root() / "generated" / "mapkit_baseline_v2_live_cache.jsonl"
    _cache_path = path
    _cache = _load_cache(path)
    return _cache, _cache_path


def _append_cache(path: Path, item: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def get_model() -> Tuple[Optional[FastVLM], Optional[str]]:
    """Lazy-load FastVLM once per predict process. Returns (model, error)."""
    global _model, _model_error
    if _model is not None:
        return _model, None
    if _model_error is not None:
        return None, _model_error
    if vlm_mode() == "off":
        _model_error = "POI_VLM_MODE=off"
        return None, _model_error
    repo, model_path = model_paths()
    if not model_path.is_dir():
        _model_error = f"model_missing:{model_path}"
        return None, _model_error
    try:
        _model = FastVLM(repo, model_path)
        return _model, None
    except Exception as exc:  # noqa: BLE001 — surface to reason string
        _model_error = f"model_load_failed:{exc!r}"
        return None, _model_error


def infer(
    case: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    style: str = "place_match",
) -> Dict[str, Any]:
    """Run FastVLM (or cache) for one case.

    Returns dict with keys: ok, prediction, raw_output, reason, error.
    """
    if not candidates:
        return {
            "ok": False,
            "prediction": "",
            "raw_output": "",
            "reason": "vlm_no_candidates",
            "error": None,
        }
    mode = vlm_mode()
    if mode == "off":
        return {
            "ok": False,
            "prediction": "",
            "raw_output": "",
            "reason": "vlm_mode_off",
            "error": None,
        }

    dataset = (case.get("dataset") or "").strip()
    photo = (case.get("photo") or "").strip()
    _, model_path = model_paths()
    key = _cache_key(dataset, photo, candidates, model_path, style)
    cache, cache_path = _ensure_cache()
    # Always reuse a write-through cache hit (same key → same model/prompt).
    hit = cache.get(key)
    if hit is not None:
        return {
            "ok": bool((hit.get("prediction") or "").strip()) and not hit.get("error"),
            "prediction": (hit.get("prediction") or "").strip(),
            "raw_output": hit.get("raw_output") or "",
            "reason": "vlm_cache_hit",
            "error": hit.get("error") or None,
        }
    if mode == "cache_first":
        return {
            "ok": False,
            "prediction": "",
            "raw_output": "",
            "reason": "vlm_cache_missing",
            "error": None,
        }

    image = resolve_photo_path(case)
    if image is None:
        return {
            "ok": False,
            "prediction": "",
            "raw_output": "",
            "reason": "vlm_image_missing",
            "error": None,
        }

    model, err = get_model()
    if model is None:
        return {
            "ok": False,
            "prediction": "",
            "raw_output": "",
            "reason": "vlm_unavailable",
            "error": err,
        }

    raw = ""
    error = ""
    prediction = ""
    try:
        raw = model.infer(image, build_prompt(candidates, style=style))
        if style == "skill":
            # Free-text residual: prefer name recovery over index-only parse.
            prediction = recover_name(raw, candidates)
            if not prediction:
                idx = parse_selection(raw, candidates)
                if idx is not None:
                    prediction = (candidates[idx].get("name") or "").strip()
        else:
            idx = parse_selection(raw, candidates)
            if idx is not None:
                prediction = (candidates[idx].get("name") or "").strip()
            else:
                # place_match sometimes free-texts a name
                prediction = recover_name(raw, candidates)
        reason = "vlm_live"
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)
        reason = "vlm_error"
        prediction = ""

    item = {
        "key": key,
        "dataset": dataset,
        "photo": photo,
        "prompt_style": style,
        "prediction": prediction,
        "raw_output": raw,
        "error": error,
    }
    cache[key] = item
    if cache_path is not None:
        try:
            _append_cache(cache_path, item)
        except OSError:
            pass

    return {
        "ok": bool(prediction) and not error,
        "prediction": prediction,
        "raw_output": raw,
        "reason": reason,
        "error": error or None,
    }
