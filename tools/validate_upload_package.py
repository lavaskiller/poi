#!/usr/bin/env python3
"""Validate a POI dataset ZIP upload package.

The package contract is intentionally small:

    dataset_slug.zip
    └─ dataset_slug/
       ├─ manifest.csv
       ├─ README.md              # optional for user uploads
       └─ photos/
          ├─ IMG_0001.jpg
          └─ ...

User-authored manifest columns:
- photo: required, ZIP-root-relative path to an image, e.g. photos/IMG_0001.jpg
- gt_input_raw: required, user's selected GT raw value
- notes: optional

The validator is non-destructive: rows with missing EXIF/location or unparseable GT
should be flagged downstream rather than dropped here. This script focuses on the
upload package shape and manifest-to-image references.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic"}
REQUIRED_COLUMNS = {"photo", "gt_input_raw"}
# notes is a free-form memo; the capture_*/timestamp/lat/lon columns are an
# optional fallback the ingest tool reads when photos carry no EXIF GPS/date.
OPTIONAL_COLUMNS = {"notes", "capture_lat", "capture_lon", "timestamp", "lat", "lon"}


class ValidationError(Exception):
    pass


def _norm_zip_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


def _is_unsafe_path(path: str) -> bool:
    p = PurePosixPath(path)
    return path.startswith("/") or any(part in {"..", ""} for part in p.parts)


def _root_dirs(names: list[str]) -> set[str]:
    roots: set[str] = set()
    for name in names:
        normalized = _norm_zip_name(name)
        if not normalized or normalized.endswith("/"):
            continue
        parts = PurePosixPath(normalized).parts
        if parts:
            roots.add(parts[0])
    return roots


def _decode_manifest(raw: bytes) -> str:
    # utf-8-sig handles Excel/Numbers BOM without changing the documented format.
    return raw.decode("utf-8-sig")


def _looks_like_gt(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered in {"unknown", "n/a", "na", "none", "null", "-"}:
        return False
    return True


def validate_zip(zip_path: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    row_flags: list[dict[str, Any]] = []

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"not a valid ZIP file: {exc}") from exc

    with zf:
        raw_names = zf.namelist()
        file_names = [_norm_zip_name(n) for n in raw_names if not n.endswith("/") and not PurePosixPath(n).name.startswith("__MACOSX")]
        unsafe = [n for n in file_names if _is_unsafe_path(n)]
        if unsafe:
            errors.append({"code": "unsafe_path", "message": "ZIP contains unsafe paths", "paths": unsafe[:20]})

        roots = _root_dirs(file_names)
        if len(roots) != 1:
            errors.append({
                "code": "invalid_root_count",
                "message": "ZIP must contain exactly one dataset root directory",
                "roots": sorted(roots),
            })
            root = sorted(roots)[0] if roots else ""
        else:
            root = next(iter(roots))

        manifest_path = f"{root}/manifest.csv" if root else "manifest.csv"
        if manifest_path not in file_names:
            errors.append({"code": "manifest_missing", "message": "manifest.csv must be directly under the dataset root"})
            return _result(False, root, None, [], errors, warnings, row_flags)

        try:
            manifest_text = _decode_manifest(zf.read(manifest_path))
        except UnicodeDecodeError as exc:
            errors.append({"code": "manifest_encoding", "message": f"manifest.csv must be UTF-8: {exc}"})
            return _result(False, root, manifest_path, [], errors, warnings, row_flags)

        reader = csv.DictReader(io.StringIO(manifest_text))
        columns = reader.fieldnames or []
        missing_cols = sorted(REQUIRED_COLUMNS - set(columns))
        if missing_cols:
            errors.append({"code": "manifest_required_columns", "message": "manifest.csv is missing required columns", "columns": missing_cols})

        unknown_cols = sorted(set(columns) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS)
        if unknown_cols:
            warnings.append({
                "code": "manifest_unknown_columns",
                "message": "Unknown columns will be ignored by MVP ingest",
                "columns": unknown_cols,
            })

        rows = list(reader)
        if not rows:
            errors.append({"code": "manifest_empty", "message": "manifest.csv has no data rows"})

        photo_values = [(r.get("photo") or "").strip() for r in rows]
        duplicate_photos = sorted([p for p, count in Counter(photo_values).items() if p and count > 1])
        if duplicate_photos:
            errors.append({"code": "duplicate_photo", "message": "manifest.csv contains duplicate photo paths", "photos": duplicate_photos[:50]})

        zip_files = set(file_names)
        image_files = [n for n in file_names if PurePosixPath(n).suffix.lower() in ALLOWED_IMAGE_EXTS]

        for idx, row in enumerate(rows, start=2):
            flags: list[str] = []
            photo = (row.get("photo") or "").strip()
            gt_raw = (row.get("gt_input_raw") or "").strip()

            if not photo:
                errors.append({"code": "photo_empty", "message": "photo is required", "row": idx})
                continue
            if _is_unsafe_path(photo):
                errors.append({"code": "photo_unsafe_path", "message": "photo path is unsafe", "row": idx, "photo": photo})
                continue

            ext = PurePosixPath(photo).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                errors.append({"code": "photo_extension", "message": "photo extension is not allowed", "row": idx, "photo": photo, "allowed": sorted(ALLOWED_IMAGE_EXTS)})

            full_photo = f"{root}/{photo}" if root else photo
            if full_photo not in zip_files:
                errors.append({"code": "photo_missing", "message": "photo path does not exist in ZIP", "row": idx, "photo": photo})

            if not _looks_like_gt(gt_raw):
                flags.append("needs_gt_review")

            # EXIF GPS extraction is an ingest step. The validator records that the row
            # still requires location extraction/review, without failing the upload.
            flags.append("pending_exif_location_extract")

            if flags:
                row_flags.append({"row": idx, "photo": photo, "flags": flags})

        unused_images = sorted(set(image_files) - {f"{root}/{p}" for p in photo_values if p})
        if unused_images:
            warnings.append({
                "code": "unused_images",
                "message": "ZIP contains image files not referenced by manifest.csv",
                "count": len(unused_images),
                "paths": unused_images[:50],
            })

        return _result(not errors, root, manifest_path, rows, errors, warnings, row_flags, image_count=len(image_files))


def _result(ok: bool, root: str | None, manifest_path: str | None, rows: list[dict[str, Any]], errors, warnings, row_flags, image_count: int | None = None) -> dict[str, Any]:
    return {
        "ok": ok,
        "dataset_root": root,
        "manifest_path": manifest_path,
        "row_count": len(rows),
        "image_count": image_count,
        "errors": errors,
        "warnings": warnings,
        "row_flags": row_flags,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a POI dataset upload ZIP package")
    parser.add_argument("zip_path", help="Path to dataset ZIP package")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        result = validate_zip(args.zip_path)
    except ValidationError as exc:
        result = {"ok": False, "errors": [{"code": "invalid_zip", "message": str(exc)}], "warnings": [], "row_flags": []}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("OK" if result.get("ok") else "FAILED")
        for err in result.get("errors", []):
            print(f"ERROR {err.get('code')}: {err.get('message')}")
        for warn in result.get("warnings", []):
            print(f"WARN  {warn.get('code')}: {warn.get('message')}")
        print(f"rows={result.get('row_count', 0)} images={result.get('image_count')}")

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
