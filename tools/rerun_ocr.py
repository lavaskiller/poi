#!/usr/bin/env python3
"""Re-run OCR (`caption_ondevice`) for a dataset via ocr_all.swift (Vision).

Usage:
  POI_DATA_DIR=/path python3 tools/rerun_ocr.py --dataset vancouver [--only-empty] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

COL = "caption_ondevice"
PROCESSED_COL = "ocr_processed"


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-run Vision OCR into caption_ondevice")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
    if COL not in fieldnames:
        raise SystemExit(f"CSV has no {COL} column")

    # A non-empty legacy OCR value proves that the row was processed. Persist
    # that fact when this worker next commits; empty results need an explicit
    # marker and must not be selected forever by --only-empty.
    rc.ensure_column(fieldnames, rows, PROCESSED_COL)
    for row in rows:
        if (row.get(COL) or "").strip():
            row[PROCESSED_COL] = "1"
    targets = rc.select_rows(rows, args.dataset, rep_col=COL,
                             only_empty=args.only_empty, processed_col=PROCESSED_COL)

    dd = rc.data_dir()
    resolved = []          # (row, abspath)
    skipped_no_photo = 0
    for _idx, row in targets:
        ph = (row.get("photo") or "").strip()
        pdir = rc.photo_dir_for((row.get("dataset") or "").strip()) or ""
        p = os.path.join(dd, pdir, ph) if ph else ""
        if ph and os.path.isfile(p):
            resolved.append((row, p))
        else:
            skipped_no_photo += 1
    print(f"[ocr] dataset={args.dataset} targets={len(targets)} "
          f"resolved={len(resolved)} skipped_no_photo={skipped_no_photo}")
    rc.progress(0, len(resolved))

    if args.dry_run:
        rc.emit_result({"ok": True, "step": "ocr", "dataset": args.dataset,
                        "only_empty": args.only_empty, "dry_run": True,
                        "targets": len(targets), "resolved": len(resolved)})
        return 0
    if not resolved:
        backup = rc.persist_processed_backfill(PROCESSED_COL, (COL,))
        rc.emit_result({"ok": True, "step": "ocr", "dataset": args.dataset,
                        "targets": 0, "filled": 0, "skipped_no_photo": skipped_no_photo,
                        "backup": backup})
        return 0

    in_tsv = os.path.join(dd, "rerun_ocr_input.tsv")
    out_tsv = os.path.join(dd, "rerun_ocr_output.tsv")
    # ocr_all.swift reads EVERY line as `name<TAB>path` (no header).
    with open(in_tsv, "w", encoding="utf-8") as f:
        for row, p in resolved:
            f.write(f"{rc.sanitize(rc.row_key(row))}\t{p}\n")
    print(f"[ocr] running ocr_all.swift over {len(resolved)} photos ...")
    rc.run_swift("ocr_all.swift", in_tsv, out_tsv)

    text_by_key = {}
    with open(out_tsv, encoding="utf-8") as f:
        for i, line in enumerate(f):
            parts = line.rstrip("\n").split("\t")
            if i == 0 and parts and parts[0] == "photo":
                continue  # header `photo\tocr_text`
            if len(parts) >= 2:
                text_by_key[parts[0]] = parts[1]

    n = len(resolved)
    # Re-read under the shared commit lock: other parallel workers may have
    # replaced the CSV while Vision was running.
    with rc.common.csv_write_lock(rc.ms.CSV_PATH):
        fieldnames, rows = rc.read_csv(rc.ms.CSV_PATH)
        rc.ensure_column(fieldnames, rows, PROCESSED_COL)
        for row in rows:
            if (row.get(COL) or "").strip():
                row[PROCESSED_COL] = "1"
        backup = rc.backup_csv(rc.ms.CSV_PATH)
        filled = 0
        processed = 0
        for row in rows:
            key = rc.row_key(row)
            if key not in text_by_key:
                continue
            # Probe output is authoritative even when it is empty: a full
            # rerun must be able to clear a stale OCR value.
            val = (text_by_key[key] or "").strip()
            row[COL] = val
            row[PROCESSED_COL] = "1"
            processed += 1
            filled += int(bool(val))
        rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
    rc.progress(n, n)
    rc.emit_result({"ok": True, "step": "ocr", "dataset": args.dataset,
                    "only_empty": args.only_empty, "targets": n,
                    "processed": processed, "detected": filled, "filled": filled,
                    "skipped_no_photo": skipped_no_photo, "backup": backup})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
