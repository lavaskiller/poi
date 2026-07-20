#!/usr/bin/env python3
"""Run a deterministic OCR evidence layer over the MapKit Bloggo selector.

This is an exploratory replay on the frozen cohort.  It keeps Bloggo's ranked
MapKit Top-5 as the default.  An OCR override is permitted only when exactly one
usable candidate has direct, distinctive name support in the already-recorded
on-device OCR text.  Ground truth is never read by prediction logic.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "examples"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import match_score as ms
import run_algorithm as ra
from mapkit_weighted import resolve as bloggo_resolve
from poi_confidence_policy import ocr_name_support

RULE_VERSION = "unique-direct-ocr-name-support-v1-exploratory"


def supported_candidates(ranked: List[Dict[str, Any]], ocr_text: str) -> List[Dict[str, Any]]:
    """Return unique-name evidence candidates, preferring full strings.

    `ocr_name_support` rejects generic labels and only accepts a full normalized
    candidate name or all of its meaningful tokens.  If any full-name support
    exists, weaker token-only support cannot compete with it.
    """
    evidence: List[Dict[str, Any]] = []
    for candidate in ranked:
        support = ocr_name_support(candidate.get("name"), ocr_text)
        if support["supported"]:
            evidence.append({"candidate": candidate, **support})
    full = [item for item in evidence if item["strength"] == "full_name"]
    return full if full else evidence


def decide(raw_candidates: List[Dict[str, Any]], ocr_text: str) -> Dict[str, Any]:
    resolution = bloggo_resolve({"nearby_candidates": raw_candidates})
    ranked, base = resolution["candidates"], resolution["selected"]
    if base is None:
        return {"prediction": "", "decision": "no_usable_bloggo_candidate", "resolution": resolution,
                "evidence": [], "override": None}
    evidence = supported_candidates(ranked, ocr_text)
    if len(evidence) != 1:
        decision = "no_unique_ocr_name_support_bloggo_fallback"
        if len(evidence) > 1:
            decision = "ambiguous_ocr_name_support_bloggo_fallback"
        return {"prediction": str(base.get("name") or "").strip(), "decision": decision,
                "resolution": resolution, "evidence": evidence, "override": None}
    supported = evidence[0]
    candidate = supported["candidate"]
    if candidate.get("provider_place_id") == base.get("provider_place_id") and candidate.get("name") == base.get("name"):
        return {"prediction": str(base.get("name") or "").strip(), "decision": "ocr_confirms_bloggo",
                "resolution": resolution, "evidence": evidence, "override": None}
    return {"prediction": str(candidate.get("name") or "").strip(), "decision": "unique_ocr_name_override",
            "resolution": resolution, "evidence": evidence, "override": candidate}


def write_tsv(path: Path, items: List[Dict[str, Any]]) -> None:
    fields = ["dataset", "photo", "prediction", "bloggo_winner", "decision", "ocr_text", "ranked_candidates",
              "ocr_supported_candidates", "ocr_strengths", "ocr_matched_tokens", "error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader(); writer.writerows(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "poi-data"))
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="Smoke-test only: process first N eligible cases")
    parser.add_argument("--results-tsv", default=str(ROOT / "poi-data/bloggo_ocr_reranker_results.tsv"))
    parser.add_argument("--run-name", default="selector-ocr-override")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    cases = ra.build_cases(ms.read_rows(str(data_dir / "eval_set_reconciled.csv")), cfg,
                           ms.load_candidates([str(data_dir / "generated/mapkit_candidates.jsonl")]),
                           "all", ["ocr_text", "nearby_candidates"], args.candidate_limit)
    if args.limit is not None: cases = cases[:args.limit]
    if not cases: raise SystemExit("no eligible cases")

    items, predictions = [], []
    for number, case in enumerate(cases, 1):
        raw = case["input"].get("nearby_candidates") or []
        ocr_text = case["input"].get("ocr_text") or ""
        outcome = decide(raw, ocr_text)
        resolution, base, evidence = outcome["resolution"], outcome["resolution"]["selected"], outcome["evidence"]
        item = {
            "dataset": case["_dataset"], "photo": case["_photo"], "prediction": outcome["prediction"],
            "bloggo_winner": str(base.get("name") or "").strip() if base else "", "decision": outcome["decision"],
            "ocr_text": ocr_text,
            "ranked_candidates": json.dumps([str(c.get("name") or "") for c in resolution["candidates"]], ensure_ascii=False),
            "ocr_supported_candidates": json.dumps([str(e["candidate"].get("name") or "") for e in evidence], ensure_ascii=False),
            "ocr_strengths": json.dumps([e["strength"] for e in evidence]),
            "ocr_matched_tokens": json.dumps([e["matched_tokens"] for e in evidence], ensure_ascii=False), "error": "",
        }
        items.append(item); predictions.append({"prediction": item["prediction"], "reason": item["decision"], "error": None})
        print(f"[{number}/{len(cases)}] {case['_photo']}: {item['decision']} -> {item['prediction']}", flush=True)

    write_tsv(Path(args.results_tsv), items)
    scored = ra._score(cases, predictions, "exact")
    safe_name, runs_dir = ra._safe_name(args.run_name), data_dir / "generated/runs"
    version = ra._pick_version(str(runs_dir), safe_name, "new")
    record = {
        "name": args.run_name, "safe_name": safe_name, "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": "all" if args.limit is None else f"first-{args.limit}", "mode": "exact",
        "params": ["ocr_text", "nearby_candidates"], "candidate_limit": args.candidate_limit,
        "lang": "deterministic-bloggo-ocr", "rule_version": RULE_VERSION,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
        "data_snapshot_sha256": ra.data_snapshot_sha256([str(data_dir / "eval_set_reconciled.csv"), str(data_dir / "dashboard_config.json"), str(data_dir / "generated/mapkit_candidates.jsonl"), str(ROOT / "examples/mapkit_weighted.py"), str(ROOT / "examples/poi_confidence_policy.py")]),
        "metrics": {key: value for key, value in scored.items() if key != "cases"}, "cases": scored["cases"],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{safe_name}__v{version}.json"
    run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run": str(run_path), "metrics": record["metrics"]}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
