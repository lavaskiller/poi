#!/usr/bin/env python3
"""Shared helpers for signal re-run jobs (OCR, MapKit-nearby).

Each re-run worker: select a dataset's rows (optionally only rows not previously
processed), run the existing Swift probe over their photos/coords, merge
the result back into eval_set_reconciled.csv (fill-empty-only by default), and
print `RESULT {json}` (final) + `PROGRESS {json}` (live) lines the server tails.

Reuses gt_classify_common's atomic read/write/backup so all CSV mutations share
one convention (`.bak-STAMP` before write, tmp + os.replace).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402

read_csv = common.read_csv
write_csv = common.write_csv
backup_csv = common.backup_csv
sanitize = common.sanitize


def data_dir() -> str:
    return os.path.dirname(os.path.abspath(ms.CSV_PATH))


def photo_dir_for(dataset: str) -> Optional[str]:
    src = (ms.load_config().get("sources") or {}).get(dataset) or {}
    if src.get("photo_dir"):
        return src["photo_dir"]
    return {"linkedspaces": "linkedspaces-photos", "vancouver": "photos",
            "union-city": "union-city-trip"}.get(dataset)


def is_processed(value) -> bool:
    """Return whether a persisted processing marker represents true."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "done"}


def ensure_column(fieldnames, rows, col: str) -> None:
    """Add a processing-state column without disturbing the existing schema."""
    if col not in fieldnames:
        fieldnames.append(col)
        for row in rows:
            row[col] = ""


def persist_processed_backfill(processed_col: str, evidence_cols) -> Optional[str]:
    """Persist legacy completion evidence when a worker has no probe targets."""
    with common.csv_write_lock(ms.CSV_PATH):
        fieldnames, rows = read_csv(ms.CSV_PATH)
        changed = processed_col not in fieldnames
        ensure_column(fieldnames, rows, processed_col)
        for row in rows:
            if (not is_processed(row.get(processed_col)) and
                    any((row.get(col) or "").strip() for col in evidence_cols)):
                row[processed_col] = "1"
                changed = True
        if not changed:
            return None
        backup = backup_csv(ms.CSV_PATH)
        write_csv(ms.CSV_PATH, fieldnames, rows)
        return backup


def row_key(row) -> str:
    """Stable probe identifier; photo names are only unique within a dataset."""
    return f"{(row.get('dataset') or '').strip()}/{(row.get('photo') or '').strip()}"


def select_rows(rows, dataset, rep_col=None, only_empty=False,
                processed_col=None) -> List[Tuple[int, dict]]:
    """Return rows in ``dataset``.

    For state-aware workers, ``only_empty`` means *not processed*, rather than
    "the result happens to be empty". ``rep_col`` remains as a compatibility
    fallback for workers that do not yet persist processing state.
    """
    out = []
    for i, r in enumerate(rows):
        if dataset and (r.get("dataset") or "").strip() != dataset:
            continue
        if only_empty:
            if processed_col and is_processed(r.get(processed_col)):
                continue
            if not processed_col and rep_col and (r.get(rep_col) or "").strip():
                continue
        out.append((i, r))
    return out


def merge_cell(row, col, value, only_empty) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    if only_empty and (row.get(col) or "").strip():
        return False
    row[col] = value
    return True


def run_swift(swift_file: str, input_tsv: str, out_tsv: str) -> None:
    with open(out_tsv, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(["swift", os.path.join(_ROOT, "tools", "swift", swift_file), input_tsv],
                                stdout=out, stderr=subprocess.PIPE, text=True, bufsize=1)
        for line in proc.stderr:
            # Swift emits machine-readable progress on stderr so TSV stdout stays clean.
            if line.startswith("PROGRESS "): print(line, end="", flush=True)
            else: sys.stderr.write(line)
        rc = proc.wait()
    if rc != 0: raise SystemExit(f"swift probe {swift_file} failed (exit {rc})")


def progress(done: int, total: int) -> None:
    print("PROGRESS " + json.dumps({"done": done, "total": total}), flush=True)


def emit_result(obj: dict) -> None:
    print("RESULT " + json.dumps(obj, ensure_ascii=False), flush=True)
