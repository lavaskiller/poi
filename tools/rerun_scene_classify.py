#!/usr/bin/env python3
"""Classify photos with Vision (VNClassifyImageRequest) → scene_labels.tsv.

Mirrors tools/rerun_ocr.py / ocr_all.swift precompute pattern.

Usage:
  POI_DATA_DIR=/path python3 tools/rerun_scene_classify.py [--dataset X] [--only-missing]
  # writes poi-data/scene_labels.tsv  (photo, scene_top1, scene_top1_conf, scene_labels)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

OUT_NAME = "scene_labels.tsv"


def main() -> int:
    ap = argparse.ArgumentParser(description="Vision scene classify → scene_labels.tsv")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip photos already present in scene_labels.tsv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
    targets = rc.select_rows(rows, args.dataset, rep_col=None, only_empty=False)
    dd = rc.data_dir()
    out_path = os.path.join(dd, OUT_NAME)

    existing = {}
    if os.path.isfile(out_path):
        with open(out_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                ph = (row.get("photo") or "").strip()
                if ph:
                    existing[ph] = row

    resolved = []
    skipped_no_photo = 0
    skipped_have = 0
    for _idx, row in targets:
        ph = (row.get("photo") or "").strip()
        dataset = (row.get("dataset") or "").strip()
        if not ph:
            continue
        # A photo basename is only unique *within* a dataset. Persist the
        # qualified key so labels cannot cross-contaminate datasets and match
        # the gate's (dataset, photo) case identity.
        key = rc.row_key(row)
        if args.only_missing and key in existing and (existing[key].get("scene_labels") or "").strip():
            skipped_have += 1
            continue
        pdir = rc.photo_dir_for(dataset) or ""
        p = os.path.join(dd, pdir, ph) if ph else ""
        if ph and os.path.isfile(p):
            resolved.append((key, p))
        else:
            skipped_no_photo += 1

    print(f"[scene] dataset={args.dataset} targets={len(targets)} "
          f"resolved={len(resolved)} skipped_no_photo={skipped_no_photo} "
          f"skipped_have={skipped_have}")
    rc.progress(0, len(resolved))

    if args.dry_run:
        rc.emit_result({
            "ok": True, "step": "scene_classify", "dataset": args.dataset,
            "dry_run": True, "resolved": len(resolved),
        })
        return 0
    if not resolved:
        rc.emit_result({
            "ok": True, "step": "scene_classify", "dataset": args.dataset,
            "resolved": 0, "written": 0, "skipped_no_photo": skipped_no_photo,
        })
        return 0

    in_tsv = os.path.join(dd, "rerun_scene_input.tsv")
    out_tmp = os.path.join(dd, "rerun_scene_output.tsv")
    # Key by dataset/photo (the stable case identity), not bare basename.
    with open(in_tsv, "w", encoding="utf-8") as f:
        for ph, p in resolved:
            f.write(f"{ph}\t{p}\n")
    print(f"[scene] running scene_classify.swift over {len(resolved)} photos ...")
    rc.run_swift("scene_classify.swift", in_tsv, out_tmp)

    fresh = {}
    with open(out_tmp, encoding="utf-8", newline="") as f:
        for i, line in enumerate(f):
            parts = line.rstrip("\n").split("\t")
            if i == 0 and parts and parts[0] == "photo":
                continue
            if len(parts) >= 4:
                fresh[parts[0]] = {
                    "photo": parts[0],
                    "scene_top1": parts[1],
                    "scene_top1_conf": parts[2],
                    "scene_labels": parts[3],
                }
            elif len(parts) >= 2:
                fresh[parts[0]] = {
                    "photo": parts[0],
                    "scene_top1": parts[1],
                    "scene_top1_conf": "",
                    "scene_labels": "",
                }

    # Merge: existing ∪ fresh (fresh wins)
    merged = dict(existing)
    merged.update(fresh)
    fieldnames_out = ["photo", "scene_top1", "scene_top1_conf", "scene_labels"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames_out, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for ph in sorted(merged.keys()):
            row = merged[ph]
            w.writerow({k: row.get(k, "") for k in fieldnames_out})

    print(f"[scene] wrote {out_path} ({len(merged)} rows, +{len(fresh)} this run)")
    rc.emit_result({
        "ok": True, "step": "scene_classify", "dataset": args.dataset,
        "resolved": len(resolved), "written": len(fresh),
        "total_rows": len(merged), "path": OUT_NAME,
        "skipped_no_photo": skipped_no_photo,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
