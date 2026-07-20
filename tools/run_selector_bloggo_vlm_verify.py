#!/usr/bin/env python3
"""Run a conservative FastVLM correction layer over the MapKit Bloggo policy.

The Bloggo winner is always the default prediction. FastVLM is called only for
Bloggo-ambiguous candidate sets, and can replace that winner only if it first
returns parseable visible text that uniquely contains a full, non-generic
candidate name and then exactly confirms that candidate. Ground truth is never
sent to FastVLM and is used only by the existing scorer after inference.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import importlib.util
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "examples"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import match_score as ms
import run_algorithm as ra
from mapkit_weighted import resolve as bloggo_resolve
from run_vlm_topk_rerank import FastVLM, photo_path

# The first prompt intentionally has no candidate names, so the model's visible
# text transcription cannot be biased by the retrieval list.
EVIDENCE_PROMPT = """Inspect the photo. Return exactly one JSON object and no other text.
Use this schema:
{"visible_text":"...","place_type":"restaurant|cafe|store|park|hotel|landmark|transport|other|unknown","view":"storefront|interior|entrance|landmark|other|unknown"}

Transcribe only venue text or logos that are visibly readable. Do not infer a
venue name from appearance, location, or likely nearby places. Use an empty
string and unknown when there is no clear evidence."""
VERIFY_PROMPT = """Does this image visibly identify the venue {candidate_name!r}?
Answer exactly YES or NO. Answer YES only if its name, logo, or another uniquely
identifying visual feature is visible. Do not infer from proximity or venue type."""

# A full candidate name containing only these tokens is not identity evidence.
GENERIC_TOKENS = frozenset({
    "bar", "beach", "cafe", "centre", "center", "coffee", "entrance", "exit",
    "hotel", "inn", "landmark", "museum", "park", "parking", "restaurant",
    "shop", "store", "the", "venue", "visitor",
})
RULE_VERSION = "visible-full-name-unique+exact-yes-v1"
CACHE_SCHEMA = 1


def normalized_words(value: Any) -> str:
    """Casefold and tokenize text while preserving Unicode letters/digits."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def parse_evidence(raw: str) -> Optional[Dict[str, str]]:
    """Accept only a JSON object containing a string visible_text field.

    Markdown fences and prose are deliberately rejected: this is an auditably
    strict gate, not a best-effort OCR parser.
    """
    try:
        value = json.loads((raw or "").strip())
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("visible_text"), str):
        return None
    return {
        "visible_text": value["visible_text"].strip(),
        "place_type": str(value.get("place_type") or "unknown").strip().casefold(),
        "view": str(value.get("view") or "unknown").strip().casefold(),
    }


def _is_distinctive_name(name: str) -> bool:
    tokens = normalized_words(name).split()
    return bool(tokens) and any(token not in GENERIC_TOKENS and len(token) >= 3 for token in tokens)


def unique_strong_name_match(visible_text: str, candidates: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a candidate only for one full, distinctive name in visible text.

    Partial-name matching is intentionally prohibited. It avoids selecting a
    business from generic words such as ``Cafe`` or from a shared brand fragment.
    If the same normalized name appears in multiple candidates, the evidence is
    ambiguous and no override is possible.
    """
    evidence = normalized_words(visible_text)
    if not evidence:
        return None
    padded_evidence = f" {evidence} "
    matches = []
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        normalized_name = normalized_words(name)
        if _is_distinctive_name(name) and normalized_name and f" {normalized_name} " in padded_evidence:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def exact_yes(raw: str) -> bool:
    return (raw or "").strip().casefold() == "yes"


def _candidate_snapshot(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stable, non-GT evidence included in cache keys and audit artifacts."""
    fields = ("name", "provider_place_id", "category", "distance_m", "lat", "lon", "rank")
    return [{field: candidate.get(field) for field in fields} for candidate in candidates]


def cache_key(case: Dict[str, Any], raw_candidates: List[Dict[str, Any]], ranked: List[Dict[str, Any]], model_path: Path) -> str:
    evidence = {
        "dataset": case["_dataset"],
        "photo": case["_photo"],
        "raw_candidates": _candidate_snapshot(raw_candidates),
        "bloggo_ranked": _candidate_snapshot(ranked),
        "bloggo_policy_sha256": hashlib.sha256((ROOT / "examples/mapkit_weighted.py").read_bytes()).hexdigest(),
        "model": model_path.name,
        "evidence_prompt": EVIDENCE_PROMPT,
        "verify_prompt": VERIFY_PROMPT,
        "rule_version": RULE_VERSION,
        "cache_schema": CACHE_SCHEMA,
    }
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                cache[item["key"]] = item
        except json.JSONDecodeError:
            continue
    return cache


def append_cache(path: Path, item: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def decide_without_model(raw_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply Bloggo and decide whether the strict VLM gate is eligible."""
    resolution = bloggo_resolve({"nearby_candidates": raw_candidates})
    ranked = resolution["candidates"]
    base = resolution["selected"]
    if base is None:
        return {"resolution": resolution, "ranked": ranked, "base": None, "decision": "no_usable_bloggo_candidate"}
    if resolution["decision"] != "ambiguous":
        return {"resolution": resolution, "ranked": ranked, "base": base, "decision": "bloggo_clear_winner_vlm_skipped"}
    return {"resolution": resolution, "ranked": ranked, "base": base, "decision": "bloggo_ambiguous_vlm_eligible"}


def write_tsv(path: Path, items: List[Dict[str, Any]]) -> None:
    fields = [
        "dataset", "photo", "prediction", "bloggo_winner", "raw_nearest", "decision",
        "bloggo_gap_m", "bloggo_threshold_m", "ranked_candidates", "visible_text",
        "place_type", "view", "matched_candidate", "evidence_raw", "verification_raw",
        "latency_ms", "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def process_case(case: Dict[str, Any], data_dir: Path, cfg: Dict[str, Any], model_repo: Path,
                 model_path: Path, model: Optional[FastVLM]) -> tuple[Dict[str, Any], Optional[FastVLM]]:
    raw_candidates = case["input"].get("nearby_candidates") or []
    policy = decide_without_model(raw_candidates)
    resolution, ranked, base = policy["resolution"], policy["ranked"], policy["base"]
    raw_nearest = str(raw_candidates[0].get("name") or "").strip() if raw_candidates else ""
    started = time.monotonic()
    evidence_raw = verification_raw = error = ""
    parsed: Optional[Dict[str, str]] = None
    matched: Optional[Dict[str, Any]] = None
    decision = policy["decision"]
    prediction = str(base.get("name") or "").strip() if base else ""

    if base is not None and resolution["decision"] == "ambiguous":
        image = photo_path(data_dir, cfg, case["_dataset"], case["_photo"])
        if image is None:
            decision = "missing_image_bloggo_fallback"
        else:
            try:
                if model is None:
                    model = FastVLM(model_repo, model_path)
                evidence_raw = model.infer(image, EVIDENCE_PROMPT)
                parsed = parse_evidence(evidence_raw)
                if parsed is None:
                    decision = "invalid_evidence_json_bloggo_fallback"
                else:
                    matched = unique_strong_name_match(parsed["visible_text"], ranked)
                    if matched is None:
                        decision = "no_unique_visible_name_bloggo_fallback"
                    elif matched.get("provider_place_id") == base.get("provider_place_id") and matched.get("name") == base.get("name"):
                        decision = "visible_name_confirms_bloggo"
                    else:
                        verification_raw = model.infer(image, VERIFY_PROMPT.format(candidate_name=str(matched.get("name") or "")))
                        if exact_yes(verification_raw):
                            prediction = str(matched.get("name") or "").strip()
                            decision = "verified_visible_name_override"
                        else:
                            decision = "verification_failed_bloggo_fallback"
            except Exception as exc:  # Record then preserve the deterministic Bloggo selection.
                error = repr(exc)
                decision = "inference_error_bloggo_fallback"

    item = {
        "dataset": case["_dataset"], "photo": case["_photo"], "prediction": prediction,
        "bloggo_winner": str(base.get("name") or "").strip() if base else "",
        "raw_nearest": raw_nearest, "decision": decision,
        "bloggo_gap_m": resolution.get("gap_m"), "bloggo_threshold_m": resolution.get("ambiguity_threshold_m"),
        "ranked_candidates": json.dumps([str(candidate.get("name") or "") for candidate in ranked], ensure_ascii=False),
        "visible_text": parsed["visible_text"] if parsed else "",
        "place_type": parsed["place_type"] if parsed else "",
        "view": parsed["view"] if parsed else "",
        "matched_candidate": str(matched.get("name") or "") if matched else "",
        "evidence_raw": evidence_raw, "verification_raw": verification_raw,
        "latency_ms": round((time.monotonic() - started) * 1000), "error": error,
    }
    return item, model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "poi-data"))
    parser.add_argument("--model-repo", default=str(ROOT / "poi-data/tools/ml-fastvlm"))
    parser.add_argument("--model-path", default=str(ROOT / "poi-data/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3"))
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="Smoke-test only: process first N eligible cases")
    parser.add_argument("--cache", default=str(ROOT / "poi-data/generated/fastvlm_bloggo_hybrid_cache.jsonl"))
    parser.add_argument("--results-tsv", default=str(ROOT / "poi-data/fastvlm_bloggo_hybrid_results.tsv"))
    parser.add_argument("--run-name", default="selector-bloggo-vlm-verify")
    args = parser.parse_args()

    data_dir, model_repo, model_path = map(Path, (args.data_dir, args.model_repo, args.model_path))
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    rows = ms.read_rows(str(data_dir / "eval_set_reconciled.csv"))
    candidate_data = ms.load_candidates([str(data_dir / "generated/mapkit_candidates.jsonl")])
    cases = ra.build_cases(rows, cfg, candidate_data, "all", ["image", "nearby_candidates"], args.candidate_limit)
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        raise SystemExit("no eligible cases")

    cache_path = Path(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    model: Optional[FastVLM] = None
    items: List[Dict[str, Any]] = []
    predictions: List[Dict[str, Any]] = []
    for number, case in enumerate(cases, 1):
        raw_candidates = case["input"].get("nearby_candidates") or []
        policy = decide_without_model(raw_candidates)
        key = cache_key(case, raw_candidates, policy["ranked"], model_path)
        item = cache.get(key)
        if item is None:
            item, model = process_case(case, data_dir, cfg, model_repo, model_path, model)
            item["key"] = key
            append_cache(cache_path, item)
        items.append(item)
        predictions.append({"prediction": item["prediction"], "reason": item["decision"], "error": None})
        print(f"[{number}/{len(cases)}] {case['_photo']}: {item['decision']} -> {item['prediction']}", flush=True)

    write_tsv(Path(args.results_tsv), items)
    scored = ra._score(cases, predictions, "exact")
    safe_name = ra._safe_name(args.run_name)
    runs_dir = data_dir / "generated/runs"
    version = ra._pick_version(str(runs_dir), safe_name, "new")
    record = {
        "name": args.run_name, "safe_name": safe_name, "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": "all" if args.limit is None else f"first-{args.limit}",
        "mode": "exact", "params": ["image", "nearby_candidates"], "candidate_limit": args.candidate_limit,
        "lang": "fastvlm-mps-bloggo-verified", "rule_version": RULE_VERSION,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
        "data_snapshot_sha256": ra.data_snapshot_sha256([
            str(data_dir / "eval_set_reconciled.csv"), str(data_dir / "dashboard_config.json"),
            str(data_dir / "generated/mapkit_candidates.jsonl"), str(ROOT / "examples/mapkit_weighted.py"),
        ]),
        "metrics": {key: value for key, value in scored.items() if key != "cases"}, "cases": scored["cases"],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{safe_name}__v{version}.json"
    run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run": str(run_path), "metrics": record["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
