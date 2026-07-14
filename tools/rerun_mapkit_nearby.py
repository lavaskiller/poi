#!/usr/bin/env python3
"""Re-run the MapKit nearby probe for a dataset via ls_mapkit_probe.swift.

Fills app_poi_rank / app_nearby_top1 / app_nearby_n_wide / app_poi_dist_m from
the wide (250m) search, matching merge_signals.py's column mapping.

Usage:
  POI_DATA_DIR=/path python3 tools/rerun_mapkit_nearby.py --dataset vancouver [--only-empty] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

RANK, NWIDE, DIST, TOP1 = "app_poi_rank", "app_nearby_n_wide", "app_poi_dist_m", "app_nearby_top1"
PROCESSED_COL = "mapkit_nearby_processed"


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-run MapKit nearby probe into app_* columns")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
    for c in (RANK, NWIDE, DIST, TOP1):
        if c not in fieldnames:
            raise SystemExit(f"CSV has no {c} column")

    rc.ensure_column(fieldnames, rows, PROCESSED_COL)
    # Any legacy MapKit cell proves a prior query, including MISS and zero
    # candidates; it must not be queried again indefinitely.
    for row in rows:
        if any((row.get(c) or "").strip() for c in (RANK, NWIDE, DIST, TOP1)):
            row[PROCESSED_COL] = "1"
    targets = rc.select_rows(rows, args.dataset, rep_col=RANK,
                             only_empty=args.only_empty, processed_col=PROCESSED_COL)
    targets = [(i, r) for (i, r) in targets
               if (r.get("capture_lat") or "").strip() and (r.get("capture_lon") or "").strip()]
    print(f"[mapkit_nearby] dataset={args.dataset} targets={len(targets)}")
    rc.progress(0, len(targets))

    if args.dry_run:
        rc.emit_result({"ok": True, "step": "mapkit_nearby", "dataset": args.dataset,
                        "only_empty": args.only_empty, "dry_run": True, "targets": len(targets)})
        return 0
    if not targets:
        backup = rc.persist_processed_backfill(
            PROCESSED_COL, (RANK, NWIDE, DIST, TOP1))
        rc.emit_result({"ok": True, "step": "mapkit_nearby", "dataset": args.dataset,
                        "targets": 0, "filled": 0, "backup": backup})
        return 0

    dd = rc.data_dir()
    in_tsv = os.path.join(dd, "rerun_mapkit_input.tsv")
    out_tsv = os.path.join(dd, "rerun_mapkit_output.tsv")
    # ls_mapkit_probe.swift removeFirst()s a header, then reads photo\tlat\tlon\tkw.
    with open(in_tsv, "w", encoding="utf-8") as f:
        f.write("photo\tlat\tlon\tkw\n")
        for _idx, row in targets:
            f.write("%s\t%s\t%s\t%s\n" % (
                rc.sanitize(rc.row_key(row)),
                rc.sanitize(row.get("capture_lat")),
                rc.sanitize(row.get("capture_lon")),
                rc.sanitize(rc.ms.input_place_name(row))))
    print(f"[mapkit_nearby] running ls_mapkit_probe.swift over {len(targets)} rows ...")
    rc.run_swift("ls_mapkit_probe.swift", in_tsv, out_tsv)

    # 9-col output: photo strict_n strict_rank strict_dist wide_n wide_rank wide_dist retries top3_wide
    res = {}
    with open(out_tsv, encoding="utf-8") as f:
        for i, line in enumerate(f):
            c = line.rstrip("\n").split("\t")
            if i == 0:
                continue  # header
            if len(c) >= 9 and c[0]:
                top1 = ""
                if c[8].strip():
                    part = c[8].split(" | ")[0].strip()
                    top1 = part.rsplit("@", 1)[0].strip() if "@" in part else part
                res[c[0]] = {RANK: c[5], NWIDE: c[4], DIST: c[6], TOP1: top1}

    n = len(targets)
    # Commit only our app_* cells onto the newest CSV under the shared lock.
    with rc.common.csv_write_lock(rc.ms.CSV_PATH):
        fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
        rc.ensure_column(fieldnames, rows, PROCESSED_COL)
        for row in rows:
            if any((row.get(c) or "").strip() for c in (RANK, NWIDE, DIST, TOP1)):
                row[PROCESSED_COL] = "1"
        backup = rc.backup_csv(rc.ms.CSV_PATH)
        filled = 0
        processed = 0
        for row in rows:
            vals = res.get(rc.row_key(row))
            if vals:
                # Persist completion independently of candidate detection, and
                # accept empty cells as the authoritative latest probe result.
                for col, value in vals.items():
                    row[col] = (value or "").strip()
                row[PROCESSED_COL] = "1"
                processed += 1
                try:
                    candidate_count = int((vals.get(NWIDE) or "0").strip())
                except ValueError:
                    candidate_count = 0
                filled += int(candidate_count > 0 or bool((vals.get(TOP1) or "").strip()))
        rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
    rc.progress(n, n)
    rc.emit_result({"ok": True, "step": "mapkit_nearby", "dataset": args.dataset,
                    "only_empty": args.only_empty, "targets": n,
                    "processed": processed, "detected": filled, "filled": filled,
                    "backup": backup})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
