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
DATA_ROOT = os.environ.get("POI_DATA_DIR") or (
    _REPO_DATA_DIR if os.path.isfile(os.path.join(_REPO_DATA_DIR, "eval_set_reconciled.csv")) else ROOT
)
CSV_PATH = os.path.join(DATA_ROOT, "eval_set_reconciled.csv")
_data_cfg = os.path.join(DATA_ROOT, "dashboard_config.json")
CONFIG_PATH = _data_cfg if os.path.exists(_data_cfg) else os.path.join(ROOT, "dashboard_config.json")
CANDIDATE_DIR = os.path.join(DATA_ROOT, "generated")
ACTIVE_MAPKIT_SNAPSHOT_POINTER = "active-mapkit-candidate-snapshot.json"
DEFAULT_LABEL_RELATIONS_PATH = os.path.join(DATA_ROOT, "eval_label_relations.v1.jsonl")
# Manual GT↔MapKit matches from the Reconcile UI. Applied at read time so
# matchrate / algorithm runs see reconciled names without rewriting the CSV.
GT_MAPKIT_OVERRIDES_PATH = os.path.join(DATA_ROOT, "gt_mapkit_overrides.tsv")


def active_mapkit_candidate_file(data_root: Optional[str] = None) -> str:
    """Return the explicitly selected immutable MapKit candidate artifact.

    Without a selection pointer, retain the legacy artifact for compatibility.
    Once a pointer exists, it is authoritative: an incomplete or tampered
    snapshot is an evaluation configuration error, not a fallback opportunity.
    """
    root = data_root or DATA_ROOT
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


DEFAULT_CANDIDATE_FILES = [
    active_mapkit_candidate_file(),
    os.path.join(CANDIDATE_DIR, "kakao_local_candidates.jsonl"),
]

KR_NAMES = {"South Korea", "Korea", "Republic of Korea", "대한민국", "한국", "KR", "KOR"}


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


def canonical_country(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    ds = (row.get("dataset") or "").strip()
    by_ds = cfg.get("country_by_dataset") or {}
    if ds in by_ds:
        return by_ds[ds]
    raw = (row.get("country") or "").strip()
    return (cfg.get("country_normalize") or {}).get(raw, raw or "Unknown")


def provider_for_row(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    return "kakao_local" if canonical_country(row, cfg) in KR_NAMES else "mapkit"


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

    See docs/reports/semantic-evaluation-policy-proposal-ko.md. Canonical GT in
    the CSV is never overwritten; aliases only expand accepted predictions.
    """
    path = path or DEFAULT_LABEL_RELATIONS_PATH
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


def convert_mapkit_tsv(tsv_path: str, out_path: str, allow_lossy_top3: bool = False) -> int:
    """Convert the current MapKit TSV probe output to candidate JSONL.

    Current probe output carries the *full* candidate list in
    ``wide_candidates_json``. Legacy probes only persisted ``top3_wide`` -- a
    three-name display summary that discards every candidate MapKit actually
    returned (``wide_n`` is routinely 20-50). Silently converting such a TSV
    yields a candidate artifact capped at three per photo, which then presents
    as an unfixable "the model can't return a stable top-5" failure downstream.

    A top3-only TSV is therefore rejected by default: the dropped candidates are
    gone at collection time and no selector can recover them. Pass
    ``allow_lossy_top3=True`` only for historical auditing of an old probe; each
    record from that path is stamped ``"lossy_top3_summary": True`` so it can
    never be mistaken for a complete candidate list.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    n = 0
    lossy_photos = 0
    with open(tsv_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        has_full_column = bool(reader.fieldnames) and "wide_candidates_json" in reader.fieldnames
        if not has_full_column and not allow_lossy_top3:
            raise ValueError(
                f"{os.path.basename(tsv_path)} has no 'wide_candidates_json' column: it is a "
                "legacy top3-only probe whose full candidate list was never persisted. "
                "Converting it would cap candidates at 3 per photo and silently drop the "
                "ground truth for cases where MapKit ranked it 4+. Re-probe with the current "
                "full-candidate probe, or pass allow_lossy_top3=True to convert it for "
                "auditing only (records are marked lossy and must not back a scored run)."
            )
        rows = list(reader)
    with open(out_path, "w", encoding="utf-8") as out:
        for row in rows:
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            rich_candidates = []
            raw_candidates = (row.get("wide_candidates_json") or "").strip()
            if raw_candidates:
                try:
                    parsed = json.loads(raw_candidates)
                    if isinstance(parsed, list):
                        rich_candidates = [c for c in parsed if isinstance(c, dict)]
                except json.JSONDecodeError:
                    rich_candidates = []
            is_lossy = not rich_candidates
            source_candidates = rich_candidates or parse_top_candidates(row.get("top3_wide") or "")
            if is_lossy and source_candidates:
                lossy_photos += 1
            for fallback_rank, cand in enumerate(source_candidates, start=1):
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
                    "source": os.path.basename(tsv_path),
                }
                if is_lossy:
                    rec["lossy_top3_summary"] = True
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    if lossy_photos and allow_lossy_top3:
        import sys as _sys
        print(
            f"WARNING: {lossy_photos} photo(s) converted from top3-only summary "
            "(candidates capped at 3, marked lossy_top3_summary). Do not score a run on this artifact.",
            file=_sys.stderr,
        )
    return n


def load_candidates(paths: Iterable[str] = DEFAULT_CANDIDATE_FILES) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for path in paths:
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

        if provider == "kakao_local":
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
