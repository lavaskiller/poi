#!/usr/bin/env python3
"""Re-run the MapKit nearby probe for a dataset via ls_mapkit_probe.swift.

Fills app_poi_rank / app_nearby_top1 / app_nearby_n_wide / app_poi_dist_m from
the wide (250m) search, and persists the *full* wide candidate list (names +
distances) so GT MapKit can label against the same nearby set.

Usage:
  POI_DATA_DIR=/path python3 tools/rerun_mapkit_nearby.py --dataset vancouver [--only-empty] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import rerun_common as rc  # noqa: E402

RANK, NWIDE, DIST, TOP1 = "app_poi_rank", "app_nearby_n_wide", "app_poi_dist_m", "app_nearby_top1"
PROCESSED_COL = "mapkit_nearby_processed"
# Merged full-candidate cache consumed by gt_classify_mapkit (distance-cut GT).
NEARBY_CANDIDATES_JSONL = "mapkit_nearby_candidates.jsonl"


def _candidates_path() -> str:
    return os.path.join(rc.data_dir(), "generated", NEARBY_CANDIDATES_JSONL)


def _parse_probe_output(out_tsv: str) -> Dict[str, Dict[str, Any]]:
    """photo key → {app_* fields, candidates: [dicts]}."""
    res: Dict[str, Dict[str, Any]] = {}
    with open(out_tsv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            top3 = (row.get("top3_wide") or "").strip()
            top1 = ""
            if top3:
                part = top3.split(" | ")[0].strip()
                top1 = part.rsplit("@", 1)[0].strip() if "@" in part else part
            rich: List[dict] = []
            raw = (row.get("wide_candidates_json") or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        rich = [c for c in parsed if isinstance(c, dict)]
                except json.JSONDecodeError:
                    rich = []
            res[photo] = {
                RANK: (row.get("wide_rank") or "").strip(),
                NWIDE: (row.get("wide_n") or "").strip(),
                DIST: (row.get("wide_dist") or "").strip(),
                TOP1: top1,
                "candidates": rich,
            }
    return res


def _merge_nearby_jsonl(path: str, updates: Dict[str, List[dict]], source: str) -> int:
    """Replace candidate lines for updated photo keys; keep others. Returns lines written."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    keep: List[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                photo = (rec.get("photo") or "").strip()
                if photo in updates:
                    continue
                keep.append(json.dumps(rec, ensure_ascii=False))
    n_new = 0
    with open(path, "w", encoding="utf-8") as out:
        for line in keep:
            out.write(line + "\n")
        for photo, cands in updates.items():
            if not cands:
                # Explicit empty nearby response so GT can distinguish "probed, none"
                # from "never probed".
                out.write(json.dumps({
                    "photo": photo,
                    "provider": "mapkit",
                    "candidate_artifact_status": "empty",
                    "source": source,
                }, ensure_ascii=False) + "\n")
                n_new += 1
                continue
            for fallback_rank, cand in enumerate(cands, start=1):
                rec = {
                    "photo": photo,
                    "provider": "mapkit",
                    "provider_place_id": cand.get("provider_place_id"),
                    "name": cand.get("name") or "",
                    "lat": cand.get("lat"),
                    "lon": cand.get("lon"),
                    "address": cand.get("address") or "",
                    "category": cand.get("category") or "",
                    "rank": cand.get("rank") or fallback_rank,
                    "distance_m": cand.get("distance_m"),
                    "source": source,
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_new += 1
    return n_new


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
    cfg = rc.ms.load_config()
    # MapKit nearby is MapKit-provider only. Kakao / unresolved rows must not
    # be probed (and must not get false app_* ranks that look like MapKit GT).
    filtered = []
    skipped_other_provider = 0
    for i, r in targets:
        if not ((r.get("capture_lat") or "").strip() and (r.get("capture_lon") or "").strip()):
            continue
        if rc.ms.provider_for_row(r, cfg) != rc.ms.PROVIDER_MAPKIT:
            skipped_other_provider += 1
            continue
        filtered.append((i, r))
    targets = filtered
    print(
        f"[mapkit_nearby] dataset={args.dataset} targets={len(targets)} "
        f"skipped_other_provider={skipped_other_provider} "
        f"gt_radius_m={rc.ms.MAPKIT_GT_RADIUS_M}",
    )
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

    res = _parse_probe_output(out_tsv)
    # Persist full wide candidates for GT (same set, distance-cut later).
    cand_updates = {k: (v.get("candidates") or []) for k, v in res.items()}
    n_cand_lines = _merge_nearby_jsonl(
        _candidates_path(), cand_updates, source=os.path.basename(out_tsv))
    print(f"[mapkit_nearby] wrote candidate cache {_candidates_path()} (+{n_cand_lines} lines)")

    # GT classification reads the nearby cache above, while algorithm runs
    # require the full candidate artifact. Keep both outputs in sync.
    run_candidates_path = os.path.join(dd, "generated", "mapkit_candidates.jsonl")
    n_run_lines = rc.ms.upsert_mapkit_candidates_from_tsv(out_tsv, run_candidates_path)
    print(f"[mapkit_nearby] upserted run candidates {run_candidates_path} (+{n_run_lines} lines)")
    active_pointer = os.path.join(dd, "generated", rc.ms.ACTIVE_MAPKIT_SNAPSHOT_POINTER)
    if os.path.isfile(active_pointer):
        print(
            "[mapkit_nearby] WARNING: an active immutable MapKit snapshot is selected; "
            "runs will use it instead of the updated legacy JSONL. Rebaseline or "
            "remove the pointer intentionally before testing these candidates.",
            file=sys.stderr,
        )

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
                for col in (RANK, NWIDE, DIST, TOP1):
                    row[col] = (vals.get(col) or "").strip()
                row[PROCESSED_COL] = "1"
                processed += 1
                try:
                    candidate_count = int((vals.get(NWIDE) or "0").strip())
                except ValueError:
                    candidate_count = 0
                filled += int(candidate_count > 0 or bool((vals.get(TOP1) or "").strip()))
        rc.write_csv(rc.ms.CSV_PATH, fieldnames, rows)
    rc.progress(n, n)
    rc.emit_result({
        "ok": True,
        "step": "mapkit_nearby",
        "dataset": args.dataset,
        "only_empty": args.only_empty,
        "targets": n,
        "processed": processed,
        "detected": filled,
        "filled": filled,
        "candidates_path": _candidates_path(),
        "candidate_lines_written": n_cand_lines,
        "run_candidates_path": run_candidates_path,
        "run_candidate_lines_upserted": n_run_lines,
        "backup": backup,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
