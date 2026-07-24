#!/usr/bin/env python3
"""Provider-aware POI candidate-retrieval metrics for the MVP dashboard.

MVP policy:
- South Korea rows are currently held out until Kakao Local canonical/candidate
  data is populated.
- Non-Korea candidate retrieval is evaluated against MapKit candidates.
- The primary matching rule is exact string equality between the provider
  canonical name and provider candidate name.
- provider_place_id is kept when present, but is nullable and never required.

Important: this module measures whether the provider candidate list contains the
human GT place and at what rank. It is not a visual/user-intent identification
accuracy evaluator; selection accuracy requires submitted algorithm predictions.

This module intentionally uses only the Python standard library so it runs in
this workspace without pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Match server.py's data-root selection so direct tool invocations and the web
# UI operate on the same local store. Keep the repository-root fallback only
# for legacy checkouts that still colocate code and data.
_REPO_DATA_DIR = os.path.join(ROOT, "poi-data")


def resolve_data_root() -> str:
    """Resolve the active dataset root (same order as server._resolve_data_dir).

    Re-evaluated on demand so a process that starts before ``poi-data/`` is
    seeded still finds label relations / overrides after the seed lands.
    """
    env = os.environ.get("POI_DATA_DIR")
    if env:
        return env
    if os.path.isfile(os.path.join(_REPO_DATA_DIR, "eval_set_reconciled.csv")):
        return _REPO_DATA_DIR
    if os.path.isfile(os.path.join(ROOT, "eval_set_reconciled.csv")):
        return ROOT  # legacy repository-root layout
    return _REPO_DATA_DIR  # fresh install: seed target is poi-data/, not ROOT


DATA_ROOT = resolve_data_root()
CSV_PATH = os.path.join(DATA_ROOT, "eval_set_reconciled.csv")
_data_cfg = os.path.join(DATA_ROOT, "dashboard_config.json")
CONFIG_PATH = _data_cfg if os.path.exists(_data_cfg) else os.path.join(ROOT, "dashboard_config.json")
CANDIDATE_DIR = os.path.join(DATA_ROOT, "generated")
ACTIVE_MAPKIT_SNAPSHOT_POINTER = "active-mapkit-candidate-snapshot.json"
# Manual GT↔MapKit matches from the Reconcile UI. Applied at read time so
# matchrate / algorithm runs see reconciled names without rewriting the CSV.
GT_MAPKIT_OVERRIDES_PATH = os.path.join(DATA_ROOT, "gt_mapkit_overrides.tsv")


def default_label_relations_path(data_root: Optional[str] = None) -> str:
    """Path to the reviewed alias/relation sidecar under the active data root.

    Resolved at call time (not only at import) so a server that started before
    the dataset was present still picks up ``eval_label_relations.v1.jsonl``
    after seed upload without a restart.
    """
    root = data_root or resolve_data_root()
    return os.path.join(root, "eval_label_relations.v1.jsonl")


# Compatibility for CLI defaults / external importers. Prefer
# ``default_label_relations_path()`` at run time.
DEFAULT_LABEL_RELATIONS_PATH = default_label_relations_path()


def active_mapkit_candidate_file(data_root: Optional[str] = None) -> str:
    """Return the explicitly selected immutable MapKit candidate artifact.

    Without a selection pointer, retain the legacy artifact for compatibility.
    Once a pointer exists, it is authoritative: an incomplete or tampered
    snapshot is an evaluation configuration error, not a fallback opportunity.
    """
    root = data_root or resolve_data_root()
    generated = os.path.join(root, "generated")
    pointer_path = os.path.join(generated, ACTIVE_MAPKIT_SNAPSHOT_POINTER)
    legacy = os.path.join(generated, "mapkit_candidates.jsonl")
    if not os.path.exists(pointer_path):
        return legacy
    try:
        with open(pointer_path, encoding="utf-8") as f:
            pointer = json.load(f)
        snapshot_id = pointer["snapshot_id"]
        artifact_name = pointer["candidate_artifact"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"invalid active MapKit snapshot pointer {pointer_path}: {e}") from e
    if (not isinstance(snapshot_id, str) or not snapshot_id.replace("-", "").replace("_", "").isalnum()
            or artifact_name != "mapkit_candidates.jsonl"):
        raise RuntimeError(f"invalid active MapKit snapshot pointer {pointer_path}")
    snapshot_dir = os.path.join(generated, "candidate-snapshots", snapshot_id)
    metadata_path = os.path.join(snapshot_dir, "metadata.json")
    artifact_path = os.path.join(snapshot_dir, artifact_name)
    try:
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
        if (metadata.get("snapshot_id") != snapshot_id
                or metadata.get("status") != "complete"
                or metadata.get("candidate_artifact") != artifact_name):
            raise ValueError("metadata is not a complete matching MapKit snapshot")
        expected_sha256 = metadata.get("candidate_artifact_sha256")
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ValueError("metadata lacks candidate artifact SHA-256")
        import hashlib
        digest = hashlib.sha256()
        with open(artifact_path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("candidate artifact SHA-256 mismatch")
    except (OSError, ValueError, TypeError) as e:
        raise RuntimeError(f"active MapKit snapshot is unusable: {e}") from e
    return artifact_path


def default_candidate_files(data_root: Optional[str] = None) -> List[str]:
    """Resolve candidate artifacts from the current active-snapshot pointer.

    Snapshot selection can happen while the dashboard is alive. Resolving only
    at module import would leave that process pinned to the previously active
    artifact until it is restarted.
    """
    root = data_root or resolve_data_root()
    return [
        active_mapkit_candidate_file(root),
        os.path.join(root, "generated", "kakao_local_candidates.jsonl"),
    ]


# Compatibility for external importers. Repository execution paths use the
# function above so an active-snapshot change is observed at run time.
DEFAULT_CANDIDATE_FILES = default_candidate_files()

KR_NAMES = {"South Korea", "Korea", "Republic of Korea", "대한민국", "한국", "KR", "KOR"}

# Provider tokens. ``unresolved`` means country/region cannot be determined —
# never silently treat that as MapKit (that mis-routes Korean rows to MapKit GT).
PROVIDER_MAPKIT = "mapkit"
PROVIDER_KAKAO = "kakao_local"
PROVIDER_UNRESOLVED = "unresolved"

# GT MapKit labels against the *nearby* candidate set, not a separate name search.
# Radius matches the wide MapKit nearby probe (ls_mapkit_probe DEFAULT_WIDE_RADIUS).
MAPKIT_NEARBY_WIDE_RADIUS_M = 250.0
MAPKIT_GT_RADIUS_M = MAPKIT_NEARBY_WIDE_RADIUS_M

# Approximate South Korea service area for GPS fallback when reverse-geocode
# has not filled ``country`` yet (or returned empty). Includes Jeju; deliberately
# conservative. This is a region gate for Kakao vs MapKit, not a full geocoder.
_KR_LAT_MIN, _KR_LAT_MAX = 33.0, 38.72
_KR_LON_MIN, _KR_LON_MAX = 124.5, 132.0


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_rows(path: str = CSV_PATH) -> List[Dict[str, str]]:
    # A fresh installation has no eval CSV until the first dataset is ingested.
    # Treat that as an empty collection; callers can render an honest empty state
    # instead of turning normal first-run state into HTTP 500.
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse_lat_lon(row: Dict[str, str]) -> Optional[Tuple[float, float]]:
    lat_s = (row.get("capture_lat") or "").strip()
    lon_s = (row.get("capture_lon") or "").strip()
    if not lat_s or not lon_s:
        return None
    try:
        lat, lon = float(lat_s), float(lon_s)
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if lat != lat or lon != lon:  # NaN
        return None
    return lat, lon


def region_from_coords(lat: float, lon: float) -> str:
    """Return ``kr`` or ``non_kr`` for a valid coordinate pair."""
    if _KR_LAT_MIN <= lat <= _KR_LAT_MAX and _KR_LON_MIN <= lon <= _KR_LON_MAX:
        return "kr"
    return "non_kr"


def region_hint_for_row(row: Dict[str, str]) -> Optional[str]:
    """``kr`` / ``non_kr`` from capture GPS, or None when coordinates are missing."""
    pair = _parse_lat_lon(row)
    if pair is None:
        return None
    return region_from_coords(pair[0], pair[1])


def normalize_country_name(raw: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    """Normalize a country string; empty input stays empty (not ``Unknown``)."""
    s = (raw or "").strip()
    if not s:
        return ""
    cfg = cfg or {}
    return (cfg.get("country_normalize") or {}).get(s, s)


def canonical_country(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    """Best-effort display country for a row.

    Authority order (provider routing uses :func:`provider_for_row`, not this alone):
    1. Per-row ``country`` (reverse-geocode / export) — primary trusted signal
    2. GPS KR bbox → ``South Korea`` when country cell is empty
    3. Optional ``country_by_dataset`` config — **display-only fallback**, untrusted
       for mixed or new datasets; never used as the sole MapKit default
    4. ``Unknown``
    """
    raw = (row.get("country") or "").strip()
    if raw:
        return normalize_country_name(raw, cfg) or "Unknown"
    # GPS can assert Korea without reverse geocode.
    if region_hint_for_row(row) == "kr":
        return "South Korea"
    # Legacy optional map — last resort for dashboards only.
    ds = (row.get("dataset") or "").strip()
    by_ds = cfg.get("country_by_dataset") or {}
    if ds in by_ds:
        return normalize_country_name(str(by_ds[ds]), cfg) or "Unknown"
    return "Unknown"


def provider_for_row(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    """MapKit vs Kakao ownership for a row.

    Never maps ``Unknown`` country to MapKit. Order:
    1. Per-row geocoded/export ``country`` (KR names → Kakao, other non-empty → MapKit)
    2. Capture GPS region (KR bbox → Kakao, outside → MapKit)
    3. ``unresolved`` when neither country nor GPS can decide
    """
    raw = (row.get("country") or "").strip()
    if raw:
        country = normalize_country_name(raw, cfg)
        if country in KR_NAMES:
            return PROVIDER_KAKAO
        if country:
            return PROVIDER_MAPKIT
    hint = region_hint_for_row(row)
    if hint == "kr":
        return PROVIDER_KAKAO
    if hint == "non_kr":
        return PROVIDER_MAPKIT
    return PROVIDER_UNRESOLVED


def input_place_name(row: Dict[str, str]) -> str:
    return (row.get("input_place_name") or "").strip()


# These values document the outcome of provider-name resolution. They are not
# provider-canonical POI names and must never be used as answer strings.
GT_SENTINEL_STATUS = {
    "NON_MAPKIT": "non_mapkit",
    "SIM_MAPKIT": "sim_mapkit",
    "NON_KAKAO": "non_kakao",
    "SIM_KAKAO": "sim_kakao",
    "KOR": "other_provider_marker",
    "NON_KR": "other_provider_marker",
}


def load_gt_mapkit_overrides(path: Optional[str] = None) -> Dict[Tuple[str, str], Dict[str, str]]:
    """Load Reconcile-UI overrides keyed by ``(dataset, photo)``.

    Later rows win when the same key is written more than once. Empty / missing
    files yield an empty dict (first-run safe).
    """
    path = path or GT_MAPKIT_OVERRIDES_PATH
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            ds = (row.get("dataset") or "").strip()
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            out[(ds, photo)] = {k: (v if v is not None else "") for k, v in row.items()}
    return out


def overlay_gt_mapkit_overrides(
    rows: List[Dict[str, str]],
    overrides: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
    *,
    path: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], int]:
    """Return shallow-copied rows with ``gt_mapkit`` patched from overrides.

    Non-destructive: the CSV is never written. Rules for a matching override:

    * ``chosen`` non-empty → ``gt_mapkit = chosen`` (promotes NON_MAPKIT →
      canonical for scoring / eligibility).
    * ``chosen_none`` truthy (or empty chosen after a deliberate save) → keep
      sentinel ``NON_MAPKIT`` (confirmed absence).
    * no override → row unchanged.

    Returns ``(rows, n_applied)`` where ``n_applied`` counts rows whose
    ``gt_mapkit`` value changed.
    """
    if overrides is None:
        overrides = load_gt_mapkit_overrides(path)
    if not overrides:
        return rows, 0
    out: List[Dict[str, str]] = []
    applied = 0
    for row in rows:
        ds = (row.get("dataset") or "").strip()
        photo = (row.get("photo") or "").strip()
        ovr = overrides.get((ds, photo))
        if not ovr:
            out.append(row)
            continue
        chosen = (ovr.get("chosen") or "").strip()
        chosen_none = str(ovr.get("chosen_none") or "").strip().lower() in {
            "1", "true", "yes", "y",
        }
        new_row = dict(row)
        before = (new_row.get("gt_mapkit") or "").strip()
        if chosen:
            new_row["gt_mapkit"] = chosen
            new_row["_gt_mapkit_override"] = "chosen"
            new_row["_gt_mapkit_override_source"] = "reconcile"
        elif chosen_none or (ovr.get("chosen") is not None and not chosen):
            # Explicit "not in MapKit" — keep non-canonical sentinel.
            new_row["gt_mapkit"] = "NON_MAPKIT"
            new_row["_gt_mapkit_override"] = "none"
            new_row["_gt_mapkit_override_source"] = "reconcile"
        else:
            out.append(row)
            continue
        if (new_row.get("gt_mapkit") or "").strip() != before:
            applied += 1
        out.append(new_row)
    return out, applied


def gt_resolution(row: Dict[str, str], provider: str) -> Tuple[str, str]:
    """Return ``(canonical_name, resolution_status)`` for a provider.

    The provider GT field is authoritative. The raw input name is the string
    being verified, so falling back to it would manufacture a canonical label.
    Empty cells and classifier sentinel values are ineligible for canonical-name
    scoring.

    When rows have been passed through ``overlay_gt_mapkit_overrides``, a
    reconciled MapKit name already sits in ``gt_mapkit`` and is treated as
    canonical here — no second lookup is required.
    """
    col = "gt_kakao" if provider == "kakao_local" else "gt_mapkit"
    value = (row.get(col) or "").strip()
    if not value:
        return "", "no_gt"
    status = GT_SENTINEL_STATUS.get(value)
    if status:
        return "", status
    return value, "canonical"


def gt_for_provider(row: Dict[str, str], provider: str) -> str:
    """Provider-canonical GT name, or empty when resolution is not canonical."""
    return gt_resolution(row, provider)[0]


def confidence_tier(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    raw = (row.get("gt_confidence") or "").strip()
    return (cfg.get("confidence_rollup") or {}).get(raw, raw)


def exact_equal(a: str, b: str) -> bool:
    return (a or "").strip() == (b or "").strip()


def normalized_equal(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        s = (s or "").casefold().strip()
        s = re.sub(r"[\s\-_·•|/\\]+", " ", s)
        s = re.sub(r"[^\w\s가-힣ぁ-んァ-ン一-龯]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    return bool(norm(a) and norm(a) == norm(b))


def load_label_relations(path: Optional[str] = None) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Load reviewed GT alias/relation sidecar keyed by (dataset, photo, provider).

    Canonical GT in the CSV is never overwritten; aliases only expand accepted
    predictions (strict / alias / related layers).

    When ``path`` is omitted, resolve the sidecar under the current data root
    (see ``default_label_relations_path``) so a post-start seed is visible.
    """
    path = path or default_label_relations_path()
    out: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid JSONL in {path}:{line_no}: {e}") from e
            ds = (rec.get("dataset") or "").strip()
            photo = (rec.get("photo") or "").strip()
            provider = (rec.get("provider") or "mapkit").strip()
            if not ds or not photo:
                raise ValueError(f"{path}:{line_no}: dataset and photo are required")
            key = (ds, photo, provider)
            if key in out:
                raise ValueError(f"{path}:{line_no}: duplicate key {key}")
            aliases = rec.get("accepted_aliases") or []
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise ValueError(f"{path}:{line_no}: accepted_aliases must be a string list")
            relations = rec.get("relations") or []
            if not isinstance(relations, list):
                raise ValueError(f"{path}:{line_no}: relations must be a list")
            out[key] = {
                "gt_canonical_name": (rec.get("gt_canonical_name") or "").strip(),
                "accepted_aliases": [a.strip() for a in aliases if a and a.strip()],
                "relations": relations,
                "review_status": rec.get("review_status") or "",
                "evidence": rec.get("evidence") or "",
            }
    return out


def accepted_gt_names(gt: str, dataset: str, photo: str, provider: str = "mapkit",
                      relations: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None
                      ) -> List[str]:
    """Canonical GT plus reviewed aliases for this case (deduped, order preserved)."""
    names: List[str] = []
    seen = set()

    def add(name: str) -> None:
        n = (name or "").strip()
        if not n or n in seen:
            return
        seen.add(n)
        names.append(n)

    add(gt)
    if relations:
        rec = relations.get((dataset, photo, provider))
        if rec:
            canon = rec.get("gt_canonical_name") or ""
            if canon and gt and not exact_equal(canon, gt) and not normalized_equal(canon, gt):
                # Sidecar canon should match CSV GT; still allow aliases either way.
                pass
            for alias in rec.get("accepted_aliases") or []:
                add(alias)
    return names


def match_prediction(gt: str, pred: str, dataset: str = "", photo: str = "",
                     provider: str = "mapkit", mode: str = "exact",
                     relations: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None
                     ) -> Dict[str, Any]:
    """Score one prediction against GT (+ optional reviewed aliases).

    Returns match_kind:
      - exact: primary GT string match (exact or normalized per mode)
      - alias: reviewed accepted_aliases match only
      - related: reviewed relation name (credit 0 for main accuracy)
      - wrong / abstain
    """
    pred = (pred or "").strip()
    if not pred:
        return {"correct_strict": False, "correct_canonical": False,
                "match_kind": "abstain", "matched_label": ""}

    matcher = exact_equal if mode in ("exact", "raw") else normalized_equal
    if matcher(gt, pred):
        return {"correct_strict": True, "correct_canonical": True,
                "match_kind": "exact", "matched_label": gt}

    # Normalized fallback for strict-looking labels when mode is exact? No —
    # keep exact mode strict on the primary string only.
    for name in accepted_gt_names(gt, dataset, photo, provider, relations):
        if name == gt:
            continue
        if matcher(name, pred) or (mode in ("exact", "raw") and normalized_equal(name, pred)):
            # Aliases: allow light normalization so "Sagrada Familia" forms match.
            return {"correct_strict": False, "correct_canonical": True,
                    "match_kind": "alias", "matched_label": name}

    if relations:
        rec = relations.get((dataset, photo, provider)) or {}
        for rel in rec.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            rname = (rel.get("name") or "").strip()
            if rname and (matcher(rname, pred) or normalized_equal(rname, pred)):
                credit = float(rel.get("credit") or 0)
                if credit >= 1.0:
                    # Reviewed same-destination credit (product metric).
                    return {
                        "correct_strict": False,
                        "correct_canonical": True,
                        "match_kind": "related_credit",
                        "matched_label": rname,
                        "relation": rel.get("relation") or "",
                    }
                return {
                    "correct_strict": False,
                    "correct_canonical": False,
                    "match_kind": "related",
                    "matched_label": rname,
                    "relation": rel.get("relation") or "",
                }

    return {"correct_strict": False, "correct_canonical": False,
            "match_kind": "wrong", "matched_label": ""}


def parse_top_candidates(top: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, part in enumerate((top or "").split(" | "), start=1):
        part = part.strip()
        if not part:
            continue
        name, _, dist = part.rpartition("@")
        out.append({
            "name": (name or part).strip(),
            "rank": idx,
            "distance_m": _num_or_none(dist.strip().replace("m", "")),
        })
    return out


def _num_or_none(v: str) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def names_within_gt_radius(
    candidates: List[Dict[str, Any]],
    radius_m: float = MAPKIT_GT_RADIUS_M,
) -> List[str]:
    """MapKit place names kept for GT labeling after a distance cut.

    Nearby probes are already radius-scoped (wide = 250 m). When ``distance_m``
    is present we still enforce the cut so a wider investigate probe cannot
    leak far-away chain-store names into GT. Missing distance keeps the name
    (legacy top3 rows, or probes that only guarantee in-radius membership).
    """
    names: List[str] = []
    seen: set = set()

    def _rank_key(c: Dict[str, Any]) -> int:
        try:
            return int(c.get("rank") or 999999)
        except (TypeError, ValueError):
            return 999999

    def _dist_key(c: Dict[str, Any]) -> float:
        try:
            return float(c.get("distance_m"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1e18

    ordered = sorted(candidates or [], key=lambda c: (_rank_key(c), _dist_key(c)))
    for c in ordered:
        name = (c.get("name") or "").strip()
        if not name or name in seen:
            continue
        dist = c.get("distance_m")
        if dist is not None and dist != "":
            try:
                if float(dist) > float(radius_m) + 1e-6:
                    continue
            except (TypeError, ValueError):
                continue
        seen.add(name)
        names.append(name)
    return names


def parse_mapkit_tsv_records(tsv_path: str, allow_lossy_top3: bool = False) -> List[Dict[str, Any]]:
    """Parse a MapKit probe TSV into candidate records.

    A successful probe with no nearby places gets an explicit empty sentinel,
    so the runner can distinguish "probed, none" from a missing artifact.
    """
    rows: List[Dict[str, str]] = []
    with open(tsv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        # Probe TSV contains JSON with many commas, which can fool Sniffer.
        # The header is authoritative and all current probe output is tab-separated.
        first_line = sample.splitlines()[0] if sample else ""
        delimiter = "\t" if "\t" in first_line else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        has_full_column = bool(reader.fieldnames) and (
            "wide_candidates_json" in reader.fieldnames or "candidates_json" in reader.fieldnames
        )
        if not has_full_column and not allow_lossy_top3:
            raise ValueError(
                f"{os.path.basename(tsv_path)} has no full candidate JSON column. "
                "It is a legacy top3-only probe; re-probe with the current tool, or "
                "pass allow_lossy_top3=True for non-scoring historical audit only."
            )
        rows.extend(dict(row) for row in reader)

    records: List[Dict[str, Any]] = []
    for row in rows:
        photo = (row.get("photo") or row.get("file") or row.get("filename") or "").strip()
        if not photo:
            continue
        raw_json = row.get("wide_candidates_json") or row.get("candidates_json") or ""
        candidates: List[Dict[str, Any]] = []
        if has_full_column:
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid candidate JSON for photo {photo!r} in {os.path.basename(tsv_path)}"
                ) from exc
            if not isinstance(parsed, list) or any(not isinstance(c, dict) for c in parsed):
                raise ValueError(
                    f"candidate JSON for photo {photo!r} in {os.path.basename(tsv_path)} "
                    "must be an array of objects"
                )
            candidates = parsed
        if not candidates and allow_lossy_top3:
            top3 = row.get("top3_wide") or row.get("top3") or ""
            for i, part in enumerate(top3.split(" | "), start=1):
                part = part.strip()
                if not part:
                    continue
                name, dist = part, None
                if "@" in part:
                    name, raw_dist = part.rsplit("@", 1)
                    try:
                        dist = float(raw_dist.rstrip("m"))
                    except ValueError:
                        pass
                candidates.append({"name": name.strip(), "distance_m": dist, "rank": i,
                                   "lossy_top3_summary": True})
        if not candidates:
            records.append({"photo": photo, "provider": "mapkit",
                            "candidate_artifact_status": "empty",
                            "source": os.path.basename(tsv_path)})
            continue
        for i, cand in enumerate(candidates, start=1):
            rec = {
                "photo": photo,
                "provider": "mapkit",
                "provider_place_id": cand.get("provider_place_id"),
                "name": cand.get("name") or "",
                "lat": cand.get("lat"),
                "lon": cand.get("lon"),
                "address": cand.get("address") or "",
                "category": cand.get("category") or "",
                "rank": cand.get("rank") or i,
                "distance_m": cand.get("distance_m"),
                "source": os.path.basename(tsv_path),
            }
            if cand.get("lossy_top3_summary"):
                rec["lossy_top3_summary"] = True
            records.append(rec)
    return records


def _write_candidate_records(out_path: str, records: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp_path = out_path + ".tmp"
    n = 0
    with open(tmp_path, "w", encoding="utf-8") as out:
        for rec in records:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp_path, out_path)
    return n


def convert_mapkit_tsv(tsv_path: str, out_path: str, allow_lossy_top3: bool = False) -> int:
    """Replace ``out_path`` with records parsed from one probe TSV."""
    return _write_candidate_records(out_path, parse_mapkit_tsv_records(tsv_path, allow_lossy_top3))


def upsert_mapkit_candidates_from_tsv(tsv_path: str, out_path: Optional[str] = None,
                                      allow_lossy_top3: bool = False) -> int:
    """Merge a probe TSV into the legacy run artifact by photo key."""
    target = out_path or os.path.join(CANDIDATE_DIR, "mapkit_candidates.jsonl")
    updates = parse_mapkit_tsv_records(tsv_path, allow_lossy_top3)
    updated_photos = {str(rec.get("photo") or "") for rec in updates}
    kept: List[Dict[str, Any]] = []
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as existing:
            for line in existing:
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(rec, dict) and str(rec.get("photo") or "") not in updated_photos:
                    kept.append(rec)
    _write_candidate_records(target, [*kept, *updates])
    return len(updates)

def load_candidates(paths: Optional[Iterable[str]] = None) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Load candidates, resolving the active snapshot now when paths are omitted."""
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for path in default_candidate_files() if paths is None else paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                photo = (rec.get("photo") or rec.get("case_id") or "").strip()
                dataset = (rec.get("dataset") or "").strip()
                provider = (rec.get("provider") or "").strip()
                if not photo or not provider:
                    continue
                # A completed full snapshot can truthfully contain zero
                # candidates. Keep an explicit key for that response so the
                # evaluator distinguishes it from an unavailable artifact.
                key_photo = f"{dataset}/{photo}" if dataset else photo
                if rec.get("candidate_artifact_status") == "empty":
                    grouped[(provider, key_photo)]
                    continue
                try:
                    rec["rank"] = int(rec.get("rank") or 0)
                except Exception:
                    rec["rank"] = 0
                # Versioned full snapshots qualify a photo by dataset; legacy
                # artifacts remain on their original bare-photo key.
                grouped[(provider, key_photo)].append(rec)
    for key in list(grouped):
        grouped[key].sort(key=lambda r: (r.get("rank") or 999999))
    return grouped


def _rank_from_candidates(gt: str, candidates: List[Dict[str, Any]], matcher: Callable[[str, str], bool]) -> Optional[int]:
    for idx, cand in enumerate(candidates, start=1):
        rank = int(cand.get("rank") or idx)
        if matcher(gt, cand.get("name") or ""):
            return rank
    return None


def _rank_from_legacy(row: Dict[str, str]) -> Optional[int | str]:
    rk = (row.get("app_poi_rank") or "").strip()
    if not rk:
        return None
    if rk == "MISS":
        return "MISS"
    if rk.isdigit():
        return int(rk)
    return None


def evaluate(dataset: str = "all", mode: str = "exact", rows: Optional[List[Dict[str, str]]] = None,
             candidates: Optional[Dict[Tuple[str, str], List[Dict[str, Any]]]] = None,
             cfg: Optional[Dict[str, Any]] = None,
             *,
             apply_overrides: bool = True,
             overrides_path: Optional[str] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    rows = rows if rows is not None else read_rows()
    overrides_applied = 0
    if apply_overrides:
        rows, overrides_applied = overlay_gt_mapkit_overrides(rows, path=overrides_path)
    candidates = candidates if candidates is not None else load_candidates()
    matcher = exact_equal if mode in ("exact", "raw") else normalized_equal

    counts = Counter()
    by_provider: Dict[str, Counter] = defaultdict(Counter)
    by_dataset: Dict[str, Counter] = defaultdict(Counter)
    cases: List[Dict[str, Any]] = []

    for row in rows:
        ds = (row.get("dataset") or "").strip()
        if dataset != "all" and ds != dataset:
            continue
        counts["rows"] += 1
        tier = confidence_tier(row, cfg)
        provider = provider_for_row(row, cfg)
        gt, gt_status = gt_resolution(row, provider)
        counts[f"gt_{gt_status}"] += 1
        country = canonical_country(row, cfg)
        photo = (row.get("photo") or "").strip()

        if provider == PROVIDER_UNRESOLVED:
            # No country and no usable GPS — must not pretend this is MapKit.
            status = "excluded_unresolved_country"
            counts[status] += 1
        elif provider == PROVIDER_KAKAO:
            status = "excluded_korea_pending_kakao"
            counts[status] += 1
        elif tier == "non_poi":
            status = "excluded_non_poi"
            counts[status] += 1
        elif gt_status != "canonical":
            # A classifier result (NON_*/SIM_*) is metadata, never a GT name.
            status = f"excluded_{gt_status}"
            counts[status] += 1
        else:
            counts["eligible"] += 1
            cand = candidates.get((provider, photo), [])
            rank: Optional[int | str]
            legacy_rank = _rank_from_legacy(row) if provider == "mapkit" else None
            if legacy_rank is not None:
                # Backward-compatible source of truth for the current reconciled CSV.
                # It was produced by the MapKit probe and includes ranks beyond the
                # top3 preview stored in ls_nearby_results.tsv. Do not let the
                # lossy preview JSONL override this complete rank field.
                rank = legacy_rank
                source = "legacy_app_poi_rank"
            elif cand:
                rank = _rank_from_candidates(gt, cand, matcher)
                if rank is None:
                    rank = "MISS"
                source = "candidate_jsonl"
            else:
                rank = None
                source = "none"

            if rank is None:
                status = "no_provider_data"
                counts[status] += 1
            else:
                counts["evaluated"] += 1
                by_provider[provider]["evaluated"] += 1
                by_dataset[ds]["evaluated"] += 1
                if rank == "MISS":
                    status = "search_failure"
                    counts["miss"] += 1
                    counts[status] += 1
                    by_provider[provider]["miss"] += 1
                    by_dataset[ds]["miss"] += 1
                else:
                    r = int(rank)
                    status = "correct" if r == 1 else "selection_failure"
                    if r == 1:
                        counts["rank1"] += 1
                        by_provider[provider]["rank1"] += 1
                        by_dataset[ds]["rank1"] += 1
                    else:
                        counts["selection_failure"] += 1
                    if r <= 3:
                        counts["top3"] += 1
                        by_provider[provider]["top3"] += 1
                        by_dataset[ds]["top3"] += 1
                    for cutoff in (5, 10, 20, 50):
                        if r <= cutoff:
                            key = f"top{cutoff}"
                            counts[key] += 1
                            by_provider[provider][key] += 1
                            by_dataset[ds][key] += 1

        by_provider[provider]["rows"] += 1
        by_dataset[ds]["rows"] += 1
        if len(cases) < 500:
            cases.append({
                "dataset": ds,
                "photo": photo,
                "gt": gt,
                "country": country,
                "provider": provider,
                "status": status,
                "rank": None if 'rank' not in locals() else rank,
                "source": None if 'source' not in locals() else source,
            })
        # avoid leaking previous loop values into excluded rows
        if 'rank' in locals():
            del rank
        if 'source' in locals():
            del source

    n = counts["evaluated"]

    def rate(k: str) -> float:
        return (counts[k] / n) if n else 0.0

    def summarize(counter: Counter) -> Dict[str, Any]:
        en = counter["evaluated"]
        return {
            "rows": counter["rows"],
            "evaluated": en,
            "rank1": counter["rank1"],
            "top3": counter["top3"],
            "top5": counter["top5"],
            "top10": counter["top10"],
            "top20": counter["top20"],
            "top50": counter["top50"],
            "miss": counter["miss"],
            "rank1_rate": counter["rank1"] / en if en else 0.0,
            "top3_rate": counter["top3"] / en if en else 0.0,
            "top5_rate": counter["top5"] / en if en else 0.0,
            "top10_rate": counter["top10"] / en if en else 0.0,
            "top20_rate": counter["top20"] / en if en else 0.0,
            "top50_rate": counter["top50"] / en if en else 0.0,
            "miss_rate": counter["miss"] / en if en else 0.0,
        }

    return {
        "dataset": dataset,
        "mode": "exact" if mode in ("raw", "exact") else "normalized",
        "matching_policy": {
            "primary": "same-provider exact string equality",
            "korea_provider": "kakao_local (held out until Kakao data is available)",
            "non_korea_provider": "mapkit",
            "provider_place_id": "nullable/fallback; not required for MVP scoring",
            "gt_mapkit_overrides": (
                "read-time overlay from gt_mapkit_overrides.tsv "
                "(Reconcile UI); promotes chosen names to canonical"
            ),
        },
        "overrides_applied": overrides_applied,
        "counts": dict(counts),
        "n": n,
        "rank1": counts["rank1"],
        "top3": counts["top3"],
        "top5": counts["top5"],
        "top10": counts["top10"],
        "top20": counts["top20"],
        "top50": counts["top50"],
        "miss": counts["miss"],
        "rank1_rate": rate("rank1"),
        "top3_rate": rate("top3"),
        "top5_rate": rate("top5"),
        "top10_rate": rate("top10"),
        "top20_rate": rate("top20"),
        "top50_rate": rate("top50"),
        "miss_rate": rate("miss"),
        "search_failure": counts["search_failure"],
        "selection_failure": counts["selection_failure"],
        "no_provider_data": counts["no_provider_data"],
        "excluded_non_poi": counts["excluded_non_poi"],
        "excluded_no_gt": counts["excluded_no_gt"],
        "excluded_non_mapkit": counts["excluded_non_mapkit"],
        "excluded_sim_mapkit": counts["excluded_sim_mapkit"],
        "excluded_korea_pending_kakao": counts["excluded_korea_pending_kakao"],
        "by_provider": {k: summarize(v) for k, v in sorted(by_provider.items())},
        "by_dataset": {k: summarize(v) for k, v in sorted(by_dataset.items())},
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Provider-aware POI candidate-retrieval metrics")
    ap.add_argument("--dataset", default="all")
    ap.add_argument("--mode", default="exact", choices=["exact", "raw", "normalized"])
    ap.add_argument("--csv", default=CSV_PATH)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--convert-mapkit-tsv", metavar="TSV")
    ap.add_argument("--allow-lossy-top3", action="store_true",
                    help="permit converting a legacy top3-only TSV for AUDITING only; "
                         "records are marked lossy and must not back a scored run")
    ap.add_argument("--out", default=os.path.join(CANDIDATE_DIR, "mapkit_candidates.jsonl"))
    args = ap.parse_args()

    if args.convert_mapkit_tsv:
        n = convert_mapkit_tsv(args.convert_mapkit_tsv, args.out,
                               allow_lossy_top3=args.allow_lossy_top3)
        print(json.dumps({"ok": True, "written": n, "out": args.out}, ensure_ascii=False))
        return 0

    result = evaluate(dataset=args.dataset, mode=args.mode, rows=read_rows(args.csv))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"n={result['n']} rank1={result['rank1']} top3={result['top3']} top5={result['top5']} miss={result['miss']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
