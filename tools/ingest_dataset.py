#!/usr/bin/env python3
"""Ingest a validated dataset ZIP into eval_set_reconciled.csv (append job).

Runs as a background job (tracked in the job panel). Given an upload package
(`dataset_slug/manifest.csv` + `photos/`), it: validates the package, copies
photos into the dataset's photo dir under POI_DATA_DIR, appends one CSV row per
manifest row (dataset=slug, photo=basename, input_place_name=gt_input_raw,
notes, gt_confidence=source default), and registers the source in
dashboard_config.json if new. Auto-extractable signals (coords via EXIF, OCR,
geocode, MapKit, GT) start empty — fill them afterward with the re-run jobs
(EXIF/geocode are 미구현; see PROGRESS/RESULT + row flags).

Usage:
  POI_DATA_DIR=/path python3 tools/ingest_dataset.py --zip /path/to/pkg.zip [--dataset slug]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile
from pathlib import PurePosixPath

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402
from validate_upload_package import validate_zip, ValidationError  # noqa: E402


def _progress(done, total):
    print("PROGRESS " + json.dumps({"done": done, "total": total}), flush=True)


def _result(obj):
    print("RESULT " + json.dumps(obj, ensure_ascii=False), flush=True)


def _photo_dir_for(cfg, slug):
    src = (cfg.get("sources") or {}).get(slug) or {}
    return src.get("photo_dir") or f"{slug}-photos"


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

    cfg = ms.load_config()
    data_dir = os.path.dirname(os.path.abspath(ms.CSV_PATH))
    photo_dir = _photo_dir_for(cfg, slug)
    dest_dir = os.path.join(data_dir, photo_dir)
    os.makedirs(dest_dir, exist_ok=True)

    # 2. read manifest rows from the ZIP.
    with zipfile.ZipFile(args.zip) as zf:
        names = set(n.replace("\\", "/").lstrip("/") for n in zf.namelist())
        manifest_text = zf.read(report["manifest_path"]).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(manifest_text)))
        n = len(rows)
        print(f"[ingest] slug={slug} manifest_rows={n} photo_dir={photo_dir}")
        _progress(0, n)

        # 3. copy photos + build new CSV rows.
        new_rows = []
        photos_copied = photos_missing = 0
        default_conf = ((cfg.get("sources") or {}).get(slug) or {}).get("default_confidence", "confirmed_user")
        for i, r in enumerate(rows, 1):
            photo_rel = (r.get("photo") or "").strip()
            src_name = f"{root}/{photo_rel}" if root else photo_rel
            base = PurePosixPath(photo_rel).name
            if photo_rel and src_name in names:
                with zf.open(src_name) as src, open(os.path.join(dest_dir, base), "wb") as out:
                    out.write(src.read())
                photos_copied += 1
            else:
                photos_missing += 1
            new_rows.append({
                "dataset": slug,
                "photo": base,
                "input_place_name": (r.get("gt_input_raw") or "").strip(),
                "notes": (r.get("notes") or "").strip(),
                "gt_confidence": default_conf,
                # optional coords if the manifest carried them (else EXIF/Phase 3)
                "capture_lat": (r.get("lat") or r.get("capture_lat") or "").strip(),
                "capture_lon": (r.get("lon") or r.get("capture_lon") or "").strip(),
            })
            if i % 5 == 0 or i == n:
                _progress(i, n)

    # 4. append to the CSV (backup first, atomic write). New rows carry only the
    #    known columns; every other field defaults to "" via DictWriter.
    fieldnames, existing = common.read_csv(ms.CSV_PATH)
    if slug in {(x.get("dataset") or "").strip() for x in existing}:
        _result({"ok": False, "step": "ingest", "error": f"dataset {slug!r} already exists"})
        return 1
    backup = common.backup_csv(ms.CSV_PATH)
    padded = [{k: (nr.get(k, "") or "") for k in fieldnames} for nr in new_rows]
    common.write_csv(ms.CSV_PATH, fieldnames, existing + padded)
    print(f"[ingest] appended {len(padded)} rows (backup {backup})")

    # 5. register the source in the live config if new.
    config_source_added = False
    if slug not in (cfg.get("sources") or {}):
        try:
            cfg_path = ms.CONFIG_PATH
            with open(cfg_path, encoding="utf-8") as f:
                live = json.load(f)
            live.setdefault("sources", {})[slug] = {
                "label": slug, "color": "cyan", "owner": "upload",
                "source_type": "upload", "default_confidence": default_conf,
                "photo_dir": photo_dir, "desc": f"업로드 데이터셋 {slug}",
            }
            bak = f"{cfg_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            with open(cfg_path, encoding="utf-8") as f:
                open(bak, "w", encoding="utf-8").write(f.read())
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(live, f, ensure_ascii=False, indent=2)
            config_source_added = True
            print(f"[ingest] registered sources[{slug}] in {cfg_path}")
        except Exception as e:
            print(f"[ingest] config source registration failed: {e}")

    _result({"ok": True, "step": "ingest", "dataset": slug, "rows_added": len(padded),
             "photos_copied": photos_copied, "photos_missing": photos_missing,
             "photo_dir": photo_dir, "config_source_added": config_source_added,
             "backup": backup,
             "note": "좌표(EXIF)·OCR·MapKit·GT는 비어 있음 — 재실행 잡으로 채우세요"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
