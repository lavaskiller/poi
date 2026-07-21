#!/usr/bin/env python3
"""Simulate AUTO_PICK / SHOW_PICKER / NONE policy on a labeled local cohort.

Ground truth is only read for post-hoc metrics. It is never added to policy
inputs. The report is JSON and contains both aggregated risk/coverage metrics
and case-level action tiers for audit.

Example (private data remains outside Git):
    python3 tools/simulate_confidence_policy.py \
      --output poi-data/generated/confidence-policy-v0.json
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import match_score as ms
import run_algorithm as ra

POLICY_PATH = ROOT / "examples" / "poi_confidence_policy.py"
SPEC = importlib.util.spec_from_file_location("poi_confidence_policy", POLICY_PATH)
policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(policy)


def _read_tsv_by_photo(path: Path, value_fields: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """Read optional OCR/VLM side data without prescribing a private schema."""
    output: Dict[str, Dict[str, str]] = {}
    if not path.is_file():
        return output
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            output[photo] = {field: (row.get(field) or "").strip() for field in value_fields}
    return output


def _slim_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": candidate.get("name", ""),
        "provider_place_id": candidate.get("provider_place_id"),
        "category": candidate.get("normalized_category", candidate.get("category", "")),
        "distance_m": candidate.get("physical_distance_m", candidate.get("distance_m")),
        "effective_distance_m": candidate.get("effective_distance_m"),
    }


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def simulate(cases: List[Dict[str, Any]], ocr_by_photo: Dict[str, Dict[str, str]],
             vlm_by_photo: Dict[str, Dict[str, str]], picker_limit: int) -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    action_counts = {policy.AUTO_PICK: 0, policy.SHOW_PICKER: 0, policy.NONE: 0}
    auto_correct = auto_wrong = picker_gt_top5 = picker_gt_visible = nearest_correct = 0

    for item in cases:
        public = dict(item["input"])
        photo = item["_photo"]
        # Side files are optional inference signals. VLM's `decision` identifies
        # whether the value was a true selection or just a nearest fallback.
        if photo in ocr_by_photo:
            public["ocr_text"] = ocr_by_photo[photo].get("ocr_text", "")
        if photo in vlm_by_photo:
            public["vlm_prediction"] = vlm_by_photo[photo].get("prediction", "")
            public["vlm_decision"] = vlm_by_photo[photo].get("decision", "")

        outcome = policy.decide(public)
        action = outcome["action"]
        action_counts[action] += 1
        selected = outcome["selected"]
        selected_name = (selected or {}).get("name", "")
        gt = item["_gt"]
        selected_correct = ms.exact_equal(selected_name, gt)
        candidates = outcome["resolution"]["candidates"]
        visible = candidates[:picker_limit]
        gt_in_top5 = any(ms.exact_equal(c.get("name", ""), gt) for c in visible)
        gt_in_ranked = any(ms.exact_equal(c.get("name", ""), gt) for c in candidates)
        nearest = min(candidates, key=lambda c: (
            c.get("physical_distance_m") is None,
            c.get("physical_distance_m") if c.get("physical_distance_m") is not None else float("inf"),
            c.get("original_index", 0),
        )) if candidates else None
        nearest_name = (nearest or {}).get("name", "")
        nearest_correct += int(ms.exact_equal(nearest_name, gt))

        if action == policy.AUTO_PICK:
            auto_correct += int(selected_correct)
            auto_wrong += int(not selected_correct)
        elif action == policy.SHOW_PICKER:
            picker_gt_top5 += int(gt_in_top5)
            picker_gt_visible += int(gt_in_ranked)

        details.append({
            "dataset": item["_dataset"], "photo": photo,
            "action": action, "reason_codes": outcome["reason_codes"],
            "selected": selected_name, "selected_correct": selected_correct,
            "nearest": nearest_name, "nearest_correct": ms.exact_equal(nearest_name, gt),
            "weighted_decision": outcome["resolution"]["decision"],
            "margin_m": outcome["resolution"].get("gap_m"),
            "picker_gt_in_top5": gt_in_top5, "picker_gt_in_ranked": gt_in_ranked,
            "candidates": [_slim_candidate(c) for c in candidates],
        })

    total = len(cases)
    auto_total = action_counts[policy.AUTO_PICK]
    picker_total = action_counts[policy.SHOW_PICKER]
    none_total = action_counts[policy.NONE]
    return {
        "policy": {
            "module": str(POLICY_PATH.relative_to(ROOT)),
            "auto_margin_m": policy.AUTO_MARGIN_M,
            "picker_initial_limit": picker_limit,
            "note": "Action tiers are calibrated rules, not probability estimates.",
        },
        "metrics": {
            "n_eligible": total,
            "actions": action_counts,
            "auto_coverage": _rate(auto_total, total),
            "auto_precision": _rate(auto_correct, auto_total),
            "wrong_auto_count": auto_wrong,
            "wrong_auto_rate": _rate(auto_wrong, total),
            "picker_rate": _rate(picker_total, total),
            "picker_recall_at_5": _rate(picker_gt_top5, picker_total),
            "picker_recall_in_ranked": _rate(picker_gt_visible, picker_total),
            "no_result_rate": _rate(none_total, total),
            "nearest_accuracy_same_cohort": _rate(nearest_correct, total),
        },
        "cases": details,
    }


def main() -> int:
    data_root = Path(os.environ.get("POI_DATA_DIR") or ROOT / "poi-data")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(data_root))
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--csv", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--candidates", nargs="*", default=None)
    parser.add_argument("--ocr-tsv", default=None, help="Optional TSV with photo, ocr_text columns")
    parser.add_argument("--vlm-tsv", default=None, help="Optional TSV with photo, prediction, decision columns")
    parser.add_argument("--picker-limit", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.picker_limit <= policy.PICKER_LIMIT:
        parser.error("--picker-limit must be between 1 and %d" % policy.PICKER_LIMIT)

    data_dir = Path(args.data_dir)
    csv_path = args.csv or str(data_dir / "eval_set_reconciled.csv")
    config_path = args.config or str(data_dir / "dashboard_config.json")
    candidate_paths = args.candidates if args.candidates is not None else [str(data_dir / "generated/mapkit_candidates.jsonl")]
    rows = ms.read_rows(csv_path)
    cfg = ms.load_config(config_path)
    candidates = ms.load_candidates(candidate_paths)
    cases = ra.build_cases(rows, cfg, candidates, args.dataset, ["nearby_candidates"])
    if not cases:
        raise SystemExit("no eligible cases: need provider-canonical non-Korea GT")

    ocr_path = Path(args.ocr_tsv) if args.ocr_tsv else data_dir / "ls_ocr_text.tsv"
    vlm_path = Path(args.vlm_tsv) if args.vlm_tsv else data_dir / "fastvlm_results.tsv"
    report = simulate(
        cases,
        _read_tsv_by_photo(ocr_path, ("ocr_text",)),
        _read_tsv_by_photo(vlm_path, ("prediction", "decision")),
        args.picker_limit,
    )
    report["inputs"] = {
        "csv": csv_path, "config": config_path, "candidate_paths": candidate_paths,
        "ocr_tsv": str(ocr_path) if ocr_path.is_file() else None,
        "vlm_tsv": str(vlm_path) if vlm_path.is_file() else None,
        "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
        "data_snapshot_sha256": ra.data_snapshot_sha256([csv_path, config_path, *candidate_paths]),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = report["metrics"]
    print("wrote", output)
    print("eligible={n_eligible} auto={auto_coverage:.1%} precision={auto_precision:.1%} "
          "wrong-auto={wrong_auto_rate:.1%} picker={picker_rate:.1%} "
          "picker-recall@5={picker_recall_at_5:.1%} none={no_result_rate:.1%}".format(**metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
