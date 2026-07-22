#!/usr/bin/env python3
"""Create an immutable, full-candidate MapKit benchmark snapshot.

The collector never modifies eval_set_reconciled.csv, legacy candidate JSONL, or
rerun_mapkit_*.tsv.  It writes a manifest, raw probe TSV, candidate JSONL and
metadata under generated/candidate-snapshots/<snapshot-id>/.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import match_score as ms  # noqa: E402
import run_algorithm as ra  # noqa: E402
import rerun_common as rc  # noqa: E402


def sha256(path: pathlib.Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def eligible(rows, cfg):
    """Deduplicate by dataset/photo, rejecting ambiguous coordinates."""
    out = {}
    for row in rows:
        ds = (row.get("dataset") or "").strip()
        provider = ms.provider_for_row(row, cfg)
        gt, status = ms.gt_resolution(row, provider)
        if (provider != ms.PROVIDER_MAPKIT or ms.confidence_tier(row, cfg) == "non_poi"
                or status != "canonical"):
            continue
        photo = (row.get("photo") or "").strip()
        lat, lon = (row.get("capture_lat") or "").strip(), (row.get("capture_lon") or "").strip()
        if not photo or not lat or not lon:
            raise ra.RunError(f"eligible case lacks dataset/photo/coordinates: {ds}/{photo}")
        try:
            float(lat); float(lon)
        except ValueError:
            raise ra.RunError(f"eligible case has invalid coordinates: {ds}/{photo}")
        key = (ds, photo)
        value = {"dataset": ds, "photo": photo, "lat": lat, "lon": lon,
                 "keyword": ms.input_place_name(row), "gt": gt}
        prior = out.get(key)
        if prior and (prior["lat"], prior["lon"]) != (lat, lon):
            raise ra.RunError(f"same benchmark key has conflicting coordinates: {ds}/{photo}")
        out[key] = value
    return [out[k] for k in sorted(out)]


def materialize(raw_tsv: pathlib.Path, candidates_jsonl: pathlib.Path):
    rows = []
    with raw_tsv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            source_key = (row.get("photo") or "").strip()
            if "/" not in source_key:
                raise ra.RunError(f"probe result has unqualified photo key: {source_key!r}")
            dataset, photo = source_key.split("/", 1)
            try:
                parsed = json.loads(row.get("wide_candidates_json") or "")
            except json.JSONDecodeError as e:
                raise ra.RunError(f"invalid wide_candidates_json for {source_key}: {e}")
            if not isinstance(parsed, list):
                raise ra.RunError(f"wide_candidates_json is not a list for {source_key}")
            # ``[]`` is a completed MapKit response, not a missing candidate
            # artifact. A flat JSONL needs an explicit sentinel to preserve it.
            if not parsed:
                rows.append({"dataset": dataset, "photo": photo, "provider": "mapkit",
                             "candidate_artifact_status": "empty", "source": raw_tsv.name})
                continue
            seen_ranks = set()
            for fallback_rank, candidate in enumerate(parsed, 1):
                if not isinstance(candidate, dict) or not (candidate.get("name") or "").strip():
                    raise ra.RunError(f"invalid candidate for {source_key}")
                rank = candidate.get("rank")
                if type(rank) is not int or rank < 1 or rank in seen_ranks:
                    raise ra.RunError(f"invalid/non-unique raw rank for {source_key}: {rank!r}")
                seen_ranks.add(rank)
                record = {"dataset": dataset, "photo": photo, "provider": "mapkit",
                          "name": candidate["name"].strip(), "rank": rank,
                          "distance_m": candidate.get("distance_m"),
                          "category": candidate.get("category") or "",
                          "provider_place_id": candidate.get("provider_place_id"),
                          "lat": candidate.get("lat"), "lon": candidate.get("lon"),
                          "source": raw_tsv.name}
                rows.append(record)
    with candidates_jsonl.open("w", encoding="utf-8") as out:
        for record in rows:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return rows


def validate_coverage(cases, manifest_rows):
    """Verify every deduplicated collection target is represented.

    Several eligible CSV rows share one dataset/photo collection target. Validate
    dataset/photo key coverage, not a misleading equality of row counts.
    """
    expected = {(r["dataset"], r["photo"]) for r in manifest_rows}
    actual = {(c["_dataset"], c["_photo"]) for c in cases}
    if actual != expected:
        missing, unexpected = sorted(expected - actual), sorted(actual - expected)
        raise ra.RunError(
            "materialized benchmark keys differ from manifest "
            f"(missing={missing[:3]}, unexpected={unexpected[:3]})"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default=dt.datetime.now(dt.timezone.utc).strftime("mapkit-%Y%m%dT%H%M%SZ"))
    ap.add_argument("--execute", action="store_true", help="perform live MapKit queries (otherwise create manifest only)")
    ap.add_argument("--finalize-existing", action="store_true",
                    help="materialize and validate existing raw probe output without querying MapKit")
    ap.add_argument("--data-dir", default=ms.DATA_ROOT)
    args = ap.parse_args()
    if not args.snapshot_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("snapshot-id must contain only letters, digits, '-' or '_'")
    data_dir = pathlib.Path(args.data_dir).resolve()
    csv_path, config_path = data_dir / "eval_set_reconciled.csv", data_dir / "dashboard_config.json"
    cfg, rows = ms.load_config(str(config_path)), ms.read_rows(str(csv_path))
    manifest_rows = eligible(rows, cfg)
    dest = data_dir / "generated" / "candidate-snapshots" / args.snapshot_id
    if args.execute and args.finalize_existing:
        raise SystemExit("--execute and --finalize-existing are mutually exclusive")
    if args.finalize_existing:
        raw_tsv, candidate_jsonl = dest / "mapkit-full-output.tsv", dest / "mapkit_candidates.jsonl"
        if not dest.is_dir() or not raw_tsv.is_file():
            raise SystemExit(f"no existing raw probe output to finalize: {raw_tsv}")
        records = materialize(raw_tsv, candidate_jsonl)
        loaded = ms.load_candidates([str(candidate_jsonl)])
        cases = ra.build_cases(rows, cfg, loaded, "all", ["nearby_candidates"], 5,
                               require_candidate_artifact=True)
        validate_coverage(cases, manifest_rows)
        metadata_path = dest / "metadata.json"
        metadata = (json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata_path.exists() else {})
        metadata.update({"snapshot_id": args.snapshot_id,
                         "kind": "live_mapkit_full_candidate_snapshot",
                         "status": "complete",
                         "finalized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                         "collection_target_count": len(manifest_rows),
                         "evaluation_case_count": len(cases),
                         "raw_probe_output": raw_tsv.name,
                         "candidate_artifact": candidate_jsonl.name,
                         "candidate_records": len(records),
                         "candidate_artifact_sha256": sha256(candidate_jsonl),
                         "candidate_counts": dict(sorted(Counter(len(c["input"]["nearby_candidates"]) for c in cases).items())),
                         "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
                         "no_csv_mutation": True,
                         "no_legacy_candidate_artifact_mutation": True})
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "finalized_existing": True, "snapshot_dir": str(dest),
                          "cases": len(cases), "candidate_records": len(records)}))
        return 0
    if dest.exists():
        raise SystemExit(f"snapshot destination already exists: {dest}")
    dest.mkdir(parents=True)
    manifest = dest / "input-manifest.tsv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["dataset", "photo", "lat", "lon", "keyword", "gt"], delimiter="\t")
        writer.writeheader(); writer.writerows(manifest_rows)
    metadata = {"snapshot_id": args.snapshot_id, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "kind": "live_mapkit_full_candidate_snapshot", "status": "manifest_created",
                "collection_target_count": len(manifest_rows), "input_manifest": manifest.name,
                "input_manifest_sha256": sha256(manifest), "source_csv_sha256": sha256(csv_path),
                "probe": {"script": "tools/swift/ls_mapkit_probe.swift", "wide_radius_m": 250,
                          "strict_radius_m": 80, "rank_order": "distance_from_capture_coordinate"},
                "no_csv_mutation": True, "no_legacy_candidate_artifact_mutation": True}
    if not args.execute:
        (dest / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "dry_run": True, "snapshot_dir": str(dest), "cases": len(manifest_rows)}))
        return 0
    probe_input, raw_tsv, candidate_jsonl = dest / "probe-input.tsv", dest / "mapkit-full-output.tsv", dest / "mapkit_candidates.jsonl"
    with probe_input.open("w", encoding="utf-8") as f:
        f.write("photo\tlat\tlon\tkw\n")
        for r in manifest_rows:
            f.write(f"{r['dataset']}/{r['photo']}\t{r['lat']}\t{r['lon']}\t{r['keyword']}\n")
    rc.run_swift("ls_mapkit_probe.swift", str(probe_input), str(raw_tsv))
    records = materialize(raw_tsv, candidate_jsonl)
    loaded = ms.load_candidates([str(candidate_jsonl)])
    cases = ra.build_cases(rows, cfg, loaded, "all", ["nearby_candidates"], 5, require_candidate_artifact=True)
    validate_coverage(cases, manifest_rows)
    metadata.update({"status": "complete", "probe_input": probe_input.name, "raw_probe_output": raw_tsv.name,
                     "candidate_artifact": candidate_jsonl.name, "candidate_records": len(records),
                     "candidate_artifact_sha256": sha256(candidate_jsonl),
                     "collection_target_count": len(manifest_rows),
                     "evaluation_case_count": len(cases),
                     "candidate_counts": dict(sorted(Counter(len(c["input"]["nearby_candidates"]) for c in cases).items())),
                     "evaluation_set_sha256": ra.evaluation_set_sha256(cases)})
    (dest / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "snapshot_dir": str(dest), "cases": len(cases), "candidate_records": len(records)}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
