#!/usr/bin/env python3
"""Ingest a validated dataset ZIP into eval_set_reconciled.csv (append job).

Runs as a background job (tracked in the job panel). Given an upload package
(`dataset_slug/manifest.csv` + `photos/`), it: validates the package, copies
photos into the dataset's photo dir under POI_DATA_DIR, appends one CSV row per
manifest row (dataset=slug, photo=basename, input_place_name=gt_input_raw,
notes, gt_confidence=source default, plus optional capture_lat/capture_lon/
timestamp when the manifest supplies them), and registers the source in
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402
from validate_upload_package import validate_zip, ValidationError  # noqa: E402


# Stable store schema used when the first upload bootstraps a fresh data root.
CANONICAL_FIELDS = [
    "dataset", "photo", "capture_lat", "capture_lon", "timestamp",
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
    """Copy package photos and return reconciled-row fragments."""
    with zipfile.ZipFile(zip_path) as zf:
        names = set(n.replace("\\", "/").lstrip("/") for n in zf.namelist())
        manifest_text = zf.read(report["manifest_path"]).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(manifest_text)))
        n = len(rows)
        print(f"[ingest] slug={slug} manifest_rows={n} photo_dir={photo_dir}")
        _progress(0, n)
        new_rows = []
        photos_copied = photos_missing = 0
        for i, r in enumerate(rows, 1):
            photo_rel = (r.get("photo") or "").strip()
            src_name = f"{root}/{photo_rel}" if root else photo_rel
            base = PurePosixPath(photo_rel).name
            if photo_rel and src_name in names:
                with zf.open(src_name) as src, open(os.path.join(dest_dir, base), "wb") as out:
                    shutil.copyfileobj(src, out)
                photos_copied += 1
            else:
                photos_missing += 1
            new_rows.append({
                "dataset": slug, "photo": base,
                "input_place_name": (r.get("gt_input_raw") or "").strip(),
                "notes": (r.get("notes") or "").strip(),
                "gt_confidence": default_conf,
                "capture_lat": (r.get("lat") or r.get("capture_lat") or "").strip(),
                "capture_lon": (r.get("lon") or r.get("capture_lon") or "").strip(),
                "timestamp": (r.get("timestamp") or "").strip(),
            })
            if i % 5 == 0 or i == n:
                _progress(i, n)
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
                "photo_dir": photo_dir, "desc": f"업로드 데이터셋 {slug}",
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
             "note": "좌표(EXIF)·OCR·MapKit·GT는 비어 있음 — 재실행 잡으로 채우세요"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
