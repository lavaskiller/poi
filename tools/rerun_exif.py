#!/usr/bin/env python3
"""Fill capture_lat/capture_lon/timestamp from photo EXIF metadata on macOS.

The worker deliberately records only metadata embedded in each local image; it
never guesses a coordinate or derives one from the input place name.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

COLS = ("capture_lat", "capture_lon", "timestamp")


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract EXIF GPS and capture time")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
    missing = [c for c in COLS if c not in fieldnames]
    if missing:
        raise SystemExit("CSV missing columns: " + ", ".join(missing))

    # A coordinate is the representative signal.  The worker still fills a
    # missing timestamp when it encounters an otherwise populated row unless
    # --only-empty was explicitly requested.
    targets = rc.select_rows(rows, args.dataset, rep_col="capture_lat", only_empty=args.only_empty)
    resolved, skipped_no_photo = [], 0
    for _idx, row in targets:
        photo = (row.get("photo") or "").strip()
        pdir = rc.photo_dir_for((row.get("dataset") or "").strip()) or ""
        path = os.path.join(rc.data_dir(), pdir, photo) if photo else ""
        if path and os.path.isfile(path):
            resolved.append((row, path))
        else:
            skipped_no_photo += 1
    print(f"[exif] dataset={args.dataset} targets={len(targets)} resolved={len(resolved)} skipped_no_photo={skipped_no_photo}")
    rc.progress(0, len(resolved))
    if args.dry_run or not resolved:
        rc.emit_result({"ok": True, "step": "exif", "dataset": args.dataset,
                        "only_empty": args.only_empty, "dry_run": args.dry_run,
                        "targets": len(resolved), "filled": 0,
                        "skipped_no_photo": skipped_no_photo,
                        "skip_reason": "no photos to inspect" if not resolved else None})
        return 0

    dd = rc.data_dir()
    input_path, output_path = os.path.join(dd, "rerun_exif_input.tsv"), os.path.join(dd, "rerun_exif_output.tsv")
    with open(input_path, "w", encoding="utf-8") as f:
        f.write("rid\tpath\n")
        for i, (_row, path) in enumerate(resolved):
            f.write(f"{i}\t{path}\n")
    rc.run_swift("exif_extract.swift", input_path, output_path)
    values = {}
    with open(output_path, encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f, delimiter="\t"):
            values[rec.get("rid", "")] = rec

    backup, filled, no_metadata = rc.backup_csv(rc.ms.CSV_PATH), 0, 0
    for i, (row, _path) in enumerate(resolved, 1):
        rec = values.get(str(i - 1), {})
        changed = any(rc.merge_cell(row, col, rec.get(col, ""), args.only_empty) for col in COLS)
        if changed:
            filled += 1
        elif not (rec.get("capture_lat") or rec.get("capture_lon") or rec.get("timestamp")):
            no_metadata += 1
        if i % 10 == 0 or i == len(resolved):
            rc.progress(i, len(resolved))
    rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
    rc.emit_result({"ok": True, "step": "exif", "dataset": args.dataset,
                    "only_empty": args.only_empty, "targets": len(resolved), "filled": filled,
                    "no_metadata": no_metadata, "skipped_no_photo": skipped_no_photo,
                    "backup": backup})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
