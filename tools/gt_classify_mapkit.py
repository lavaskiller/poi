#!/usr/bin/env python3
"""Classify ``gt_mapkit`` by whether ``input_place_name`` is written the MapKit
way. Candidate names come from ``gt_mapkit_classify.swift`` (MKLocalSearch name
search, macOS + Apple Maps). All classification policy lives in
``gt_classify_common``; this file only supplies the MapKit candidate fetch.

Result values: ``KOR`` (Korea rows), the verbatim input (exact MapKit match),
``SIM_MAPKIT`` (normalized match), ``NON_MAPKIT`` (else), empty (out of scope).

Usage:
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py --dry-run
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py --no-run --probe-out out.tsv
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from typing import Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402

SWIFT_PROBE = os.path.join(_ROOT, "tools", "swift", "gt_mapkit_classify.swift")
CAND_SEP = " ||| "


def _write_probe_input(targets, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("rid\tlat\tlon\tquery\n")
        for idx, row in targets:
            f.write("%s\t%s\t%s\t%s\n" % (
                idx,
                common.sanitize(row.get("capture_lat") or ""),
                common.sanitize(row.get("capture_lon") or ""),
                common.sanitize(ms.input_place_name(row)),
            ))


def _run_swift(input_tsv: str, out_tsv: str) -> None:
    with open(out_tsv, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(["swift", SWIFT_PROBE, input_tsv], stdout=out,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
        for line in proc.stderr:
            if line.startswith("PROGRESS "): print(line, end="", flush=True)
            else: sys.stderr.write(line)
        rc = proc.wait()
    if rc != 0: raise SystemExit(f"swift probe failed (exit {rc})")


def _parse_candidates(path: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f, delimiter="\t"):
            rid = (rec.get("rid") or "").strip()
            if not rid:
                continue
            raw = (rec.get("candidates") or "").strip()
            out[rid] = [c.strip() for c in raw.split(CAND_SEP) if c.strip()] if raw else []
    return out


def make_fetch(data_dir: str, no_run: bool, probe_in: str, probe_out: str):
    def fetch(targets):
        if not no_run:
            _write_probe_input(targets, probe_in)
            print(f"[mapkit] probe input: {probe_in} ({len(targets)} queries)")
            print(f"[mapkit] running swift probe -> {probe_out} ...")
            _run_swift(probe_in, probe_out)
        else:
            print(f"[mapkit] reusing probe output: {probe_out}")
        return _parse_candidates(probe_out)
    return fetch


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify gt_mapkit (KOR / verbatim / SIM_MAPKIT / NON_MAPKIT)")
    ap.add_argument("--csv", default=ms.CSV_PATH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-run", action="store_true", help="skip swift probe; reuse --probe-out")
    ap.add_argument("--probe-in", default=None)
    ap.add_argument("--probe-out", default=None)
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    args = ap.parse_args()

    data_dir = os.path.dirname(os.path.abspath(args.csv))
    probe_in = args.probe_in or os.path.join(data_dir, "gt_mapkit_classify_input.tsv")
    probe_out = args.probe_out or os.path.join(data_dir, "gt_mapkit_classify_output.tsv")
    fetch = make_fetch(data_dir, args.no_run, probe_in, probe_out)
    common.run_classification(common.MAPKIT, fetch, args.csv, dry_run=args.dry_run,
                              dataset=args.dataset, only_empty=args.only_empty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
