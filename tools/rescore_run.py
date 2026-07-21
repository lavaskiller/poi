#!/usr/bin/env python3
"""Re-score an existing run JSON with current GT + optional alias sidecar.

Does not re-run models. Writes a new run file ``<safe>__vN.json`` (or
``--in-place`` overwrites metrics/cases only when forced).

Example:
  python3 tools/rescore_run.py poi-data/generated/runs/selector-photo-match__v1.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import match_score as ms
import run_algorithm as ra


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_json", help="path to existing run JSON")
    ap.add_argument("--label-relations", default=ms.DEFAULT_LABEL_RELATIONS_PATH)
    ap.add_argument("--out-name", default=None, help="new run name (default: <name>-rescored)")
    ap.add_argument("--runs-dir", default=None)
    args = ap.parse_args()

    path = Path(args.run_json)
    run = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        {
            "_dataset": c["dataset"],
            "_photo": c["photo"],
            "_gt": c["gt"],
            "_provider": c.get("provider") or "mapkit",
        }
        for c in run.get("cases") or []
    ]
    preds = [
        {
            "prediction": c.get("prediction") or "",
            "reason": c.get("reason"),
            "error": c.get("error"),
            "latency_ms": c.get("latency_ms"),
        }
        for c in run.get("cases") or []
    ]
    relations = ms.load_label_relations(args.label_relations)
    scored = ra._score(cases, preds, run.get("mode") or "exact", label_relations=relations)
    metrics = {k: v for k, v in scored.items() if k != "cases"}
    # preserve duration if present
    old_m = run.get("metrics") or {}
    for k in ("duration_ms", "runtime", "latency_ms"):
        if k in old_m and k not in metrics:
            metrics[k] = old_m[k]
    if "latency_ms" in old_m:
        metrics["latency_ms"] = old_m["latency_ms"]
    metrics["rescored_from"] = str(path)
    metrics["label_relations_path"] = args.label_relations
    metrics["label_relations_n"] = len(relations)

    name = args.out_name or f"{run.get('name') or path.stem}-rescored"
    safe = ra._safe_name(name)
    runs_dir = Path(args.runs_dir or path.parent)
    version = ra._pick_version(str(runs_dir), safe, "auto")
    record = {
        **{k: run.get(k) for k in (
            "scope", "mode", "params", "candidate_limit", "lang",
            "script_sha256", "evaluation_set_sha256", "data_snapshot_sha256",
        )},
        "name": name,
        "safe_name": safe,
        "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "label_relations_path": args.label_relations if relations else None,
        "rescored_from": str(path),
        "metrics": metrics,
        "cases": scored["cases"],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    out = runs_dir / f"{safe}__v{version}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "strict": f"{metrics['correct']}/{metrics['n_eligible']} ({metrics['accuracy_pct']}%)",
        "canonical": f"{metrics['correct_canonical']}/{metrics['n_eligible']} ({metrics['accuracy_canonical_pct']}%)",
        "match_kind_counts": metrics.get("match_kind_counts"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
