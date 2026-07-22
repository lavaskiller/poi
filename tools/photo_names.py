#!/usr/bin/env python3
"""Local photo identity for the POI eval store.

Design
------
Upstream names (LinkedSpaces exports, phone UUIDs, camera roll) are *inputs*.
Once a photo is copied into the local data root, the eval store assigns a
**uniform, local** identity:

    {dataset}_{YYYYMMDD}_{sha256(bytes)[:12]}{ext}

    e.g.  linkedspaces_20260419_a3f91c2b8e4d.jpg
          union-city_20250701_7c0e1a92b4f3.jpg

Why this shape
~~~~~~~~~~~~~~
* **dataset_**  — which bundle owns the file (readable in a flat folder / logs)
* **YYYYMMDD_** — capture day (required: manifest timestamp or EXIF; never empty)
* **hash12**    — content address: same bytes ⇒ same id, natural dedup
* **ext**       — normalized (``.jpeg`` → ``.jpg``)

Capture time is mandatory. Ingest fills ``timestamp`` from EXIF when the
manifest omits it; packages with neither source are rejected.

GPS coordinates are mandatory the same way: manifest ``capture_lat`` /
``capture_lon`` (or ``lat`` / ``lon``) or EXIF GPS on the image. Packages
with neither source are rejected.

Not used as the key: raw export prefixes, camera ``IMG_*`` alone, or sequential
``0001.jpg`` (order-dependent, re-ingest unstable).

Provenance
~~~~~~~~~~
``photo_original`` may store a sanitized upload basename for humans. Scoring
and artifacts must join on ``photo`` (the local id above).

Legacy lookup
~~~~~~~~~~~~~
Historical CSV rows still use long LinkedSpaces / UUID / ``IMG_*`` names. Alias
helpers keep the photo API working until an explicit migration.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import BinaryIO, Iterable, List, Optional, Set, Tuple

# Historical export wrappers — provenance + legacy lookup only.
_LINKEDSPACES_EXPORT = re.compile(
    r"^(?P<user>[0-9a-f]{24})_(?P<ts>\d{10,13})_(?P<original>.+)$",
    re.I,
)
_EPOCH_PREFIX = re.compile(r"^(?P<ts>\d{10,13})_(?P<original>.+)$")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DATASET_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".heic"}
_CONTENT_ID_LEN = 12
# linkedspaces_20260419_a3f91c2b8e4d.jpg  (day is always YYYYMMDD — never nodate)
_LOCAL_ID = re.compile(
    r"^(?P<dataset>[A-Za-z0-9][A-Za-z0-9._-]*)_"
    r"(?P<day>\d{8})_"
    r"(?P<hash>[0-9a-f]{" + str(_CONTENT_ID_LEN) + r"})"
    r"(?P<ext>\.[a-z0-9]+)$"
)
# Older experiments still recognized as “local-ish”.
_LOCAL_SEQ = re.compile(r"^(\d{4,})(\.[A-Za-z0-9]+)$")
_LOCAL_HASH_ONLY = re.compile(r"^([0-9a-f]{12})(\.[a-z0-9]+)$")


def _basename(value: str) -> str:
    return PurePosixPath((value or "").replace("\\", "/")).name


def normalize_extension(original: str) -> str:
    """Safe lowercase image extension (``.jpeg`` → ``.jpg``)."""
    _, ext = os.path.splitext(_basename(original) or "photo.jpg")
    ext = (ext or ".jpg").lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in _ALLOWED_EXT:
        ext = ".jpg"
    return ext


def safe_dataset_slug(dataset: str) -> str:
    slug = (dataset or "").strip() or "dataset"
    slug = _SAFE.sub("-", slug).strip(".-") or "dataset"
    if not _DATASET_SLUG.match(slug):
        slug = "dataset"
    return slug


def strip_export_prefix(original: str) -> str:
    """Peel LinkedSpaces / epoch wrappers → inner basename (provenance only)."""
    name = _basename(original) or "photo.jpg"
    m = _LINKEDSPACES_EXPORT.match(name)
    if m:
        return m.group("original")
    m = _EPOCH_PREFIX.match(name)
    if m:
        return m.group("original")
    return name


def provenance_basename(original: str) -> str:
    """Sanitized original name for ``photo_original`` — never the eval key."""
    name = strip_export_prefix(original)
    stem, _ext = os.path.splitext(name)
    stem = _SAFE.sub("-", stem).strip(".-") or "photo"
    return f"{stem}{normalize_extension(name)}"


# ---------------------------------------------------------------------------
# Capture time (required — never optional in the local store)
# ---------------------------------------------------------------------------

class CaptureTimeRequired(ValueError):
    """Raised when neither manifest timestamp nor EXIF provides a capture time."""


def _parse_datetime(value: str) -> Optional[datetime]:
    s = (value or "").strip()
    if not s:
        return None
    # ISO-ish: 2026-06-26T22:02:19Z / 2026-06-26 22:02:19
    s2 = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s2)
    except ValueError:
        pass
    for fmt in (
        "%Y:%m:%d %H:%M:%S",      # EXIF
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # epoch seconds / ms
    if re.fullmatch(r"\d{10,13}", s):
        n = int(s)
        if n > 10_000_000_000:  # ms
            n //= 1000
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def format_capture_timestamp(dt: datetime) -> str:
    """Store form matching existing eval CSV: ``YYYY-MM-DDTHH:MM:SSZ``."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_datetime_from_exif_bytes(data: bytes) -> Optional[datetime]:
    """Best-effort EXIF capture datetime from image bytes."""
    if not data:
        return None
    try:
        from io import BytesIO
        from PIL import Image, ExifTags
    except ImportError:
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            ex = im.getexif() or {}
            tags = {}
            for k, v in ex.items():
                tags[ExifTags.TAGS.get(k, k)] = v
            try:
                exif_ifd = ex.get_ifd(0x8769)  # ExifOffset
                for k, v in (exif_ifd or {}).items():
                    tags.setdefault(ExifTags.TAGS.get(k, k), v)
            except Exception:
                pass
            for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                raw = tags.get(key)
                if not raw:
                    continue
                dt = _parse_datetime(str(raw))
                if dt:
                    return dt
    except Exception:
        return None
    return None


def capture_day_from_exif_bytes(data: bytes) -> Optional[str]:
    """EXIF day ``YYYYMMDD``, or None."""
    dt = capture_datetime_from_exif_bytes(data)
    return dt.strftime("%Y%m%d") if dt else None


def resolve_capture_timestamp(
    timestamp: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
) -> Tuple[str, str]:
    """Resolve a required capture time.

    Priority: explicit timestamp (manifest / CSV) → EXIF from image bytes.

    Returns
    -------
    (iso_z, yyyymmdd)
        ``iso_z`` is written into the CSV ``timestamp`` column.
        ``yyyymmdd`` is used in the local photo filename.

    Raises
    ------
    CaptureTimeRequired
        If neither source yields a parseable capture time. Callers must not
        invent ``nodate`` or leave timestamp empty.
    """
    dt = _parse_datetime(timestamp or "")
    if dt is None and image_bytes:
        dt = capture_datetime_from_exif_bytes(image_bytes)
    if dt is None:
        raise CaptureTimeRequired(
            "capture time is required: set manifest timestamp or use a photo "
            "with EXIF DateTimeOriginal/DateTime"
        )
    return format_capture_timestamp(dt), dt.strftime("%Y%m%d")


def capture_day_token(
    timestamp: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    *,
    require: bool = True,
) -> str:
    """Return ``YYYYMMDD``. When ``require`` (default), never returns ``nodate``."""
    if require:
        return resolve_capture_timestamp(timestamp, image_bytes)[1]
    try:
        return resolve_capture_timestamp(timestamp, image_bytes)[1]
    except CaptureTimeRequired:
        return "nodate"


# ---------------------------------------------------------------------------
# Capture GPS (required — never optional in the local store)
# ---------------------------------------------------------------------------

class CaptureGpsRequired(ValueError):
    """Raised when neither manifest lat/lon nor EXIF provides capture GPS."""


def _parse_coord(value: Optional[str]) -> Optional[float]:
    s = (value or "").strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    return f


def _rational_to_float(value) -> Optional[float]:
    """EXIF rationals: int/float, (num, den), or DMS sequence of those."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, tuple) and len(value) == 2 and not isinstance(value[0], (tuple, list)):
        try:
            num, den = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
        if den == 0 or not math.isfinite(num) or not math.isfinite(den):
            return None
        return num / den
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        d = _rational_to_float(value[0])
        m = _rational_to_float(value[1])
        s = _rational_to_float(value[2])
        if d is None or m is None or s is None:
            return None
        return d + m / 60.0 + s / 3600.0
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _apply_hemisphere(value: float, ref: Optional[str]) -> float:
    r = (ref or "").strip().upper()
    if r in {"S", "W"}:
        return -abs(value)
    if r in {"N", "E"}:
        return abs(value)
    return value


def format_capture_coord(value: float) -> str:
    """Store form matching EXIF/Swift workers: up to 8 decimal places."""
    s = f"{value:.8f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def capture_gps_from_exif_bytes(data: bytes) -> Optional[Tuple[str, str]]:
    """Best-effort EXIF GPS (lat, lon) strings from image bytes."""
    if not data:
        return None
    try:
        from io import BytesIO
        from PIL import Image, ExifTags
    except ImportError:
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            ex = im.getexif() or {}
            gps = {}
            try:
                raw_gps = ex.get_ifd(0x8825)  # GPSInfo
                if raw_gps:
                    for k, v in raw_gps.items():
                        name = ExifTags.GPSTAGS.get(k, k)
                        gps[name] = v
            except Exception:
                pass
            if not gps:
                return None
            lat_raw = gps.get("GPSLatitude")
            lon_raw = gps.get("GPSLongitude")
            lat = _rational_to_float(lat_raw)
            lon = _rational_to_float(lon_raw)
            if lat is None or lon is None:
                return None
            lat = _apply_hemisphere(lat, gps.get("GPSLatitudeRef"))
            lon = _apply_hemisphere(lon, gps.get("GPSLongitudeRef"))
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                return None
            if lat == 0.0 and lon == 0.0:
                # (0,0) is almost never a real capture; treat as missing.
                return None
            return format_capture_coord(lat), format_capture_coord(lon)
    except Exception:
        return None


def resolve_capture_gps(
    lat: Optional[str] = None,
    lon: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
) -> Tuple[str, str]:
    """Resolve required capture GPS coordinates.

    Priority: explicit lat/lon (manifest / CSV) → EXIF from image bytes.

    Returns
    -------
    (lat_str, lon_str)
        Written into the CSV ``capture_lat`` / ``capture_lon`` columns.

    Raises
    ------
    CaptureGpsRequired
        If neither source yields a valid coordinate pair.
    """
    lat_f = _parse_coord(lat)
    lon_f = _parse_coord(lon)
    if lat_f is not None and lon_f is not None:
        if -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0:
            return format_capture_coord(lat_f), format_capture_coord(lon_f)
        raise CaptureGpsRequired(
            "capture GPS is invalid: latitude must be in [-90, 90] and "
            "longitude in [-180, 180]"
        )
    # Partial manifest coords are not accepted — need both or fall through to EXIF.
    if (lat_f is None) != (lon_f is None):
        # One side only in manifest: still try EXIF before failing.
        pass

    if image_bytes:
        pair = capture_gps_from_exif_bytes(image_bytes)
        if pair:
            return pair

    raise CaptureGpsRequired(
        "capture GPS is required: set manifest capture_lat/capture_lon "
        "(or lat/lon) or use a photo with EXIF GPS"
    )


# ---------------------------------------------------------------------------
# Content id + local store basename
# ---------------------------------------------------------------------------

def content_id_from_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()[:_CONTENT_ID_LEN]


def content_id_from_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:_CONTENT_ID_LEN]


def local_store_basename(
    dataset: str,
    content_id: str,
    *,
    day: str,
    source_original: str = "",
) -> str:
    """``{dataset}_{YYYYMMDD}_{hash12}{ext}`` — day must be a real ``YYYYMMDD``."""
    ds = safe_dataset_slug(dataset)
    cid = (content_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{" + str(_CONTENT_ID_LEN) + r"}", cid):
        raise ValueError(f"invalid content id: {content_id!r}")
    day_tok = (day or "").strip()
    if not re.fullmatch(r"\d{8}", day_tok):
        raise CaptureTimeRequired(
            f"local photo id requires YYYYMMDD capture day, got {day!r}"
        )
    return f"{ds}_{day_tok}_{cid}{normalize_extension(source_original)}"


def local_store_basename_for_bytes(
    dataset: str,
    data: bytes,
    *,
    source_original: str = "",
    timestamp: Optional[str] = None,
) -> str:
    _iso, day = resolve_capture_timestamp(timestamp, data)
    return local_store_basename(
        dataset,
        content_id_from_bytes(data),
        day=day,
        source_original=source_original,
    )


def is_local_store_basename(name: str) -> bool:
    """True for current composite ids and older local experiments."""
    base = _basename(name) or ""
    if _LOCAL_ID.match(base):
        return True
    if _LOCAL_HASH_ONLY.match(base):
        return True
    return bool(_LOCAL_SEQ.match(base))


def is_canonical_photo_basename(name: str) -> bool:
    return bool(_LOCAL_ID.match(_basename(name) or ""))


# ---------------------------------------------------------------------------
# Batch allocation (ingest)
# ---------------------------------------------------------------------------

def allocate_local_photo_basenames(
    sources: Iterable[Tuple[str, bytes, str, Optional[str]]],
    *,
    used: Optional[Set[str]] = None,
) -> List[Tuple[str, str, str, str]]:
    """Assign local names for ``(source_basename, bytes, dataset, timestamp)``.

    Returns
    -------
    list of ``(source_basename, local_basename, photo_original, timestamp_iso)``

    ``timestamp_iso`` is always set (manifest or EXIF). Raises
    :class:`CaptureTimeRequired` if any row cannot resolve a capture time.

    Identical content within the same dataset+day reuses the same local name.
    """
    used = used if used is not None else set()
    by_key: dict = {}
    out: List[Tuple[str, str, str, str]] = []
    for item in sources:
        if len(item) == 2:
            raw, data = item  # type: ignore[misc]
            dataset, timestamp = "dataset", None
        elif len(item) == 3:
            raw, data, dataset = item  # type: ignore[misc]
            timestamp = None
        else:
            raw, data, dataset, timestamp = item  # type: ignore[misc]
        source = _basename(raw) or "photo.jpg"
        data = data or b""
        ds = safe_dataset_slug(dataset)
        iso, day = resolve_capture_timestamp(timestamp, data if data else None)
        cid = content_id_from_bytes(data if data else source.encode("utf-8"))
        key = (ds, day, cid)
        if key in by_key:
            local = by_key[key]
        else:
            local = local_store_basename(ds, cid, day=day, source_original=source)
            by_key[key] = local
            used.add(local)
        out.append((source, local, provenance_basename(source), iso))
    return out


# ---------------------------------------------------------------------------
# Legacy helpers (lookup / old call sites)
# ---------------------------------------------------------------------------

def preferred_photo_basename(original: str) -> str:
    return provenance_basename(original)


def allocate_photo_basename(original: str, used: Set[str]) -> str:
    """Deprecated provenance short-name with hash disambiguation (no bytes)."""
    source = _basename(original) or "photo.jpg"
    preferred = provenance_basename(source)
    if preferred not in used:
        used.add(preferred)
        return preferred
    tag = hashlib.sha1(source.encode("utf-8")).hexdigest()[:6]
    stem, ext = os.path.splitext(preferred)
    candidate = f"{stem}__{tag}{ext}"
    n = 2
    while candidate in used:
        candidate = f"{stem}__{tag}{n}{ext}"
        n += 1
    used.add(candidate)
    return candidate


def normalize_photo_basename(original: str, used: Optional[Set[str]] = None) -> str:
    if used is None:
        return provenance_basename(original)
    return allocate_photo_basename(original, used)


def photo_name_aliases(original: str) -> List[str]:
    """Lookup candidates for resolving photos on disk (legacy + local)."""
    raw = _basename(original)
    if not raw:
        return []
    out: List[str] = []
    for name in (raw, provenance_basename(raw), strip_export_prefix(raw)):
        n = _basename(name)
        if n and n not in out:
            out.append(n)
    stem, ext = os.path.splitext(provenance_basename(raw))
    if ext.lower() in {".jpg", ".jpeg"}:
        for e in (".jpg", ".jpeg", ".JPG", ".JPEG"):
            alt = stem + e
            if alt not in out:
                out.append(alt)
    return out


def next_local_index(existing_names: Iterable[str]) -> int:
    high = 0
    for name in existing_names:
        m = _LOCAL_SEQ.match(_basename(name) or "")
        if m:
            high = max(high, int(m.group(1)))
    return high + 1
