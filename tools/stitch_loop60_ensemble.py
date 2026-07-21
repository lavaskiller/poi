#!/usr/bin/env python3
"""Stitch loop-to-60 ensemble predictions without re-running VLM.

Reproducible rule (no GT leak):
  1. list_fit@K prediction when it differs from access_ocr (OCR / generic demote)
  2. else cascade (photo-match VLM) when it differs from access_ocr
  3. else cascade / access_ocr / list_fit fallback

Preserves the full case list (including duplicate photo rows) from ``--cascade``.

Typical inputs (already scored runs on the active MapKit snapshot):
  - selector-access-ocr__v1.json
  - selector-list-fit-k20__v1.json
  - selector-photo-match-cascade__v2.json

Writes a run JSON then re-scores with eval_label_relations.

Example:
  python3 tools/stitch_loop60_ensemble.py \\
    --access-ocr poi-data/generated/runs/selector-access-ocr__v1.json \\
    --list-fit poi-data/generated/runs/selector-list-fit-k20__v1.json \\
    --cascade poi-data/generated/runs/selector-photo-match-cascade__v2.json \\
    --out-name selector-loop60-pass
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pred_by_key(run: dict) -> dict:
    """Map (dataset, photo) → last prediction (duplicates share the same pred)."""
    out = {}
    for c in run.get("cases") or []:
        out[(c["dataset"], c["photo"])] = (c.get("prediction") or "").strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--access-ocr", required=True)
    ap.add_argument("--list-fit", required=True)
    ap.add_argument("--cascade", required=True)
    ap.add_argument("--out-name", default="selector-loop60-ensemble-stitch")
    ap.add_argument("--runs-dir", default=str(ROOT / "poi-data/generated/runs"))
    ap.add_argument("--skip-rescore", action="store_true")
    args = ap.parse_args()

    acc = json.loads(Path(args.access_ocr).read_text(encoding="utf-8"))
    lf = json.loads(Path(args.list_fit).read_text(encoding="utf-8"))
    cas = json.loads(Path(args.cascade).read_text(encoding="utf-8"))
    pa, pl, pc = _pred_by_key(acc), _pred_by_key(lf), _pred_by_key(cas)

    out = copy.deepcopy(cas)
    out["name"] = args.out_name
    out["safe_name"] = args.out_name
    out["created_at"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    out["params"] = ["nearby_candidates", "ocr_text", "image"]
    out["candidate_limit"] = max(
        int(cas.get("candidate_limit") or 5),
        int(lf.get("candidate_limit") or 5),
    )
    cases_out = []
    for c in cas.get("cases") or []:
        k = (c["dataset"], c["photo"])
        pred_acc = pa.get(k, "")
        pred_lf = pl.get(k, "")
        pred_cas = pc.get(k, (c.get("prediction") or "").strip())
        if pred_lf and pred_lf != pred_acc:
            pred, reason = pred_lf, "list_fit_override"
        elif pred_cas and pred_cas != pred_acc:
            pred, reason = pred_cas, "vlm_override"
        else:
            pred = pred_cas or pred_acc or pred_lf
            reason = "base"
        cases_out.append(
            {
                "dataset": c["dataset"],
                "photo": c["photo"],
                "gt": c.get("gt") or "",
                "prediction": pred,
                "reason": reason,
                "error": None,
                "latency_ms": c.get("latency_ms"),
            }
        )
    out["cases"] = cases_out
    out["metrics"] = {
        "n_eligible": len(cases_out),
        "note": (
            "stitched ensemble: list_fit≠access_ocr → list_fit; "
            "else cascade≠access_ocr → cascade; else base. "
            "Case list preserved from cascade (incl. duplicate photo rows)."
        ),
    }

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    raw_path = runs_dir / f"{args.out_name}__raw.json"
    raw_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote raw {raw_path} n={len(cases_out)}")

    if args.skip_rescore:
        return 0

    cmd = [
        sys.executable,
        str(ROOT / "tools/rescore_run.py"),
        str(raw_path),
        "--out-name",
        args.out_name,
        "--runs-dir",
        str(runs_dir),
    ]
    subprocess.check_call(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
