#!/usr/bin/env python3
"""Algorithm submission harness for the POI evaluation dashboard.

A submission is a script that implements a single `predict(case)` function (or,
for non-Python languages, a stdin-JSONL -> stdout-JSONL program). The harness:

  1. builds one input `case` per *eligible* eval row (has GT, non-Korea,
     not non_poi) exposing only the signals the submitter selected,
  2. runs the submission over every case in an isolated subprocess,
  3. scores each prediction against the human GT place name using the same
     provider-exact matching policy as match_score (identification accuracy),
  4. persists the run under generated/runs/<name>__v<k>.json with name-based
     versioning, and returns a summary.

This is *identification* accuracy (did the algorithm name the right place),
which is distinct from the candidate-retrieval coverage in match_score.

Standard library only, to match the rest of the workspace.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import match_score as ms
from file_ops import atomic_write_json, file_lock

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_predict_runner.py")
# Full MapKit-backed submissions may legitimately take many minutes. Runs are
# unlimited by default; set POI_RUN_TIMEOUT_S to a positive number to add a
# deployment-specific guard.
_timeout_raw = os.environ.get("POI_RUN_TIMEOUT_S", "").strip()
try:
    RUN_TIMEOUT_S: Optional[float] = float(_timeout_raw) if _timeout_raw else None
except ValueError:
    RUN_TIMEOUT_S = None
if RUN_TIMEOUT_S is not None and RUN_TIMEOUT_S <= 0:
    RUN_TIMEOUT_S = None
NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

# param key (from the UI) -> which signal keys it injects into the case
PARAM_SIGNALS = {
    "image": ("photo", "photo_url"),
    "lat,lon": ("lat", "lon"),
    "timestamp": ("timestamp",),
    "ocr_text": ("ocr_text",),
    "vlm_caption": ("vlm_caption",),
    "nearby_candidates": ("nearby_candidates",),
    "city,country,address": ("geocode",),
}
ALL_PARAMS = list(PARAM_SIGNALS.keys())


class RunError(Exception):
    """A submission-level error that should surface to the user (422)."""


def _safe_name(name: str) -> str:
    """Stable filesystem / versioning slug for a run.

    Collapses whitespace and punctuation to ``-``, lowercases, strips leading
    timestamps / random hex prefixes (the historical source of 30+ near-dup
    names), and caps length so versions stay readable.
    """
    raw = (name or "").strip()
    # Drop trailing version suffixes users sometimes type ("algo-v3" → "algo").
    raw = re.sub(r"(?:__)?v\d+$", "", raw, flags=re.I).strip("-_ ")
    # Strip leading ObjectId / UUID / epoch noise if someone pastes a filename.
    raw = re.sub(
        r"^(?:[0-9a-f]{24}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|\d{10,13})[_-]+",
        "",
        raw,
        flags=re.I,
    )
    slug = NAME_RE.sub("-", raw).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")
    return slug or "algorithm"


def _candidate_names(candidates, provider: str, photo: str, row: Dict[str, str],
                     dataset: str = "") -> List[Dict[str, Any]]:
    """Return only records stored in the candidate artifact.

    ``app_nearby_top1`` is a scalar summary, not a candidate-list artifact. It
    cannot establish an original list, raw rank, or metadata, so it must never
    be promoted to a synthetic rank-one candidate.
    """
    # New snapshots use dataset-qualified keys. Bare-photo artifacts remain
    # readable solely for historical auditing.
    qualified = candidates.get((provider, f"{dataset}/{photo}"), []) if dataset else []
    source = qualified or candidates.get((provider, photo), [])
    out = []
    for c in source:
        entry = {
            "name": c.get("name") or "",
            "rank": c.get("rank"),
            "distance_m": c.get("distance_m"),
            "category": c.get("category") or "",
            "provider_place_id": c.get("provider_place_id"),
            "lat": c.get("lat"),
            "lon": c.get("lon"),
        }
        # Preserve the lossy marker so a scored run can refuse a top3-capped
        # artifact instead of reporting retrieval loss as selection failure.
        if c.get("lossy_top3_summary"):
            entry["lossy_top3_summary"] = True
        out.append(entry)
    return out


def _has_candidate_artifact(candidates, provider: str, photo: str, dataset: str = "") -> bool:
    """Return whether an artifact explicitly represents this case.

    A completed full probe can return ``[]``. That is an available empty input,
    unlike a case absent from the selected artifact altogether.
    """
    qualified = (provider, f"{dataset}/{photo}") if dataset else None
    return ((qualified in candidates if qualified else False)
            or (provider, photo) in candidates)


def row_ineligibility(row: Dict[str, str], cfg: Dict[str, Any]) -> Optional[str]:
    """Return the runner exclusion reason, or None when the row is eligible."""
    provider = ms.provider_for_row(row, cfg)
    _gt, gt_status = ms.gt_resolution(row, provider)
    tier = ms.confidence_tier(row, cfg)
    if provider == ms.PROVIDER_UNRESOLVED:
        return "unresolved_country"
    if provider == ms.PROVIDER_KAKAO:
        return "korea_pending_kakao"
    if tier == "non_poi":
        return "non_poi"
    if gt_status != "canonical":
        return gt_status or "no_gt"
    return None


def dataset_eligibility_summary(rows: List[Dict[str, str]], cfg: Dict[str, Any],
                                dataset: str,
                                candidates: Optional[Dict[Any, Any]] = None) -> Dict[str, Any]:
    """Summarize whether one dataset can pass ``build_cases`` preflight.

    Row exclusions use the exact runner policy. When candidates are supplied we
    also report artifact conditions that make ``build_cases`` fail.

    Counts (UI labels):
      * ``eligible`` / ``gt_eligible`` — canonical GT, MapKit provider, not non-POI
      * ``artifact_ready`` — GT-eligible rows that have a full candidate artifact
      * ``runnable_now`` — artifact-ready rows that are not lossy-summary-only
      * ``runnable`` — bool: at least one case can pass ``build_cases``
    """
    exclusions: Counter = Counter()
    blockers: Counter = Counter()
    total = eligible = 0
    for row in rows:
        if (row.get("dataset") or "").strip() != dataset:
            continue
        total += 1
        reason = row_ineligibility(row, cfg)
        if reason:
            exclusions[reason] += 1
            continue
        eligible += 1
        if candidates is not None:
            provider = ms.provider_for_row(row, cfg)
            photo = (row.get("photo") or "").strip()
            if not _has_candidate_artifact(candidates, provider, photo, dataset):
                blockers["missing_candidate_artifact"] += 1
            elif any(c.get("lossy_top3_summary") for c in
                     _candidate_names(candidates, provider, photo, row, dataset)):
                blockers["lossy_candidate_artifact"] += 1
    missing = int(blockers.get("missing_candidate_artifact") or 0)
    lossy = int(blockers.get("lossy_candidate_artifact") or 0)
    # When candidates were not supplied we cannot distinguish artifact readiness.
    if candidates is None:
        artifact_ready = eligible
        runnable_now = eligible
        runnable = eligible > 0
    else:
        artifact_ready = max(0, eligible - missing)
        runnable_now = max(0, artifact_ready - lossy)
        # build_cases fails on the first blocked eligible row, so the dataset is
        # only runnable when every GT-eligible row has a full (non-lossy) artifact.
        runnable = eligible > 0 and not blockers
    return {
        "rows": total,
        "eligible": eligible,
        "gt_eligible": eligible,
        "artifact_ready": artifact_ready,
        "runnable_now": runnable_now,
        "exclusions": dict(exclusions),
        "blockers": dict(blockers),
        "runnable": runnable,
    }


def build_cases(rows, cfg, candidates, dataset: str, params: Optional[List[str]],
                candidate_limit: Optional[int] = None,
                require_candidate_artifact: bool = True) -> List[Dict[str, Any]]:
    """Return eligible eval cases. Each has a public `input` (fed to predict,
    never containing GT) plus internal `_gt`/`_dataset`/`_photo` for scoring."""
    # None is the legacy/CLI default (all signals); [] deliberately means no
    # optional signals. Never leak inputs the user explicitly unchecked.
    selected = [p for p in (ALL_PARAMS if params is None else params) if p in PARAM_SIGNALS]
    wanted = set()
    for p in selected:
        wanted.update(PARAM_SIGNALS[p])

    # Comma-separated values are the persisted wire format for multi-dataset
    # runs; "all" and a single value remain backward compatible.
    selected_datasets = {x.strip() for x in dataset.split(",") if x.strip()}
    cases: List[Dict[str, Any]] = []
    for row in rows:
        ds = (row.get("dataset") or "").strip()
        if "all" not in selected_datasets and ds not in selected_datasets:
            continue
        if row_ineligibility(row, cfg):
            continue
        provider = ms.provider_for_row(row, cfg)
        gt, _gt_status = ms.gt_resolution(row, provider)
        photo = (row.get("photo") or "").strip()

        nearby_candidates = _candidate_names(candidates, provider, photo, row, ds)
        if require_candidate_artifact and not _has_candidate_artifact(candidates, provider, photo, ds):
            raise RunError(
                "Candidate-input artifact unavailable for eligible case "
                f"{ds}/{photo}. Refusing to synthesize a candidate from "
                "app_nearby_top1; collect or select a versioned full-candidate snapshot."
            )
        if any(c.get("lossy_top3_summary") for c in nearby_candidates):
            raise RunError(
                "Candidate artifact for eligible case "
                f"{ds}/{photo} was converted from a top3-only probe summary "
                "(lossy_top3_summary): its candidate list is capped at 3 and the "
                "true ranking was dropped at collection time. Scoring on it would "
                "misreport retrieval loss as selection failure. Re-probe with the "
                "full-candidate probe and select a complete snapshot before running."
            )
        full = {
            "photo": photo,
            "photo_url": (row.get("photo_url") or "").strip(),
            "lat": (row.get("capture_lat") or "").strip(),
            "lon": (row.get("capture_lon") or "").strip(),
            "timestamp": (row.get("timestamp") or "").strip(),
            "ocr_text": (row.get("caption_ondevice") or "").strip(),
            "vlm_caption": "",  # not extracted yet
            "nearby_candidates": nearby_candidates[:candidate_limit],
            "geocode": {
                "city": (row.get("city") or "").strip(),
                "country": (row.get("country") or "").strip(),
                "address": (row.get("address") or "").strip(),
            },

        }
        public = {k: v for k, v in full.items() if k in wanted}
        public["photo"] = photo  # always present as a reference id
        cases.append({
            "input": public, "_gt": gt, "_dataset": ds, "_photo": photo,
            "_provider": provider,
        })
    return cases


def _percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    """Nearest-rank percentile for a pre-sorted non-empty list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    # Inclusive nearest-rank: index = ceil(p/100 * n) - 1
    k = int((p / 100.0) * len(sorted_vals) + 0.999999999) - 1
    k = max(0, min(len(sorted_vals) - 1, k))
    return float(sorted_vals[k])


def _latency_summary(latencies: List[float]) -> Dict[str, Any]:
    if not latencies:
        return {"mean": None, "p50": None, "p95": None, "max": None, "n": 0}
    ordered = sorted(latencies)
    return {
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 50) or 0.0, 3),
        "p95": round(_percentile(ordered, 95) or 0.0, 3),
        "max": round(ordered[-1], 3),
        "n": len(ordered),
    }


def _host_runtime_info() -> Dict[str, Any]:
    """Describe the evaluation host. Values are not mobile-device measurements."""
    return {
        "device_class": "desktop_host",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "system": platform.system(),
        "notes": "Host-side wall time on this evaluation machine, not mobile runtime.",
    }


def _run_subprocess(script_path: str, lang: str, cases: List[Dict[str, Any]]):
    """Run the submission and return (preds, duration_ms).

    duration_ms is wall-clock for the whole subprocess, including process start.
    Per-case latency_ms (when present on each pred) is predict-call wall time only.
    """
    if lang == "python":
        cmd = [sys.executable, RUNNER, script_path]
    else:
        cmd = [script_path]  # non-python: script speaks the JSONL protocol itself
    stdin_data = "".join(json.dumps(c["input"], ensure_ascii=False) + "\n" for c in cases)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, input=stdin_data, capture_output=True,
                              text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RunError(f"submission timed out after {RUN_TIMEOUT_S:g}s")
    except (PermissionError, OSError) as e:
        raise RunError(f"could not execute submission: {e}")
    duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise RunError("submission failed to load: " + (detail[-1] if detail else f"exit {proc.returncode}"))

    preds: List[Dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            preds.append(json.loads(line))
        except json.JSONDecodeError:
            preds.append({"prediction": "", "error": "non-JSON line from submission", "latency_ms": None})
    return preds, duration_ms


def _score(cases, preds, mode: str,
           label_relations: Optional[Dict] = None) -> Dict[str, Any]:
    """Score predictions.

    Primary ``correct`` / ``accuracy`` remain **strict** (canonical GT string
    only) so historical leaderboards stay comparable.

    When ``label_relations`` is provided (reviewed alias sidecar), also emit:
      - correct_canonical / accuracy_canonical  (strict ∪ accepted_aliases)
      - match_kind breakdown (exact, alias, related, wrong, abstain)
    """
    n = len(cases)
    correct = correct_canonical = errored = abstained = 0
    kind_counts: Dict[str, int] = {}
    by_dataset: Dict[str, Dict[str, int]] = {}
    scored_cases: List[Dict[str, Any]] = []
    # Default: load sidecar if present so alias expansion works without callers
    # threading the path; pass {} to force strict-only dual metrics off... actually
    # None means auto-load; empty dict means no relations.
    if label_relations is None:
        label_relations = ms.load_label_relations()

    for i, c in enumerate(cases):
        p = preds[i] if i < len(preds) else {"prediction": "", "error": "no output for case"}
        pred = (p.get("prediction") or "").strip()
        err = p.get("error")
        gt = c["_gt"]
        provider = c.get("_provider") or "mapkit"
        match = ms.match_prediction(
            gt, pred, dataset=c["_dataset"], photo=c["_photo"],
            provider=provider, mode=mode, relations=label_relations,
        )
        is_correct = match["correct_strict"]
        is_canonical = match["correct_canonical"]
        match_kind = match["match_kind"]
        # An execution/protocol error is distinct from a blank prediction.
        # Keep outcome counts mutually exclusive for summaries and charts.
        if err:
            errored += 1
            match_kind = "error"
        elif not pred:
            abstained += 1
            match_kind = "abstain"
        if is_correct:
            correct += 1
        if is_canonical:
            correct_canonical += 1
        kind_counts[match_kind] = kind_counts.get(match_kind, 0) + 1
        d = by_dataset.setdefault(c["_dataset"], {"n": 0, "correct": 0, "correct_canonical": 0})
        d["n"] += 1
        d["correct"] += 1 if is_correct else 0
        d["correct_canonical"] += 1 if is_canonical else 0
        lat = p.get("latency_ms")
        try:
            latency_ms = float(lat) if lat is not None else None
        except (TypeError, ValueError):
            latency_ms = None
        scored_cases.append({
            "dataset": c["_dataset"], "photo": c["_photo"], "gt": gt,
            "prediction": pred, "reason": p.get("reason"),
            "correct": is_correct,
            "correct_canonical": is_canonical,
            "match_kind": match_kind,
            "matched_label": match.get("matched_label") or "",
            "error": err,
            "latency_ms": latency_ms,
        })
    accuracy = (correct / n) if n else 0.0
    accuracy_canonical = (correct_canonical / n) if n else 0.0
    latencies = [c["latency_ms"] for c in scored_cases if isinstance(c.get("latency_ms"), (int, float))]
    return {
        "n_eligible": n,
        "correct": correct,
        "correct_canonical": correct_canonical,
        "abstained": abstained,
        "errored": errored,
        "accuracy": accuracy,
        "accuracy_pct": round(100 * accuracy),
        "accuracy_canonical": accuracy_canonical,
        "accuracy_canonical_pct": round(100 * accuracy_canonical),
        "match_kind_counts": dict(sorted(kind_counts.items())),
        "by_dataset": {
            k: {
                **v,
                "accuracy": (v["correct"] / v["n"] if v["n"] else 0.0),
                "accuracy_canonical": (v["correct_canonical"] / v["n"] if v["n"] else 0.0),
            }
            for k, v in sorted(by_dataset.items())
        },
        "latency_ms": _latency_summary(latencies),
        "cases": scored_cases,
    }


def evaluation_set_sha256(cases: List[Dict[str, Any]]) -> str:
    """Identify the ordered evaluation cohort, including its answer labels.

    Algorithm inputs are excluded: runs using different signals are comparable
    when they were scored on the same examples and labels.  Both internal cases
    and scored cases persisted in run JSON are accepted for legacy support.
    """
    cohort = [{
        "dataset": c.get("_dataset", c.get("dataset", "")),
        "photo": c.get("_photo", c.get("photo", "")),
        "gt": c.get("_gt", c.get("gt", "")),
    } for c in cases]
    payload = json.dumps(cohort, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def data_snapshot_sha256(paths: List[str]) -> str:
    """Hash the source files that determine evaluation and candidate inputs."""
    digest = hashlib.sha256()
    for pos, path in enumerate(paths):
        digest.update(f"{pos}:{os.path.basename(path)}\0".encode("utf-8"))
        if not os.path.isfile(path):
            # Optional provider files may legitimately be absent (for example,
            # Kakao candidates before that provider has been collected). Keep
            # the absence in the snapshot identity instead of failing the run.
            digest.update(b"<missing>\0")
            continue
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _existing_versions(runs_dir: str, safe: str) -> List[int]:
    if not os.path.isdir(runs_dir):
        return []
    vs = []
    pat = re.compile(re.escape(safe) + r"__v(\d+)\.json$")
    for fn in os.listdir(runs_dir):
        m = pat.match(fn)
        if m:
            vs.append(int(m.group(1)))
    return sorted(vs)


def _pick_version(runs_dir: str, safe: str, save_mode: str) -> int:
    existing = _existing_versions(runs_dir, safe)
    m = re.fullmatch(r"v(\d+)", save_mode or "")
    if m:  # explicit overwrite of a specific version
        return int(m.group(1))
    return (max(existing) + 1) if existing else 1


def run_submission(*, name: str, script_text: str, lang: str, dataset: str, mode: str,
                   params: Optional[List[str]], save_mode: str, csv_path: str, config_path: str,
                   candidate_paths: List[str], runs_dir: str,
                   candidate_limit: Optional[int] = None,
                   label_relations_path: Optional[str] = None) -> Dict[str, Any]:
    if not (script_text or "").strip():
        raise RunError("no script provided — attach a predict() script before running")
    lang = "python" if lang in ("python", "py", "") else lang

    if params is not None:
        if not all(isinstance(p, str) for p in params):
            raise RunError("params must contain only string signal keys")
        unknown = sorted(set(params) - set(PARAM_SIGNALS))
        if unknown:
            raise RunError("unknown input signal(s): " + ", ".join(unknown))

    cfg = ms.load_config(config_path)
    rows = ms.read_rows(csv_path)
    # Same read-time Reconcile overlay as matchrate so identification scoring
    # sees promoted MapKit names without rewriting the eval CSV.
    rows, _n_ovr = ms.overlay_gt_mapkit_overrides(rows)
    candidates = ms.load_candidates(candidate_paths)
    if candidate_limit is not None and (type(candidate_limit) is not int or candidate_limit < 1 or candidate_limit > 250):
        raise RunError("candidate_limit must be an integer between 1 and 250, or null")
    cases = build_cases(rows, cfg, candidates, dataset or "all", params, candidate_limit)
    if not cases:
        raise RunError(f"no eligible eval cases for scope '{dataset}' "
                       "(need rows with GT, non-Korea, not non_poi)")

    rel_path = label_relations_path or ms.DEFAULT_LABEL_RELATIONS_PATH
    relations = ms.load_label_relations(rel_path)

    suffix = ".py" if lang == "python" else ""
    tmp = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    try:
        tmp.write(script_text)
        tmp.close()
        if lang != "python":
            os.chmod(tmp.name, 0o755)
        preds, duration_ms = _run_subprocess(tmp.name, lang, cases)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    scored = _score(cases, preds, mode or "exact", label_relations=relations)
    metrics = {k: v for k, v in scored.items() if k != "cases"}
    metrics["duration_ms"] = duration_ms
    metrics["runtime"] = _host_runtime_info()
    if relations:
        metrics["label_relations_path"] = rel_path
        metrics["label_relations_n"] = len(relations)

    # --- Retrieval-depth contract (for /retrieval charts) ---
    # ``candidate_limit`` is the exact k used to truncate nearby_candidates
    # before predict(). accuracy_pct is the selection score *at that k only*.
    # Charts must match on candidate_limit == N; they must not interpolate
    # accuracy@N from a different k. null means "no truncation" / unknown k
    # and must not be plotted as any N.
    selected_params = ALL_PARAMS if params is None else list(params)
    used_nearby = "nearby_candidates" in selected_params
    metrics["candidate_limit"] = candidate_limit
    metrics["score_k"] = candidate_limit  # alias: accuracy is for this k
    metrics["accuracy_at_k"] = candidate_limit is not None and used_nearby
    metrics["scoring_note"] = (
        f"strict accuracy with nearby_candidates truncated to k={candidate_limit}"
        if candidate_limit is not None and used_nearby
        else (
            "strict accuracy; nearby list not truncated (candidate_limit=null)"
            if used_nearby
            else "strict accuracy; nearby_candidates not in params"
        )
    )

    safe = _safe_name(name)
    # Display name tracks the stable slug so the UI never shows a one-off
    # free-text label that diverges from the versioned filename.
    display_name = safe
    save_mode = (save_mode or "auto").strip() or "auto"
    if save_mode not in ("auto",) and not re.fullmatch(r"v\d+", save_mode):
        # Unknown modes fall back to auto-increment (never clobber silently).
        save_mode = "auto"
    os.makedirs(runs_dir, exist_ok=True)
    hash_paths = [csv_path, config_path, *candidate_paths]
    if relations and os.path.isfile(rel_path):
        hash_paths.append(rel_path)
    # Reserve version + write under a directory lock so concurrent /api/run
    # (or CLI + UI) cannot pick the same version or leave a partial JSON.
    with file_lock(os.path.join(runs_dir, ".runs")):
        version = _pick_version(runs_dir, safe, save_mode)
        record = {
            "name": display_name,
            "safe_name": safe,
            "version": version,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "scope": dataset or "all",
            "mode": "exact" if mode in ("exact", "raw", "") else "normalized",
            "params": selected_params,
            "candidate_limit": candidate_limit,
            "lang": lang,
            "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
            "evaluation_set_sha256": evaluation_set_sha256(cases),
            "data_snapshot_sha256": data_snapshot_sha256(hash_paths),
            "label_relations_path": rel_path if relations else None,
            "script_text": script_text,
            "metrics": metrics,
            "cases": scored["cases"],
        }
        out_path = os.path.join(runs_dir, f"{safe}__v{version}.json")
        atomic_write_json(out_path, record)

    return {k: v for k, v in record.items() if k not in ("script_text", "cases")} | {
        "metrics": record["metrics"],
        "n_cases": len(scored["cases"]),
    }


def list_runs(runs_dir: str) -> List[Dict[str, Any]]:
    if not os.path.isdir(runs_dir):
        return []
    out = []
    for fn in sorted(os.listdir(runs_dir)):
        if not fn.endswith(".json"):
            continue
        # Skip raw/unscored intermediate snapshots: they carry a duplicate
        # version number with no accuracy and would surface as bogus 0% runs.
        if fn.endswith("__raw.json"):
            continue
        try:
            with open(os.path.join(runs_dir, fn), encoding="utf-8") as f:
                r = json.load(f)
        except Exception:
            continue
        m = r.get("metrics", {})
        stored_hash = r.get("script_sha256")
        stored_evaluation_hash = r.get("evaluation_set_sha256")
        derived_evaluation_hash = (
            evaluation_set_sha256(r.get("cases") or [])
            if not stored_evaluation_hash and r.get("cases") is not None
            else None
        )
        out.append({
            "run_id": f"{r.get('safe_name') or _safe_name(r.get('name') or '')}__v{r.get('version')}",
            "name": r.get("name"),
            "safe_name": r.get("safe_name"),
            "version": r.get("version"),
            "scope": r.get("scope"),
            "mode": r.get("mode"),
            "params": r.get("params", []),
            "candidate_limit": r.get("candidate_limit"),
            # score_k mirrors candidate_limit when present (chart: exact == N only)
            "score_k": (r.get("metrics") or {}).get("score_k", r.get("candidate_limit")),
            "lang": r.get("lang"),
            "script_sha256": stored_hash or (
                hashlib.sha256(str(r["script_text"]).encode("utf-8")).hexdigest()
                if r.get("script_text")
                else None
            ),
            "script_sha256_derived": bool(not stored_hash and r.get("script_text")),
            "evaluation_set_sha256": stored_evaluation_hash or derived_evaluation_hash,
            "evaluation_set_sha256_derived": bool(
                not stored_evaluation_hash and derived_evaluation_hash
            ),
            "data_snapshot_sha256": r.get("data_snapshot_sha256"),
            "created_at": r.get("created_at"),
            "metrics": m,
            "n_eligible": m.get("n_eligible", 0),
            "correct": m.get("correct", 0),
            "correct_canonical": m.get("correct_canonical"),
            "abstained": m.get("abstained", 0),
            "errored": m.get("errored", 0),
            "accuracy_pct": m.get("accuracy_pct", 0),
            "accuracy_canonical_pct": m.get("accuracy_canonical_pct"),
            "match_kind_counts": m.get("match_kind_counts"),
            "label_relations_path": r.get("label_relations_path") or m.get("label_relations_path"),
            "duration_ms": m.get("duration_ms"),
            "latency_ms": m.get("latency_ms"),
            "runtime": m.get("runtime"),
        })
    # Dedupe by (name, version): if two files claim the same identity, keep the
    # scored one (real accuracy) over an unscored/None entry.
    dedup: Dict[Any, Dict[str, Any]] = {}
    for r in out:
        key = (r.get("name"), r.get("version"))
        prev = dedup.get(key)
        if prev is None or (prev.get("accuracy_pct") is None and r.get("accuracy_pct") is not None):
            dedup[key] = r
    out = list(dedup.values())
    out.sort(key=lambda r: (r.get("created_at") or "", r.get("version") or 0), reverse=True)
    return out


def _run_path(runs_dir: str, name: str, version: Any) -> str:
    """Resolve one persisted run by logical identity, never by a client path."""
    if type(version) is not int or version < 1:
        raise RunError("version must be a positive integer")
    return os.path.join(runs_dir, f"{_safe_name(name)}__v{version}.json")


def get_run(runs_dir: str, name: str, version: Any) -> Dict[str, Any]:
    path = _run_path(runs_dir, name, version)
    try:
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
    except FileNotFoundError:
        raise RunError(f"run not found: {_safe_name(name)} v{version}")
    except (OSError, json.JSONDecodeError) as e:
        raise RunError(f"could not read run: {e}")
    # A slug collision must not let a differently named record be managed.
    if run.get("name") != name or run.get("version") != version:
        raise RunError("run identity does not match its stored record")
    # Legacy records predate explicit code hashes.  Derive the identity from
    # their persisted script text instead of presenting the run as unknowable.
    if not run.get("script_sha256") and run.get("script_text"):
        run["script_sha256"] = hashlib.sha256(
            str(run["script_text"]).encode("utf-8")
        ).hexdigest()
        run["script_sha256_derived"] = True
    else:
        run["script_sha256_derived"] = False
    if not run.get("evaluation_set_sha256") and run.get("cases") is not None:
        run["evaluation_set_sha256"] = evaluation_set_sha256(run["cases"])
        run["evaluation_set_sha256_derived"] = True
    else:
        run["evaluation_set_sha256_derived"] = False
    return run


def delete_run(runs_dir: str, name: str, version: Any) -> Dict[str, Any]:
    with file_lock(os.path.join(runs_dir, ".runs")):
        run = get_run(runs_dir, name, version)
        try:
            os.unlink(_run_path(runs_dir, name, version))
        except OSError as e:
            raise RunError(f"could not delete run: {e}")
    return {"name": run.get("name"), "version": version,
            "run_id": f"{run.get('safe_name')}__v{version}"}


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run a predict() submission over the eval set")
    ap.add_argument("script", help="path to a Python script defining predict(case)")
    ap.add_argument("--name", default="cli-run")
    ap.add_argument("--dataset", default="all")
    ap.add_argument("--mode", default="exact", choices=["exact", "raw", "normalized"])
    ap.add_argument("--params", default="", help="comma-separated param keys (default: all)")
    ap.add_argument("--candidate-limit", type=int, default=None)
    ap.add_argument("--runs-dir", default=os.path.join(ms.CANDIDATE_DIR, "runs"))
    args = ap.parse_args()
    with open(args.script, encoding="utf-8") as f:
        script_text = f.read()
    res = run_submission(
        name=args.name, script_text=script_text, lang="python", dataset=args.dataset,
        mode=args.mode, params=([p for p in args.params.split(",") if p] if args.params else None), save_mode="auto",
        csv_path=ms.CSV_PATH, config_path=ms.CONFIG_PATH,
        candidate_paths=ms.default_candidate_files(), runs_dir=args.runs_dir,
        candidate_limit=args.candidate_limit,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
