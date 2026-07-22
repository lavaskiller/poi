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

Capture time and GPS are required end-to-end (manifest columns and/or EXIF on
the image). Unparseable GT is flagged for review rather than rejected here.
This script focuses on the upload package shape, required signals, and
manifest-to-image references.
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
# notes is free-form. Capture time and GPS are required end-to-end via either
# manifest columns or EXIF on the image (validator checks both). Column names
# remain optional so EXIF-only packages still validate.
OPTIONAL_COLUMNS = {"notes", "capture_lat", "capture_lon", "timestamp", "lat", "lon", "capture_time"}


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

        # Capture-time / GPS resolution (shared with ingest / local photo ids).
        try:
            from photo_names import (
                CaptureGpsRequired,
                CaptureTimeRequired,
                resolve_capture_gps,
                resolve_capture_timestamp,
            )
        except ImportError:
            import sys as _sys
            from pathlib import Path as _Path
            _sys.path.insert(0, str(_Path(__file__).resolve().parent))
            from photo_names import (
                CaptureGpsRequired,
                CaptureTimeRequired,
                resolve_capture_gps,
                resolve_capture_timestamp,
            )

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

            # Capture time required: manifest timestamp OR EXIF on the image.
            ts = (row.get("timestamp") or row.get("capture_time") or "").strip()
            image_bytes = None
            if full_photo in zip_files:
                try:
                    image_bytes = zf.read(full_photo)
                except Exception:
                    image_bytes = None
            try:
                resolve_capture_timestamp(ts or None, image_bytes)
                if not ts and image_bytes:
                    flags.append("timestamp_will_fill_from_exif")
            except CaptureTimeRequired:
                errors.append({
                    "code": "timestamp_required",
                    "message": (
                        "capture time is required: set manifest timestamp "
                        "(ISO-8601) or use a photo with EXIF DateTimeOriginal/DateTime"
                    ),
                    "row": idx,
                    "photo": photo,
                })

            # GPS required: manifest lat/lon OR EXIF GPS on the image.
            lat = (row.get("capture_lat") or row.get("lat") or "").strip()
            lon = (row.get("capture_lon") or row.get("lon") or "").strip()
            try:
                resolve_capture_gps(lat or None, lon or None, image_bytes)
                if not (lat and lon) and image_bytes:
                    flags.append("gps_will_fill_from_exif")
            except CaptureGpsRequired:
                errors.append({
                    "code": "gps_required",
                    "message": (
                        "capture GPS is required: set manifest capture_lat/capture_lon "
                        "(or lat/lon) or use a photo with EXIF GPS"
                    ),
                    "row": idx,
                    "photo": photo,
                })

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


# Minimal 1×1 pixel JPEG (valid JFIF) used as a placeholder photo in the
# downloadable upload-package template. Not a real capture — replace with
# your own images before ingesting for evaluation.
_MINIMAL_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
    0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
    0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
    0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
    0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
    0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
    0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
    0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
    0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
    0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
    0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
    0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
    0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
    0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
    0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
    0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
    0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
    0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
    0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
    0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xA8, 0xF1, 0x45, 0x00,
    0xFF, 0xD9,
])

TEMPLATE_README = """# POI dataset upload package

This ZIP is the **upload template** for the POI Eval dashboard
(`Datasets → Add dataset` / drop zone).

## Layout (required)

```
my-dataset/                 # root folder name becomes the dataset slug
  manifest.csv              # one row per case
  README.md                 # optional
  photos/
    example_001.jpg
    example_002.jpg
```

Rename the root folder to your dataset slug (letters, digits, `-`, `_`).

## manifest.csv columns

| column | required | meaning |
|--------|----------|---------|
| `photo` | yes | path relative to the dataset root, e.g. `photos/IMG_0001.jpg` |
| `gt_input_raw` | yes | ground-truth place name as the user selected it |
| `timestamp` | yes* | capture time (ISO-8601). *May be omitted only if the photo has EXIF DateTime; ingest will fill it. Rows with neither are rejected. |
| `capture_lat` / `capture_lon` (or `lat` / `lon`) | yes* | capture GPS. *May be omitted only if the photo has EXIF GPS; ingest will fill it. Rows with neither are rejected. |
| `notes` | no | free-form memo |

## Image rules

- Extensions: `.jpg` `.jpeg` `.png` `.heic`
- Every `photo` path must exist inside the ZIP
- **Capture time is required** (manifest `timestamp` and/or EXIF). No undated rows.
- **GPS is required** (manifest lat/lon and/or EXIF GPS). No locationless rows.
- Placeholders in this template include `timestamp` and coordinates so validation passes — replace with real photos

## Workflow

1. Fill `manifest.csv` and drop real images under `photos/`
2. Zip the **root folder** (not loose files): `zip -r my-dataset.zip my-dataset`
3. In the dashboard: **Datasets → drop ZIP** (validated before write)
4. Run enrichment (EXIF / OCR / MapKit / GT) as needed, then **New run**

## Notes

- Ingest appends rows into the reconciled eval CSV and copies photos into the data root
- Korean / non-MapKit rows may be holdouts for headline metrics until provider data exists
"""

TEMPLATE_MANIFEST = """photo,gt_input_raw,notes,capture_lat,capture_lon,timestamp
photos/example_001.jpg,Example Café,replace with a real place name,37.5665,126.9780,2026-07-01T12:00:00
photos/example_002.jpg,Example Park,second sample row,37.5796,126.9770,2026-07-01T13:30:00
"""


def build_dataset_template_zip(root_name: str = "my-dataset") -> bytes:
    """Return bytes for a minimal, validator-passing upload package ZIP."""
    import io as _io

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (root_name or "my-dataset").strip()).strip("-") or "my-dataset"
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}/README.md", TEMPLATE_README)
        zf.writestr(f"{slug}/manifest.csv", TEMPLATE_MANIFEST)
        zf.writestr(f"{slug}/photos/example_001.jpg", _MINIMAL_JPEG)
        zf.writestr(f"{slug}/photos/example_002.jpg", _MINIMAL_JPEG)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a POI dataset upload ZIP package")
    parser.add_argument("zip_path", nargs="?", help="Path to dataset ZIP package")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--write-template",
        metavar="PATH",
        help="Write a sample upload-package ZIP to PATH and exit",
    )
    args = parser.parse_args(argv)

    if args.write_template:
        path = args.write_template
        data = build_dataset_template_zip()
        with open(path, "wb") as f:
            f.write(data)
        result = validate_zip(path)
        print(f"wrote {path} ({len(data)} bytes) validate={'OK' if result.get('ok') else 'FAILED'}")
        if not result.get("ok"):
            for err in result.get("errors", []):
                print(f"ERROR {err.get('code')}: {err.get('message')}")
            return 1
        return 0

    if not args.zip_path:
        parser.error("zip_path is required unless --write-template is set")

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
