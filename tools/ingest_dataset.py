#!/usr/bin/env python3
"""Ingest a validated dataset ZIP into eval_set_reconciled.csv (append job).

Runs as a background job (tracked in the job panel). Given an upload package
(`dataset_slug/manifest.csv` + `photos/`), it: validates the package, copies
photos into the dataset's photo dir under POI_DATA_DIR, appends one CSV row per
manifest row (dataset=slug, photo=basename, input_place_name=gt_input_raw,
notes, gt_confidence=source default, plus required capture_lat/capture_lon/
timestamp from the manifest and/or EXIF), and registers the source in
dashboard_config.json if new. A successful server-managed ingest then starts
its EXIF/OCR/MapKit/GT post-processing pipeline (fill-empty-only). Geocoding is
reported as skipped until a real CLGeocoder worker is implemented.

Usage:
  POI_DATA_DIR=/path python3 tools/ingest_dataset.py --zip /path/to/pkg.zip [--dataset slug]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import PurePosixPath
from typing import Set

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402
from validate_upload_package import validate_zip, ValidationError  # noqa: E402
from photo_names import (  # noqa: E402
    CaptureGpsRequired,
    CaptureTimeRequired,
    allocate_local_photo_basenames,
    resolve_capture_gps,
)


# Stable store schema used when the first upload bootstraps a fresh data root.
# ``photo`` is the local eval identity (0001.jpg …). ``photo_original`` keeps
# the upload basename for provenance only — never used as a join key.
CANONICAL_FIELDS = [
    "dataset", "photo", "photo_original", "capture_lat", "capture_lon", "timestamp",
    "caption_oracle", "caption_ondevice", "input_place_name", "gt_mapkit",
    "gt_kakao", "poi_list_match", "poi_match_keyword", "category",
    "gt_confidence", "baseline_place_title", "app_nearby_n_wide",
    "app_poi_rank", "app_poi_dist_m", "app_nearby_top1", "notes",
    "username", "city", "country", "address", "photo_url",
]


def _progress(done, total):
    print("PROGRESS " + json.dumps({"done": done, "total": total}), flush=True)


def _result(obj):
    print("RESULT " + json.dumps(obj, ensure_ascii=False), flush=True)


def _photo_dir_for(cfg, slug):
    src = (cfg.get("sources") or {}).get(slug) or {}
    return src.get("photo_dir") or f"{slug}-photos"


def _extract_rows(zip_path, report, root, slug, photo_dir, dest_dir, default_conf):
    """Copy package photos under local composite names; return row fragments.

    Local identity: ``{dataset}_{YYYYMMDD}_{sha256[:12]}{ext}`` (see
    ``photo_names``). Capture time and GPS are required: manifest columns or
    EXIF; resolved values are always written to the CSV row. Upload basenames
    go to ``photo_original`` only.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = set(n.replace("\\", "/").lstrip("/") for n in zf.namelist())
        manifest_text = zf.read(report["manifest_path"]).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(manifest_text)))
        n = len(rows)
        print(
            f"[ingest] slug={slug} manifest_rows={n} photo_dir={photo_dir} "
            f"local_ids={{dataset}}_{{YYYYMMDD}}_{{sha256[:12]}} "
            f"(capture time + GPS required)",
            flush=True,
        )
        _progress(0, n)

        # Read each photo once → (name, bytes, dataset, timestamp) for allocate.
        payloads: list = []
        for i, r in enumerate(rows, start=2):
            photo_rel = (r.get("photo") or "").strip()
            raw_base = PurePosixPath(photo_rel).name if photo_rel else ""
            src_name = f"{root}/{photo_rel}" if root else photo_rel
            data = b""
            if photo_rel and src_name in names:
                with zf.open(src_name) as src:
                    data = src.read()
            ts = (r.get("timestamp") or r.get("capture_time") or "").strip() or None
            payloads.append((raw_base, data, slug, ts))

        try:
            allocated = allocate_local_photo_basenames(payloads)
        except CaptureTimeRequired as e:
            # Surface as a clean ingest failure (which rows lack time).
            missing = []
            from photo_names import resolve_capture_timestamp
            for i, (raw, data, _ds, ts) in enumerate(payloads, start=2):
                try:
                    resolve_capture_timestamp(ts, data if data else None)
                except CaptureTimeRequired:
                    missing.append({"row": i, "photo": raw or "(empty)"})
            raise CaptureTimeRequired(
                f"{e}; {len(missing)} row(s) without capture time: "
                + ", ".join(f"row {m['row']} ({m['photo']})" for m in missing[:8])
                + ("…" if len(missing) > 8 else "")
            ) from e

        new_rows = []
        photos_copied = photos_missing = 0
        written: Set[str] = set()
        filled_ts_from_exif = 0
        filled_gps_from_exif = 0
        for i, (r, (_raw, data, _ds, ts_in), (raw_base, local_base, photo_original, ts_iso)) in enumerate(
            zip(rows, payloads, allocated), 1
        ):
            dest_path = os.path.join(dest_dir, local_base)
            if data:
                if local_base not in written:
                    with open(dest_path, "wb") as out:
                        out.write(data)
                    written.add(local_base)
                photos_copied += 1
            else:
                photos_missing += 1
            if not (ts_in or "").strip():
                filled_ts_from_exif += 1
            lat_in = (r.get("lat") or r.get("capture_lat") or "").strip()
            lon_in = (r.get("lon") or r.get("capture_lon") or "").strip()
            lat_out, lon_out = resolve_capture_gps(
                lat_in or None, lon_in or None, data if data else None
            )
            if not (lat_in and lon_in):
                filled_gps_from_exif += 1
            new_rows.append({
                "dataset": slug,
                "photo": local_base,
                "photo_original": photo_original or raw_base,
                "input_place_name": (r.get("gt_input_raw") or "").strip(),
                "notes": (r.get("notes") or "").strip(),
                "gt_confidence": default_conf,
                # Always filled: manifest value or EXIF-resolved coordinates.
                "capture_lat": lat_out,
                "capture_lon": lon_out,
                # Always filled: manifest value or EXIF-resolved ISO.
                "timestamp": ts_iso,
            })
            if i % 5 == 0 or i == n:
                _progress(i, n)
        print(
            f"[ingest] local ids for {len(allocated)} rows "
            f"({len(written)} unique files; "
            f"{filled_ts_from_exif} timestamps from EXIF; "
            f"{filled_gps_from_exif} GPS from EXIF) "
            f"e.g. {allocated[0][1] if allocated else '—'}",
            flush=True,
        )
    return new_rows, photos_copied, photos_missing


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest a dataset ZIP (append rows + copy photos)")
    ap.add_argument("--zip", required=True)
    ap.add_argument("--dataset", default=None, help="override slug (default: ZIP root dir)")
    args = ap.parse_args()

    # 1. validate the package shape first (reuse the validator).
    try:
        report = validate_zip(args.zip)
    except ValidationError as e:
        _result({"ok": False, "step": "ingest", "error": f"invalid ZIP: {e}"})
        return 1
    if not report.get("ok"):
        codes = [e.get("code") for e in report.get("errors", [])]
        _result({"ok": False, "step": "ingest", "error": "validation failed",
                 "errors": report.get("errors", [])[:10], "codes": codes})
        return 1

    root = report["dataset_root"]
    slug = (args.dataset or root or "").strip()
    if not slug:
        _result({"ok": False, "step": "ingest", "error": "no dataset slug"})
        return 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        _result({"ok": False, "step": "ingest",
                 "error": "dataset slug may contain only letters, numbers, dot, underscore, and hyphen"})
        return 1

    data_dir = os.path.dirname(os.path.abspath(ms.CSV_PATH))
    try:
        cfg = ms.load_config()
    except Exception as e:
        _result({"ok": False, "step": "ingest", "error": f"could not read config: {e}"})
        return 1
    photo_dir = _photo_dir_for(cfg, slug)
    dest_dir = os.path.abspath(os.path.join(data_dir, photo_dir))
    if not (dest_dir.startswith(data_dir + os.sep) and dest_dir != data_dir):
        _result({"ok": False, "step": "ingest", "error": "configured photo directory escapes the data root"})
        return 1

    # Reject conflicts before copying anything. This keeps a failed ingestion from
    # leaving photos behind, including when the data-root directory is brand new.
    csv_existed = os.path.isfile(ms.CSV_PATH)
    try:
        if csv_existed:
            fieldnames, existing = common.read_csv(ms.CSV_PATH)
            if not fieldnames:
                fieldnames = list(CANONICAL_FIELDS)
        else:
            fieldnames, existing = list(CANONICAL_FIELDS), []
    except Exception as e:
        _result({"ok": False, "step": "ingest", "error": f"could not read existing CSV: {e}"})
        return 1
    # Ensure provenance column exists for new and legacy CSVs.
    if "photo_original" not in fieldnames:
        # Insert right after photo for readability.
        if "photo" in fieldnames:
            i = fieldnames.index("photo") + 1
            fieldnames = list(fieldnames[:i]) + ["photo_original"] + list(fieldnames[i:])
        else:
            fieldnames = list(fieldnames) + ["photo_original"]
    if slug in {(x.get("dataset") or "").strip() for x in existing}:
        _result({"ok": False, "step": "ingest", "error": f"dataset {slug!r} already exists"})
        return 1
    if os.path.exists(dest_dir):
        _result({"ok": False, "step": "ingest", "error": f"photo directory already exists: {photo_dir}"})
        return 1

    # 2–3. Extract into a newly created directory. Any read/copy failure removes
    # the directory before returning, including failures after a partial copy.
    os.makedirs(dest_dir)
    default_conf = ((cfg.get("sources") or {}).get(slug) or {}).get(
        "default_confidence", "confirmed_user")
    try:
        new_rows, photos_copied, photos_missing = _extract_rows(
            args.zip, report, root, slug, photo_dir, dest_dir, default_conf)
    except CaptureTimeRequired as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        _result({"ok": False, "step": "ingest", "error": str(e),
                 "error_code": "capture_time_required"})
        return 1
    except CaptureGpsRequired as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        _result({"ok": False, "step": "ingest", "error": str(e),
                 "error_code": "capture_gps_required"})
        return 1
    except Exception as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        _result({"ok": False, "step": "ingest", "error": f"photo extraction failed: {e}"})
        return 1

    # 4. Append atomically. A backup/write failure also removes copied photos;
    # write_csv itself leaves the prior CSV intact when atomic replacement fails.
    backup = None
    try:
        backup = common.backup_csv(ms.CSV_PATH) if csv_existed else None
        padded = [{k: (nr.get(k, "") or "") for k in fieldnames} for nr in new_rows]
        common.write_csv(ms.CSV_PATH, fieldnames, existing + padded)
    except Exception as e:
        cleanup_error = None
        try:
            if backup and os.path.exists(backup):
                os.remove(backup)
        except OSError as cleanup_exc:
            cleanup_error = str(cleanup_exc)
        shutil.rmtree(dest_dir, ignore_errors=True)
        result = {"ok": False, "step": "ingest", "error": f"CSV update failed: {e}"}
        if cleanup_error:
            result["cleanup_error"] = cleanup_error
        _result(result)
        return 1
    print(f"[ingest] appended {len(padded)} rows (backup {backup})")

    # 5. Register uploads in the data root, never in the repository template.
    # Write atomically. If registration fails, roll back the CSV and copied photo
    # directory so a failed first ingestion cannot leave a partial dataset.
    config_source_added = False
    if slug not in (cfg.get("sources") or {}):
        cfg_path = os.path.join(data_dir, "dashboard_config.json")
        tmp_cfg = f"{cfg_path}.tmp-{os.getpid()}"
        cfg_backup = None
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    live = json.load(f)
                cfg_backup = f"{cfg_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
                shutil.copy2(cfg_path, cfg_backup)
            else:
                live = cfg
            live.setdefault("sources", {})[slug] = {
                "label": slug, "color": "cyan", "owner": "upload",
                "source_type": "upload", "default_confidence": default_conf,
                "photo_dir": photo_dir, "desc": f"Uploaded dataset {slug}",
            }
            os.makedirs(data_dir, exist_ok=True)
            with open(tmp_cfg, "w", encoding="utf-8") as f:
                json.dump(live, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_cfg, cfg_path)
            config_source_added = True
            print(f"[ingest] registered sources[{slug}] in {cfg_path}")
        except Exception as e:
            cleanup_errors = []
            for path in (tmp_cfg, cfg_backup, backup):
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except OSError as cleanup_exc:
                    cleanup_errors.append(str(cleanup_exc))
            rollback_error = None
            try:
                if csv_existed:
                    common.write_csv(ms.CSV_PATH, fieldnames, existing)
                elif os.path.exists(ms.CSV_PATH):
                    os.remove(ms.CSV_PATH)
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
            shutil.rmtree(dest_dir, ignore_errors=True)
            result = {"ok": False, "step": "ingest",
                      "error": f"config source registration failed: {e}"}
            if rollback_error:
                result["rollback_error"] = rollback_error
            if cleanup_errors:
                result["cleanup_errors"] = cleanup_errors
            _result(result)
            return 1

    _result({"ok": True, "step": "ingest", "dataset": slug, "rows_added": len(padded),
             "photos_copied": photos_copied, "photos_missing": photos_missing,
             "photo_dir": photo_dir, "config_source_added": config_source_added,
             "backup": backup,
             "note": "Capture time and GPS are required at ingest; OCR, MapKit, and GT start empty — fill them with rerun jobs"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
