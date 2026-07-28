#!/usr/bin/env python3
"""Release gate: score a run on the frozen TEST split and enforce a scorecard.

Accuracy alone is not a promotion criterion. This gate restricts a run to the
sealed test split (``tools/eval_split.py``) and checks a scorecard against a
committed baseline:

  * overall exact + canonical accuracy (within tolerance of baseline)
  * coverage floor            — how much the selector actually answers
  * wrong-leak ceiling        — answered-but-wrong = a wrong POI shown to a user
  * p95 latency ceiling
  * per-slice canonical floors — dataset / category / OCR / candidate-count /
                                 country, so a headline win can't hide a
                                 regression on a slice that matters

Exit code is non-zero when any check fails, so CI can block a merge. With no
baseline it degrades to a report (exit 0). ``emit-baseline`` derives a starting
baseline from a known-good run.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _TOOLS_DIR)
import match_score as ms  # noqa: E402
import eval_split as es  # noqa: E402
from file_ops import atomic_write_json  # noqa: E402

SCHEMA_VERSION = "release-baseline/v1"
_REPO_ROOT = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
DEFAULT_BASELINE = os.path.join(_REPO_ROOT, "eval", "baselines", "baseline.v1.json")

DEFAULT_TOLERANCE = {"accuracy_exact": 0.02, "accuracy_canonical": 0.02, "slice_canonical": 0.05}
DEFAULT_SLICE_MIN_N = 5


def _percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    k = int((p / 100.0) * len(sorted_vals) + 0.999999999) - 1
    k = max(0, min(len(sorted_vals) - 1, k))
    return float(sorted_vals[k])


def _cand_bucket(n_raw: str) -> str:
    try:
        n = int(float(n_raw))
    except (TypeError, ValueError):
        return "unknown"
    if n <= 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 4:
        return "2-4"
    return "5+"


def _slice_keys(row: Dict[str, str]) -> List[str]:
    ds = (row.get("dataset") or "unknown").strip() or "unknown"
    cat = (row.get("category") or "unknown").strip() or "unknown"
    ocr = "ocr" if (row.get("caption_ondevice") or "").strip() else "no_ocr"
    cand = _cand_bucket(row.get("app_nearby_n_wide"))
    country = (row.get("country") or "unknown").strip() or "unknown"
    return [
        f"dataset={ds}", f"category={cat}", f"has_ocr={ocr}",
        f"cand_bucket={cand}", f"country={country}",
    ]


def _index_rows(csv_path: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    rows = ms.read_rows(csv_path)
    rows, _n = ms.overlay_gt_mapkit_overrides(rows)
    return {((r.get("dataset") or "").strip(), (r.get("photo") or "").strip()): r
            for r in rows}


def compute_scorecard(run: Dict[str, Any], split_name: str = "test",
                      csv_path: Optional[str] = None) -> Dict[str, Any]:
    """Overall + per-slice metrics for the run restricted to ``split_name``."""
    csv_path = csv_path or ms.CSV_PATH
    cfg = ms.load_config()
    rows = ms.read_rows(csv_path)
    rows, _n = ms.overlay_gt_mapkit_overrides(rows)
    mem = es.membership(rows, cfg)
    row_by_id = _index_rows(csv_path)
    return scorecard_from(run.get("cases") or [], mem, row_by_id, split_name,
                          run_label=f"{run.get('name')}__v{run.get('version')}")


def scorecard_from(cases: List[Dict[str, Any]],
                   membership_map: Dict[Tuple[str, str], str],
                   row_by_id: Dict[Tuple[str, str], Dict[str, str]],
                   split_name: str = "test",
                   run_label: str = "?") -> Dict[str, Any]:
    """Pure scorecard core: no filesystem, so it is directly unit-testable."""
    target_ids = {k for k, v in membership_map.items() if v == split_name}

    seen_ids = set()
    total = answered = correct_exact = correct_canon = wrong_leak = 0
    latencies: List[float] = []
    slices: Dict[str, Dict[str, int]] = {}

    for c in cases:
        key = ((c.get("dataset") or "").strip(), (c.get("photo") or "").strip())
        if key not in target_ids:
            continue
        seen_ids.add(key)
        total += 1
        pred = (c.get("prediction") or "").strip()
        errored = bool(c.get("error"))
        is_answered = bool(pred) and not errored
        canon = bool(c.get("correct_canonical") or c.get("correct"))
        if is_answered:
            answered += 1
            if not canon:
                wrong_leak += 1
        if c.get("correct"):
            correct_exact += 1
        if canon:
            correct_canon += 1
        lat = c.get("latency_ms")
        if isinstance(lat, (int, float)):
            latencies.append(float(lat))
        row = row_by_id.get(key, {})
        for sk in _slice_keys(row):
            s = slices.setdefault(sk, {"n": 0, "correct_canonical": 0})
            s["n"] += 1
            if canon:
                s["correct_canonical"] += 1

    def _rate(a: int, b: int) -> Optional[float]:
        return round(a / b, 4) if b else None

    ordered = sorted(latencies)
    slice_out = {
        k: {"n": v["n"], "correct_canonical": v["correct_canonical"],
            "accuracy_canonical": _rate(v["correct_canonical"], v["n"])}
        for k, v in sorted(slices.items())
    }
    missing = sorted(f"{d}/{p}" for (d, p) in (target_ids - seen_ids))
    return {
        "split": split_name,
        "run": run_label,
        "overall": {
            "total": total,
            "answered": answered,
            "accuracy_exact": _rate(correct_exact, total),
            "accuracy_canonical": _rate(correct_canon, total),
            "coverage": _rate(answered, total),
            "wrong_leak_rate": _rate(wrong_leak, total),
            "p95_latency_ms": (round(_percentile(ordered, 95), 3)
                               if ordered else None),
        },
        "slices": slice_out,
        "test_ids_total": len(target_ids),
        "test_ids_missing_from_run": missing,
    }


def _cmp(name: str, actual: Optional[float], op: str, threshold: Optional[float],
         checks: List[Dict[str, Any]]) -> None:
    if actual is None or threshold is None:
        checks.append({"check": name, "status": "skip", "actual": actual,
                       "threshold": threshold})
        return
    ok = (actual >= threshold) if op == ">=" else (actual <= threshold)
    checks.append({"check": name, "status": "pass" if ok else "FAIL",
                   "actual": round(actual, 4), "op": op,
                   "threshold": round(threshold, 4)})


def evaluate(scorecard: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """Apply baseline thresholds to a scorecard; return pass/fail + checks."""
    tol = {**DEFAULT_TOLERANCE, **(baseline.get("tolerance") or {})}
    ov = scorecard["overall"]
    b_ov = baseline.get("overall") or {}
    checks: List[Dict[str, Any]] = []

    _cmp("overall.accuracy_exact", ov["accuracy_exact"], ">=",
         (b_ov.get("accuracy_exact") or 0) - tol["accuracy_exact"]
         if b_ov.get("accuracy_exact") is not None else None, checks)
    _cmp("overall.accuracy_canonical", ov["accuracy_canonical"], ">=",
         (b_ov.get("accuracy_canonical") or 0) - tol["accuracy_canonical"]
         if b_ov.get("accuracy_canonical") is not None else None, checks)
    _cmp("overall.coverage", ov["coverage"], ">=", b_ov.get("coverage_min"), checks)
    _cmp("overall.wrong_leak_rate", ov["wrong_leak_rate"], "<=",
         b_ov.get("wrong_leak_max"), checks)
    _cmp("overall.p95_latency_ms", ov["p95_latency_ms"], "<=",
         b_ov.get("p95_latency_ms_max"), checks)

    min_n = baseline.get("slice_min_n", DEFAULT_SLICE_MIN_N)
    for sk, floor in (baseline.get("slices") or {}).items():
        got = scorecard["slices"].get(sk)
        if not got or got["n"] < min_n:
            checks.append({"check": f"slice[{sk}].accuracy_canonical",
                           "status": "skip",
                           "actual": (got or {}).get("accuracy_canonical"),
                           "note": f"n<{min_n}" if got else "absent"})
            continue
        _cmp(f"slice[{sk}].accuracy_canonical", got["accuracy_canonical"], ">=",
             floor - tol["slice_canonical"], checks)

    failed = [c for c in checks if c["status"] == "FAIL"]
    return {"passed": not failed, "n_failed": len(failed), "checks": checks}


def emit_baseline(scorecard: Dict[str, Any], *, slice_min_n: int = DEFAULT_SLICE_MIN_N,
                  wrong_leak_margin: float = 0.02, p95_margin: float = 1.25,
                  ) -> Dict[str, Any]:
    """Derive a starting baseline from a known-good run's scorecard."""
    ov = scorecard["overall"]
    slices = {
        sk: v["accuracy_canonical"]
        for sk, v in scorecard["slices"].items()
        if v["n"] >= slice_min_n and v["accuracy_canonical"] is not None
    }
    return {
        "schema": SCHEMA_VERSION,
        "generated_from_run": scorecard["run"],
        "split": scorecard["split"],
        "tolerance": DEFAULT_TOLERANCE,
        "slice_min_n": slice_min_n,
        "overall": {
            "accuracy_exact": ov["accuracy_exact"],
            "accuracy_canonical": ov["accuracy_canonical"],
            "coverage_min": ov["coverage"],
            "wrong_leak_max": (round((ov["wrong_leak_rate"] or 0) + wrong_leak_margin, 4)),
            "p95_latency_ms_max": (round(ov["p95_latency_ms"] * p95_margin, 3)
                                   if ov["p95_latency_ms"] else None),
        },
        "slices": slices,
    }


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _print_scorecard(sc: Dict[str, Any]) -> None:
    ov = sc["overall"]
    print(f"# release gate — split={sc['split']} run={sc['run']}")
    print(f"  total={ov['total']} answered={ov['answered']} "
          f"exact={ov['accuracy_exact']} canonical={ov['accuracy_canonical']}")
    print(f"  coverage={ov['coverage']} wrong_leak={ov['wrong_leak_rate']} "
          f"p95_ms={ov['p95_latency_ms']}")
    if sc["test_ids_missing_from_run"]:
        print(f"  WARNING: {len(sc['test_ids_missing_from_run'])} test id(s) "
              f"absent from run (of {sc['test_ids_total']})")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_score = sub.add_parser("score", help="score a run and enforce a baseline")
    p_score.add_argument("--run", required=True)
    p_score.add_argument("--baseline", default=DEFAULT_BASELINE)
    p_score.add_argument("--split", default="test")
    p_score.add_argument("--csv", default=None)
    p_score.add_argument("--json", action="store_true", help="emit JSON only")

    p_emit = sub.add_parser("emit-baseline", help="derive a baseline from a good run")
    p_emit.add_argument("--run", required=True)
    p_emit.add_argument("--out", default=DEFAULT_BASELINE)
    p_emit.add_argument("--split", default="test")
    p_emit.add_argument("--csv", default=None)

    args = ap.parse_args(argv)
    run = _load_json(args.run)
    sc = compute_scorecard(run, split_name=args.split, csv_path=args.csv)

    if args.cmd == "emit-baseline":
        baseline = emit_baseline(sc)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        atomic_write_json(args.out, baseline)
        print(json.dumps(baseline, indent=2, ensure_ascii=False))
        return 0

    # score
    if os.path.isfile(args.baseline):
        verdict = evaluate(sc, _load_json(args.baseline))
    else:
        verdict = {"passed": True, "n_failed": 0, "checks": [],
                   "note": f"no baseline at {args.baseline}; report only"}

    if args.json:
        print(json.dumps({"scorecard": sc, "verdict": verdict},
                         indent=2, ensure_ascii=False))
    else:
        _print_scorecard(sc)
        for c in verdict["checks"]:
            print(f"  [{c['status']:>4}] {c['check']}: "
                  f"actual={c.get('actual')} {c.get('op','')} {c.get('threshold','')}"
                  + (f"  ({c['note']})" if c.get("note") else ""))
        print(f"  => {'PASS' if verdict['passed'] else 'FAIL'} "
              f"({verdict['n_failed']} failed)")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
