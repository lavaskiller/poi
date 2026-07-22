#!/usr/bin/env python3
"""Classify ``gt_mapkit`` against MapKit *nearby* candidates (distance-cut).

Policy (product):
  Is the user label written the way MapKit names the place *at this capture
  location*? We answer that by checking whether ``input_place_name`` exact- or
  normalized-matches any name in the wide nearby list after a distance cut
  (default 250 m — same as the MapKit nearby wide radius).

This job does **not** run a separate MapKit name search. It reuses candidates
produced by ``rerun_mapkit_nearby`` / full-candidate snapshots. Run nearby first
(or rely on post-ingest order: mapkit_nearby → gt_mapkit).

Result values: ``KOR`` (non-MapKit provider rows), the verbatim input (exact
match in nearby), ``SIM_MAPKIT`` (normalized match), ``NON_MAPKIT`` (no match
or empty nearby), empty (out of scope).

Usage:
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py --dry-run
  POI_DATA_DIR=/path python3 tools/gt_classify_mapkit.py --radius-m 250
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402

NEARBY_CANDIDATES_NAME = "mapkit_nearby_candidates.jsonl"


def _lookup_candidates(
    grouped: Dict[Tuple[str, str], List[dict]],
    dataset: str,
    photo: str,
) -> Optional[List[dict]]:
    """Resolve candidate list for a CSV row.

    Returns
    -------
    list
        Candidates (possibly empty if nearby returned none).
    None
        No artifact key for this photo (nearby never ran for it).
    """
    ds = (dataset or "").strip()
    ph = (photo or "").strip()
    if not ph:
        return None
    keys = []
    if ds:
        keys.append(f"{ds}/{ph}")
        keys.append(f"{ds}/{os.path.basename(ph)}")
    keys.append(ph)
    keys.append(os.path.basename(ph))
    for k in keys:
        key = (ms.PROVIDER_MAPKIT, k)
        if key in grouped:
            return grouped[key]
    return None


def _load_nearby_grouped(data_dir: str) -> Dict[Tuple[str, str], List[dict]]:
    """Load nearby candidate artifacts; prefer the live nearby cache."""
    generated = os.path.join(data_dir, "generated")
    paths: List[str] = []
    nearby_cache = os.path.join(generated, NEARBY_CANDIDATES_NAME)
    if os.path.isfile(nearby_cache):
        paths.append(nearby_cache)
    # Latest probe TSV from the nearby worker (full wide_candidates_json).
    tsv = os.path.join(data_dir, "rerun_mapkit_output.tsv")
    if os.path.isfile(tsv):
        tmp = os.path.join(generated, "mapkit_nearby_from_tsv.jsonl")
        try:
            ms.convert_mapkit_tsv(tsv, tmp)
            paths.append(tmp)
            print(f"[mapkit] converted probe TSV → {tmp}")
        except ValueError as e:
            print(f"[mapkit] skip TSV convert: {e}")
    # Versioned / legacy evaluation snapshots as fallback.
    try:
        paths.append(ms.active_mapkit_candidate_file(data_dir))
    except RuntimeError as e:
        print(f"[mapkit] active snapshot unavailable: {e}")
    legacy = os.path.join(generated, "mapkit_candidates.jsonl")
    if os.path.isfile(legacy):
        paths.append(legacy)
    # Dedup paths preserving order.
    seen = set()
    uniq = []
    for p in paths:
        ap = os.path.abspath(p)
        if ap in seen or not os.path.isfile(ap):
            continue
        seen.add(ap)
        uniq.append(ap)
    print(f"[mapkit] candidate sources ({len(uniq)}): " + ", ".join(os.path.basename(p) for p in uniq))
    return ms.load_candidates(uniq)


def make_fetch(data_dir: str, radius_m: float):
    def fetch(targets) -> Dict[str, List[str]]:
        grouped = _load_nearby_grouped(data_dir)
        out: Dict[str, List[str]] = {}
        missing = 0
        empty_nearby = 0
        for idx, row in targets:
            ds = (row.get("dataset") or "").strip()
            photo = (row.get("photo") or "").strip()
            cands = _lookup_candidates(grouped, ds, photo)
            if cands is None:
                missing += 1
                out[str(idx)] = []
                continue
            names = ms.names_within_gt_radius(cands, radius_m=radius_m)
            out[str(idx)] = names
            if not names:
                empty_nearby += 1
        print(
            f"[mapkit] GT from nearby ≤{radius_m:g}m: "
            f"targets={len(targets)} missing_artifact={missing} "
            f"in_radius_empty_or_no_name={empty_nearby}"
        )
        if missing:
            print(
                "[mapkit] note: rows without a nearby artifact classify as "
                f"{common.MAPKIT.non_token} — run mapkit_nearby first"
            )
        return out
    return fetch


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Classify gt_mapkit against MapKit nearby names (distance-cut)"
    )
    ap.add_argument("--csv", default=ms.CSV_PATH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    ap.add_argument(
        "--radius-m",
        type=float,
        default=ms.MAPKIT_GT_RADIUS_M,
        help=f"keep nearby names with distance_m ≤ this (default {ms.MAPKIT_GT_RADIUS_M:g}, wide nearby)",
    )
    # Legacy flags kept so old CLI/docs do not hard-fail; ignored.
    ap.add_argument("--no-run", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--probe-in", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--probe-out", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.radius_m <= 0:
        raise SystemExit("--radius-m must be positive")

    data_dir = os.path.dirname(os.path.abspath(args.csv))
    fetch = make_fetch(data_dir, radius_m=float(args.radius_m))
    result = common.run_classification(
        common.MAPKIT, fetch, args.csv, dry_run=args.dry_run,
        dataset=args.dataset, only_empty=args.only_empty,
    )
    if isinstance(result, dict):
        result["gt_source"] = "mapkit_nearby"
        result["gt_radius_m"] = float(args.radius_m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
