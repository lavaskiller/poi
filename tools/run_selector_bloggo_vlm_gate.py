#!/usr/bin/env python3
"""Exploratory semantic-evidence correction layer over MapKit Bloggo.

This runner keeps Bloggo as the default.  On Bloggo-ambiguous cases, FastVLM
first selects from the *raw MapKit Top-5* with the existing baseline prompt.
A non-Bloggo selection may override only when (1) its candidate name contains
one narrowly defined, visually checkable specialty term, and (2) a separate,
candidate-name-free FastVLM prompt answers exactly YES that the photo depicts
that specialty.  It never reads ground truth during prediction.

This is an exploratory replay: the archery failure motivated the rule and the
frozen cohort must not be treated as a deployment/held-out estimate.
"""
from __future__ import annotations

import argparse, csv, datetime, hashlib, json, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "examples"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import match_score as ms
import run_algorithm as ra
from mapkit_weighted import resolve as bloggo_resolve
from run_vlm_topk_rerank import FastVLM, _normalized_words, build_prompt, cache_key as baseline_cache_key, parse_selection, photo_path

# These terms describe a specialized activity/facility that can be assessed from
# a photograph without exposing a candidate name to the verification prompt.
# Generic venue types (restaurant, store, cafe, park, etc.) are deliberately
# excluded because scene type alone is not identity evidence.
SPECIALTY_TERMS = frozenset({"archery", "bowling", "climbing", "golf", "skating"})
VERIFY_PROMPT = """Look at the photo only. Does it unambiguously depict a {term} facility or activity?
Reply with exactly one character: 1 for yes or 0 for no. Use 1 only for directly visible, distinctive evidence; do not infer from location, nearby places, or a venue name."""
RULE_VERSION = "raw-top5-choice+candidate-name-free-specialty-yes-v3-exploratory"
CACHE_SCHEMA = 1


def candidate_specialty_terms(candidate: Dict[str, Any]) -> List[str]:
    """Extract exact specialty words from a candidate name, deterministically."""
    words = set(_normalized_words(str(candidate.get("name") or "")).split())
    return sorted(words & SPECIALTY_TERMS)


def exact_specialty_yes(raw: str) -> bool:
    """Accept only the verifier's one-character affirmative contract."""
    return (raw or "").strip() == "1"


def eligible(raw_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    resolution = bloggo_resolve({"nearby_candidates": raw_candidates})
    return {"resolution": resolution, "ranked": resolution["candidates"], "base": resolution["selected"]}


def verification_cache_key(case: Dict[str, Any], raw: List[Dict[str, Any]], nominated: Dict[str, Any], term: str, model_path: Path) -> str:
    payload = {
        "dataset": case["_dataset"], "photo": case["_photo"],
        "raw_candidates": [{k: c.get(k) for k in ("name", "provider_place_id", "distance_m", "category", "rank")} for c in raw],
        "nominated": {k: nominated.get(k) for k in ("name", "provider_place_id")},
        "term": term, "prompt": VERIFY_PROMPT, "model": model_path.name,
        "rule_version": RULE_VERSION, "cache_schema": CACHE_SCHEMA,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_jsonl(path: Path) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and isinstance(item.get("key"), str):
                    result[item["key"]] = item
            except json.JSONDecodeError:
                pass
    return result


def append_jsonl(path: Path, item: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def process_case(case: Dict[str, Any], data_dir: Path, cfg: Dict[str, Any], model_repo: Path, model_path: Path,
                 selection_cache: Dict[str, Dict[str, Any]], verification_cache: Dict[str, Dict[str, Any]],
                 verification_cache_path: Path, model: Optional[FastVLM]) -> tuple[Dict[str, Any], Optional[FastVLM]]:
    raw = case["input"].get("nearby_candidates") or []
    policy = eligible(raw); base, ranked, resolution = policy["base"], policy["ranked"], policy["resolution"]
    prediction = str(base.get("name") or "").strip() if base else ""
    decision = "no_usable_bloggo_candidate" if base is None else "bloggo_clear_winner_vlm_skipped"
    raw_selection = verification_raw = specialty_term = error = ""
    nominated: Optional[Dict[str, Any]] = None
    selection_source = ""
    started = time.monotonic()

    if base is not None and resolution["decision"] == "ambiguous":
        image = photo_path(data_dir, cfg, case["_dataset"], case["_photo"])
        if image is None:
            decision = "missing_image_bloggo_fallback"
        else:
            try:
                selection_key = baseline_cache_key(case, raw, model_path)
                cached_selection = selection_cache.get(selection_key)
                if cached_selection is not None:
                    raw_selection = str(cached_selection.get("raw_output") or "")
                    selection_source = "baseline_cache"
                else:
                    if model is None: model = FastVLM(model_repo, model_path)
                    raw_selection = model.infer(image, build_prompt(raw))
                    selection_source = "fresh_inference"
                index = parse_selection(raw_selection, raw)
                if index is None:
                    decision = "unusable_selection_bloggo_fallback"
                else:
                    nominated = raw[index]
                    same = nominated.get("provider_place_id") == base.get("provider_place_id") and nominated.get("name") == base.get("name")
                    terms = candidate_specialty_terms(nominated)
                    if same:
                        decision = "vlm_confirms_bloggo"
                    elif len(terms) != 1:
                        decision = "non_specialty_nomination_bloggo_fallback"
                    else:
                        specialty_term = terms[0]
                        key = verification_cache_key(case, raw, nominated, specialty_term, model_path)
                        cached_verification = verification_cache.get(key)
                        if cached_verification is not None:
                            verification_raw = str(cached_verification.get("verification_raw") or "")
                        else:
                            if model is None: model = FastVLM(model_repo, model_path)
                            verification_raw = model.infer(image, VERIFY_PROMPT.format(term=specialty_term))
                            cached_verification = {"key": key, "verification_raw": verification_raw}
                            append_jsonl(verification_cache_path, cached_verification)
                            verification_cache[key] = cached_verification
                        if exact_specialty_yes(verification_raw):
                            prediction = str(nominated.get("name") or "").strip()
                            decision = "specialty_semantic_verified_override"
                        else:
                            decision = "specialty_verification_failed_bloggo_fallback"
            except Exception as exc:
                error = repr(exc); decision = "inference_error_bloggo_fallback"

    return ({
        "dataset": case["_dataset"], "photo": case["_photo"], "prediction": prediction,
        "bloggo_winner": str(base.get("name") or "").strip() if base else "", "decision": decision,
        "bloggo_gap_m": resolution.get("gap_m"), "ranked_candidates": json.dumps([str(c.get("name") or "") for c in ranked], ensure_ascii=False),
        "nominated_candidate": str(nominated.get("name") or "") if nominated else "", "specialty_term": specialty_term,
        "selection_source": selection_source, "selection_raw": raw_selection, "verification_raw": verification_raw,
        "latency_ms": round((time.monotonic() - started) * 1000), "error": error,
    }, model)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "poi-data")); parser.add_argument("--model-repo", default=str(ROOT / "poi-data/tools/ml-fastvlm"))
    parser.add_argument("--model-path", default=str(ROOT / "poi-data/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3")); parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None); parser.add_argument("--selection-cache", default=str(ROOT / "poi-data/generated/fastvlm_top5_cache.jsonl"))
    parser.add_argument("--verification-cache", default=str(ROOT / "poi-data/generated/fastvlm_bloggo_semantic_v3_cache.jsonl")); parser.add_argument("--results-tsv", default=str(ROOT / "poi-data/fastvlm_bloggo_semantic_v3_results.tsv"))
    parser.add_argument("--run-name", default="selector-bloggo-vlm-gate")
    args = parser.parse_args(); data_dir, model_repo, model_path = map(Path, (args.data_dir, args.model_repo, args.model_path))
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    cases = ra.build_cases(ms.read_rows(str(data_dir / "eval_set_reconciled.csv")), cfg, ms.load_candidates([str(data_dir / "generated/mapkit_candidates.jsonl")]), "all", ["image", "nearby_candidates"], args.candidate_limit)
    if args.limit is not None: cases = cases[:args.limit]
    if not cases: raise SystemExit("no eligible cases")
    selection_cache = load_jsonl(Path(args.selection_cache)); verification_path = Path(args.verification_cache); verification_path.parent.mkdir(parents=True, exist_ok=True); verification_cache = load_jsonl(verification_path)
    items: List[Dict[str, Any]] = []; predictions = []; model = None
    for number, case in enumerate(cases, 1):
        item, model = process_case(case, data_dir, cfg, model_repo, model_path, selection_cache, verification_cache, verification_path, model)
        items.append(item); predictions.append({"prediction": item["prediction"], "reason": item["decision"], "error": None})
        print(f"[{number}/{len(cases)}] {case['_photo']}: {item['decision']} -> {item['prediction']}", flush=True)
    fields = list(items[0])
    with Path(args.results_tsv).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader(); writer.writerows(items)
    scored = ra._score(cases, predictions, "exact"); runs_dir = data_dir / "generated/runs"; safe_name = ra._safe_name(args.run_name); version = ra._pick_version(str(runs_dir), safe_name, "new")
    record = {"name": args.run_name, "safe_name": safe_name, "version": version, "created_at": datetime.datetime.now().isoformat(timespec="seconds"), "scope": "all" if args.limit is None else f"first-{args.limit}", "mode": "exact", "params": ["image", "nearby_candidates"], "candidate_limit": args.candidate_limit, "lang": "fastvlm-mps-bloggo-semantic", "rule_version": RULE_VERSION, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "evaluation_set_sha256": ra.evaluation_set_sha256(cases), "data_snapshot_sha256": ra.data_snapshot_sha256([str(data_dir / "eval_set_reconciled.csv"), str(data_dir / "dashboard_config.json"), str(data_dir / "generated/mapkit_candidates.jsonl"), str(ROOT / "examples/mapkit_weighted.py")]), "metrics": {key: value for key, value in scored.items() if key != "cases"}, "cases": scored["cases"]}
    runs_dir.mkdir(parents=True, exist_ok=True); run_path = runs_dir / f"{safe_name}__v{version}.json"; run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run": str(run_path), "metrics": record["metrics"]}, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
