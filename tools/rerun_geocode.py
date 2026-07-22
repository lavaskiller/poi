#!/usr/bin/env python3
"""Fill city / country / address via reverse geocoding (CLGeocoder on macOS).

Uses each row's capture_lat / capture_lon (already required at ingest). Does not
guess coordinates. Country is written so provider routing (MapKit vs Kakao) can
rely on a real reverse-geocode string rather than an untrusted dataset map.

Usage:
  POI_DATA_DIR=/path python3 tools/rerun_geocode.py [--dataset slug] [--only-empty] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

COLS = ("city", "country", "address")
PROCESSED_COL = "geocode_processed"
REP_COL = "country"  # representative: country is what provider routing needs


def main() -> int:
    ap = argparse.ArgumentParser(description="Reverse-geocode capture coordinates → city/country/address")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
    for c in COLS:
        if c not in fieldnames:
            fieldnames.append(c)
            for r in rows:
                r.setdefault(c, "")
    rc.ensure_column(fieldnames, rows, PROCESSED_COL)

    # Legacy: any filled country proves a prior geocode (or export).
    for row in rows:
        if any((row.get(c) or "").strip() for c in COLS):
            if not rc.is_processed(row.get(PROCESSED_COL)):
                row[PROCESSED_COL] = "1"

    targets = rc.select_rows(
        rows, args.dataset, rep_col=REP_COL,
        only_empty=args.only_empty, processed_col=PROCESSED_COL,
    )
    # Need coordinates to reverse-geocode.
    with_coords = []
    skipped_no_coords = 0
    for idx, row in targets:
        lat = (row.get("capture_lat") or "").strip()
        lon = (row.get("capture_lon") or "").strip()
        if not lat or not lon:
            skipped_no_coords += 1
            continue
        try:
            lat_f, lon_f = float(lat), float(lon)
        except ValueError:
            skipped_no_coords += 1
            continue
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            skipped_no_coords += 1
            continue
        with_coords.append((idx, row, lat, lon))

    print(
        f"[geocode] dataset={args.dataset} targets={len(targets)} "
        f"with_coords={len(with_coords)} skipped_no_coords={skipped_no_coords}",
        flush=True,
    )
    rc.progress(0, len(with_coords))

    if args.dry_run or not with_coords:
        # Persist any legacy processed backfill so only-empty doesn't re-loop forever.
        if not args.dry_run:
            rc.backup_csv(rc.ms.CSV_PATH)
            rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
        rc.emit_result({
            "ok": True,
            "step": "geocode",
            "dataset": args.dataset,
            "only_empty": args.only_empty,
            "dry_run": args.dry_run,
            "targets": len(with_coords),
            "filled": 0,
            "skipped_no_coords": skipped_no_coords,
            "skip_reason": "no rows with coordinates to geocode" if not with_coords else None,
        })
        return 0

    dd = rc.data_dir()
    in_tsv = os.path.join(dd, "rerun_geocode_input.tsv")
    out_tsv = os.path.join(dd, "rerun_geocode_output.tsv")
    with open(in_tsv, "w", encoding="utf-8") as f:
        f.write("rid\tlat\tlon\n")
        for i, (_idx, _row, lat, lon) in enumerate(with_coords):
            f.write(f"{i}\t{lat}\t{lon}\n")

    print(f"[geocode] running geocode_reverse.swift over {len(with_coords)} rows …", flush=True)
    rc.run_swift("geocode_reverse.swift", in_tsv, out_tsv)

    values = {}
    with open(out_tsv, encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f, delimiter="\t"):
            values[rec.get("rid", "")] = rec

    backup = rc.backup_csv(rc.ms.CSV_PATH)
    filled = 0
    empty_result = 0
    for i, (_idx, row, _lat, _lon) in enumerate(with_coords, 1):
        rec = values.get(str(i - 1), {})
        city = (rec.get("city") or "").strip()
        country = (rec.get("country") or "").strip()
        address = (rec.get("address") or "").strip()
        changed = False
        for col, val in (("city", city), ("country", country), ("address", address)):
            if rc.merge_cell(row, col, val, args.only_empty):
                changed = True
        # Mark processed even when Apple returned empty — avoids infinite retry on
        # ocean / blocked coords. Operator can clear geocode_processed to force re-run.
        row[PROCESSED_COL] = "1"
        if changed:
            filled += 1
        if not (city or country or address):
            empty_result += 1
        if i % 5 == 0 or i == len(with_coords):
            rc.progress(i, len(with_coords))

    rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
    rc.emit_result({
        "ok": True,
        "step": "geocode",
        "dataset": args.dataset,
        "only_empty": args.only_empty,
        "targets": len(with_coords),
        "filled": filled,
        "empty_result": empty_result,
        "skipped_no_coords": skipped_no_coords,
        "backup": backup,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
