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
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

import match_score as ms
from file_ops import atomic_write_json, file_lock

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
RUNNER = os.path.join(_TOOLS_DIR, "_predict_runner.py")
# examples/ holds multi-module *sources* for development. The predict harness
# never puts this directory on PYTHONPATH — submissions must be self-contained
# (or a future package laid out entirely under the submission temp dir).
# stdlib + installed site-packages remain available.
EXAMPLES_DIR = os.path.join(_REPO_ROOT, "examples")
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
        # Dataset id is not ground truth; image/VLM baselines need it to resolve
        # photo files under sources[dataset].photo_dir.
        public["dataset"] = ds
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


def _python_has_torch(py_path: str) -> bool:
    """True if *py_path* can import torch (venv site-packages or probe).

    Prefer a cheap filesystem check for venvs; fall back to a short subprocess
    for non-venv interpreters (or broken layout).
    """
    if not py_path or not os.path.isfile(py_path):
        return False
    # Standard venv layout: <venv>/bin/python → <venv>/lib/pythonX.Y/site-packages
    venv_root = os.path.dirname(os.path.dirname(os.path.abspath(py_path)))
    try:
        import glob as _glob
        if _glob.glob(os.path.join(venv_root, "lib", "python*", "site-packages", "torch", "__init__.py")):
            return True
        # Also homebrew / framework installs sometimes put torch next to the binary.
        if _glob.glob(os.path.join(venv_root, "lib", "python*", "site-packages", "torch", "__init__.py")):
            return True
    except Exception:
        pass
    try:
        probe = subprocess.run(
            [py_path, "-c", "import torch"],
            capture_output=True,
            timeout=20,
            env={**os.environ, "PYTHONNOUSERSITE": "1"},
        )
        return probe.returncode == 0
    except Exception:
        return False


def _fastvlm_python_candidates() -> List[str]:
    """Ordered interpreter paths that might host FastVLM (torch+MPS)."""
    try:
        data_root = ms.resolve_data_root()
    except Exception:
        data_root = os.path.join(_REPO_ROOT, "poi-data")
    explicit = (os.environ.get("POI_PREDICT_PYTHON") or "").strip()
    cands: List[str] = []
    if explicit:
        cands.append(explicit)
    for root in (data_root, os.path.join(_REPO_ROOT, "poi-data")):
        cands.append(os.path.join(root, "tools", "fastvlm-venv", "bin", "python"))
        cands.append(os.path.join(root, "tools", "fastvlm-venv", "bin", "python3"))
    cands.append(sys.executable)
    # De-dupe while preserving order.
    seen = set()
    out: List[str] = []
    for c in cands:
        if not c:
            continue
        key = os.path.abspath(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _default_predict_python() -> str:
    """Interpreter for predict subprocesses.

    Preference:
      1. ``POI_PREDICT_PYTHON`` if set, executable, and (when possible) has torch
      2. ``$POI_DATA_DIR/tools/fastvlm-venv/bin/python`` with torch installed
      3. repo ``poi-data/tools/fastvlm-venv`` with torch
      4. ``sys.executable`` (server Python) — last resort; live VLM will fail-loud
         if torch is missing

    Important: the venv must live under **this checkout's** data root (or be
    pointed at via ``POI_PREDICT_PYTHON``). A server started from another clone
    will not magically find a sibling checkout's venv.
    """
    cands = _fastvlm_python_candidates()
    executable = [
        c for c in cands
        if os.path.isfile(c) and os.access(c, os.X_OK)
    ]
    if not executable:
        return sys.executable

    # Prefer an interpreter that actually has torch (real FastVLM host).
    for c in executable:
        if _python_has_torch(c):
            return c

    # Explicit POI_PREDICT_PYTHON always wins as a path even without torch so
    # misconfiguration is visible; otherwise first existing path / system.
    explicit = (os.environ.get("POI_PREDICT_PYTHON") or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit
    return executable[0]


def _predict_env(submission_dir: Optional[str] = None) -> Dict[str, str]:
    """Environment for the predict subprocess.

    Import policy (also enforced in ``_predict_runner`` via ``sys.path``):

    * **Allowed:** stdlib + installed site-packages (real packages such as
      ``json``, and any pip-installed dependency present on the host).
    * **Allowed:** modules living *inside* the submission directory only.
    * **Blocked:** repo ``examples/``, ``tools/``, and the checkout root —
      bare ``import selector_list_fit`` must not resolve to workspace files.

    Parent ``PYTHONPATH`` entries that point at those blocked locations are
    stripped so a developer shell cannot accidentally re-open the hole.

    Also injects ``POI_DATA_DIR`` (when unset) so live image/VLM code can
    resolve photo paths and model checkpoints under the active data root.
    """
    env = os.environ.copy()
    blocked = {
        os.path.abspath(EXAMPLES_DIR),
        os.path.abspath(_TOOLS_DIR),
        os.path.abspath(_REPO_ROOT),
    }
    kept: List[str] = []
    if submission_dir:
        kept.append(os.path.abspath(submission_dir))
    for part in (env.get("PYTHONPATH") or "").split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        abs_part = os.path.abspath(part)
        if abs_part in blocked:
            continue
        if abs_part not in kept:
            kept.append(part)
    if kept:
        env["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        env.pop("PYTHONPATH", None)
    # Avoid user-site surprises in weird envs; keep system site-packages.
    env.setdefault("PYTHONNOUSERSITE", "1")
    if not (env.get("POI_DATA_DIR") or "").strip():
        try:
            env["POI_DATA_DIR"] = ms.resolve_data_root()
        except Exception:
            env["POI_DATA_DIR"] = os.path.join(_REPO_ROOT, "poi-data")
    return env


def _default_label_relations_path(csv_path: str,
                                  explicit: Optional[str] = None) -> str:
    """Prefer the sidecar next to the eval CSV this run is scoring against.

    Falls back to the active data-root default. Using the CSV's directory keeps
    UI runs consistent even when match_score was imported before poi-data existed.
    """
    if explicit:
        return explicit
    if csv_path:
        beside = os.path.join(os.path.dirname(os.path.abspath(csv_path)),
                              "eval_label_relations.v1.jsonl")
        if os.path.isfile(beside):
            return beside
    return ms.default_label_relations_path()


def _raise_from_runner_failure(msg: str) -> None:
    lower = (msg or "").lower()
    if "import preflight failed" in lower:
        raise RunError("submission import preflight failed: " + msg)
    if "submission failed on case" in lower:
        raise RunError(msg)
    if "syntax error" in lower:
        raise RunError("submission failed to load: " + msg)
    raise RunError("submission failed to load: " + msg)


def _run_subprocess(
    script_path: str,
    lang: str,
    cases: List[Dict[str, Any]],
    on_pred: Optional[Callable[[int, Dict[str, Any]], None]] = None,
):
    """Run the submission and return (preds, duration_ms).

    Streams each stdout JSONL line as soon as it arrives so callers can score
    and persist partial results for the Results UI. ``on_pred(index, pred)`` is
    invoked after each successful line (0-based).

    duration_ms is wall-clock for the whole subprocess, including process start.
    Per-case latency_ms (when present on each pred) is predict-call wall time only.
    """
    if lang == "python":
        cmd = [_default_predict_python(), RUNNER, script_path]
    else:
        cmd = [script_path]  # non-python: script speaks the JSONL protocol itself
    stdin_data = "".join(json.dumps(c["input"], ensure_ascii=False) + "\n" for c in cases)
    submission_dir = os.path.dirname(os.path.abspath(script_path))
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_predict_env(submission_dir) if lang == "python" else None,
            cwd=submission_dir if lang == "python" else None,
        )
    except (PermissionError, OSError) as e:
        raise RunError(f"could not execute submission: {e}")

    preds: List[Dict[str, Any]] = []
    stderr_chunks: List[str] = []
    try:
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        except BrokenPipeError:
            pass

        deadline = (t0 + RUN_TIMEOUT_S) if RUN_TIMEOUT_S else None
        while True:
            if deadline is not None and time.perf_counter() > deadline:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                raise RunError(f"submission timed out after {RUN_TIMEOUT_S:g}s")
            line = proc.stdout.readline()
            if line == "":
                if proc.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                pred = json.loads(line)
            except json.JSONDecodeError:
                proc.kill()
                raise RunError(
                    "submission produced non-JSON output; refusing to score partial results"
                )
            if not isinstance(pred, dict):
                proc.kill()
                raise RunError(
                    "submission produced non-object JSON; refusing to score partial results"
                )
            idx = len(preds)
            preds.append(pred)
            if on_pred is not None:
                on_pred(idx, pred)

        proc.wait(timeout=1 if deadline is None else max(1.0, deadline - time.perf_counter()))
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RunError(f"submission timed out after {RUN_TIMEOUT_S:g}s")
    finally:
        if proc.stderr is not None:
            try:
                stderr_chunks.append(proc.stderr.read() or "")
            except Exception:
                pass
            try:
                proc.stderr.close()
            except Exception:
                pass
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    stderr_text = "".join(stderr_chunks)
    if proc.returncode not in (0, None):
        err_lines = stderr_text.strip().splitlines()
        # Runner may put the fatal message on stderr; partial preds already on_pred.
        msg = err_lines[-1] if err_lines else f"exit {proc.returncode}"
        _raise_from_runner_failure(msg)

    errored = [
        (i, p.get("error"))
        for i, p in enumerate(preds)
        if isinstance(p, dict) and p.get("error")
    ]
    if errored:
        i, err = errored[0]
        raise RunError(
            f"submission failed on case {i}: {err} "
            f"({len(errored)} case error(s) total; refusing to score)"
        )
    if len(preds) != len(cases):
        raise RunError(
            f"submission returned {len(preds)} predictions for {len(cases)} cases; "
            "refusing to score partial results"
        )
    return preds, duration_ms


def _score_one_case(
    case: Dict[str, Any],
    pred_obj: Dict[str, Any],
    mode: str,
    label_relations: Optional[Dict],
) -> Dict[str, Any]:
    """Score a single predict() result against its harness case."""
    pred = (pred_obj.get("prediction") or "").strip()
    err = pred_obj.get("error")
    gt = case["_gt"]
    provider = case.get("_provider") or "mapkit"
    match = ms.match_prediction(
        gt, pred, dataset=case["_dataset"], photo=case["_photo"],
        provider=provider, mode=mode, relations=label_relations or {},
    )
    is_correct = match["correct_strict"]
    is_canonical = match["correct_canonical"]
    match_kind = match["match_kind"]
    if err:
        match_kind = "error"
    elif not pred:
        match_kind = "abstain"
    lat = pred_obj.get("latency_ms")
    try:
        latency_ms = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        latency_ms = None
    return {
        "dataset": case["_dataset"],
        "photo": case["_photo"],
        "gt": gt,
        "prediction": pred,
        "reason": pred_obj.get("reason"),
        "correct": is_correct,
        "correct_canonical": is_canonical,
        "match_kind": match_kind,
        "matched_label": match.get("matched_label") or "",
        "error": err,
        "latency_ms": latency_ms,
    }


def _metrics_from_scored(
    scored_cases: List[Dict[str, Any]],
    *,
    n_eligible_total: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate metrics from zero or more scored cases.

    While a live run is in progress, ``n_eligible`` is the full cohort size
    (``n_eligible_total``) so progress is ``len(cases) / n_eligible``. Accuracy
    percentages are over **completed** cases only until the run finishes.
    """
    completed = len(scored_cases)
    n_report = n_eligible_total if n_eligible_total is not None else completed
    correct = sum(1 for c in scored_cases if c.get("correct"))
    correct_canonical = sum(1 for c in scored_cases if c.get("correct_canonical"))
    errored = sum(1 for c in scored_cases if c.get("match_kind") == "error" or c.get("error"))
    abstained = sum(1 for c in scored_cases if c.get("match_kind") == "abstain")
    kind_counts: Dict[str, int] = {}
    by_dataset: Dict[str, Dict[str, int]] = {}
    for c in scored_cases:
        mk = c.get("match_kind") or "wrong"
        kind_counts[mk] = kind_counts.get(mk, 0) + 1
        d = by_dataset.setdefault(
            c.get("dataset") or "",
            {"n": 0, "correct": 0, "correct_canonical": 0},
        )
        d["n"] += 1
        d["correct"] += 1 if c.get("correct") else 0
        d["correct_canonical"] += 1 if c.get("correct_canonical") else 0
    # Live accuracy is over finished cases so the tile moves as results arrive.
    denom = completed if completed else 0
    accuracy = (correct / denom) if denom else 0.0
    accuracy_canonical = (correct_canonical / denom) if denom else 0.0
    latencies = [
        c["latency_ms"] for c in scored_cases
        if isinstance(c.get("latency_ms"), (int, float))
    ]
    return {
        "n_eligible": n_report,
        "n_completed": completed,
        "correct": correct,
        "correct_canonical": correct_canonical,
        "abstained": abstained,
        "errored": errored,
        "accuracy": accuracy,
        "accuracy_pct": round(100 * accuracy) if denom else 0,
        "accuracy_canonical": accuracy_canonical,
        "accuracy_canonical_pct": round(100 * accuracy_canonical) if denom else 0,
        "match_kind_counts": dict(sorted(kind_counts.items())),
        "by_dataset": {
            k: {
                **v,
                "accuracy": (v["correct"] / v["n"] if v["n"] else 0.0),
                "accuracy_canonical": (
                    v["correct_canonical"] / v["n"] if v["n"] else 0.0
                ),
            }
            for k, v in sorted(by_dataset.items())
        },
        "latency_ms": _latency_summary(latencies),
        "cases": scored_cases,
    }


def _score(cases, preds, mode: str,
           label_relations: Optional[Dict] = None) -> Dict[str, Any]:
    """Score predictions.

    Primary ``correct`` / ``accuracy`` remain **strict** (canonical GT string
    only) so historical leaderboards stay comparable.

    When ``label_relations`` is provided (reviewed alias sidecar), also emit:
      - correct_canonical / accuracy_canonical  (strict ∪ accepted_aliases)
      - match_kind breakdown (exact, alias, related, wrong, abstain)
    """
    if label_relations is None:
        label_relations = ms.load_label_relations()

    scored_cases: List[Dict[str, Any]] = []
    for i, c in enumerate(cases):
        p = preds[i] if i < len(preds) else {"prediction": "", "error": "no output for case"}
        scored_cases.append(_score_one_case(c, p, mode, label_relations))
    return _metrics_from_scored(scored_cases)


def live_runs_dir(runs_dir: str) -> str:
    return os.path.join(runs_dir, "live")


def live_run_path(runs_dir: str, job_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", (job_id or "").strip()) or "job"
    return os.path.join(live_runs_dir(runs_dir), f"{safe}.json")


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


def prepare_submission(*, name: str, script_text: str, lang: str, dataset: str, mode: str,
                       params: Optional[List[str]], save_mode: str, csv_path: str,
                       config_path: str, candidate_paths: List[str], runs_dir: str,
                       candidate_limit: Optional[int] = None,
                       label_relations_path: Optional[str] = None,
                       job_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate inputs, build cases, reserve a version, write a live run stub.

    Returns a context dict consumed by ``execute_submission``. Used so the
    HTTP handler can respond with name/version before the long predict loop.
    """
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
    rows, _n_ovr = ms.overlay_gt_mapkit_overrides(rows)
    candidates = ms.load_candidates(candidate_paths)
    if candidate_limit is not None and (type(candidate_limit) is not int or candidate_limit < 1 or candidate_limit > 250):
        raise RunError("candidate_limit must be an integer between 1 and 250, or null")
    cases = build_cases(rows, cfg, candidates, dataset or "all", params, candidate_limit)
    if not cases:
        raise RunError(f"no eligible eval cases for scope '{dataset}' "
                       "(need rows with GT, non-Korea, not non_poi)")

    rel_path = _default_label_relations_path(csv_path, label_relations_path)
    relations = ms.load_label_relations(rel_path)
    selected_params = ALL_PARAMS if params is None else list(params)
    safe = _safe_name(name)
    display_name = safe
    save_mode = (save_mode or "auto").strip() or "auto"
    if save_mode not in ("auto",) and not re.fullmatch(r"v\d+", save_mode):
        save_mode = "auto"

    os.makedirs(runs_dir, exist_ok=True)
    os.makedirs(live_runs_dir(runs_dir), exist_ok=True)
    hash_paths = [csv_path, config_path, *candidate_paths]
    if relations and os.path.isfile(rel_path):
        hash_paths.append(rel_path)

    job = (job_id or "").strip() or hashlib.sha256(
        f"{safe}:{time.time()}".encode("utf-8")
    ).hexdigest()[:12]
    live_path = live_run_path(runs_dir, job)

    with file_lock(os.path.join(runs_dir, ".runs")):
        version = _pick_version(runs_dir, safe, save_mode)
        # Also avoid colliding with another live run of the same identity.
        for fn in os.listdir(live_runs_dir(runs_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(live_runs_dir(runs_dir), fn), encoding="utf-8") as f:
                    other = json.load(f)
            except Exception:
                continue
            if other.get("safe_name") == safe and other.get("version") == version:
                version = max(version, int(other.get("version") or 0)) + 1

        empty_metrics = _metrics_from_scored([], n_eligible_total=len(cases))
        empty_metrics["duration_ms"] = None
        empty_metrics["runtime"] = _host_runtime_info()
        empty_metrics["candidate_limit"] = candidate_limit
        empty_metrics["score_k"] = candidate_limit
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
            "metrics": empty_metrics,
            "cases": [],
            "status": "running",
            "job_id": job,
            "progress": {"done": 0, "total": len(cases)},
        }
        atomic_write_json(live_path, record)

    return {
        "job_id": job,
        "live_path": live_path,
        "runs_dir": runs_dir,
        "script_text": script_text,
        "lang": lang,
        "cases": cases,
        "relations": relations,
        "rel_path": rel_path,
        "mode": record["mode"],
        "record_base": {
            k: v for k, v in record.items()
            if k not in ("metrics", "cases", "status", "progress")
        },
        "selected_params": selected_params,
        "candidate_limit": candidate_limit,
        "name": display_name,
        "safe_name": safe,
        "version": version,
        "n_eligible": len(cases),
    }


def execute_submission(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run predict over prepared cases, streaming scored cases into the live file."""
    script_text = ctx["script_text"]
    lang = ctx["lang"]
    cases: List[Dict[str, Any]] = ctx["cases"]
    relations = ctx["relations"]
    rel_path = ctx["rel_path"]
    mode = ctx["mode"]
    live_path = ctx["live_path"]
    runs_dir = ctx["runs_dir"]
    safe = ctx["safe_name"]
    version = ctx["version"]
    candidate_limit = ctx["candidate_limit"]
    selected_params = ctx["selected_params"]
    record_base = ctx["record_base"]

    scored_cases: List[Dict[str, Any]] = []
    n_total = len(cases)
    t_wall0 = time.perf_counter()

    def _write_live(*, status: str = "running", error: Optional[str] = None,
                    duration_ms: Optional[float] = None) -> Dict[str, Any]:
        metrics = _metrics_from_scored(scored_cases, n_eligible_total=n_total)
        metrics["duration_ms"] = duration_ms
        metrics["runtime"] = _host_runtime_info()
        if relations:
            metrics["label_relations_path"] = rel_path
            metrics["label_relations_n"] = len(relations)
        used_nearby = "nearby_candidates" in selected_params
        metrics["candidate_limit"] = candidate_limit
        metrics["score_k"] = candidate_limit
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
        last = scored_cases[-1] if scored_cases else None
        progress = {
            "done": len(scored_cases),
            "total": n_total,
            "last_photo": (last or {}).get("photo"),
            "last_dataset": (last or {}).get("dataset"),
            "last_correct": (last or {}).get("correct"),
            "last_match_kind": (last or {}).get("match_kind"),
        }
        record = {
            **record_base,
            "metrics": metrics,
            "cases": list(scored_cases),
            "status": status,
            "job_id": ctx["job_id"],
            "progress": progress,
        }
        if error:
            record["error"] = error
        atomic_write_json(live_path, record)
        return record

    def on_pred(idx: int, pred: Dict[str, Any]) -> None:
        if idx < 0 or idx >= n_total:
            return
        scored_cases.append(
            _score_one_case(cases[idx], pred, mode, relations)
        )
        # Throttle disk a bit only if extremely fast; usually case-level is fine.
        _write_live(status="running")

    tmp_dir = tempfile.mkdtemp(prefix="poi-submit-")
    script_path = os.path.join(
        tmp_dir, "predict.py" if lang == "python" else "predict"
    )
    try:
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(script_text)
        if lang != "python":
            os.chmod(script_path, 0o755)
        _write_live(status="running")
        try:
            _preds, duration_ms = _run_subprocess(
                script_path, lang, cases, on_pred=on_pred,
            )
        except RunError as e:
            duration_ms = round((time.perf_counter() - t_wall0) * 1000.0, 3)
            _write_live(status="failed", error=str(e), duration_ms=duration_ms)
            raise
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Final metrics use completed==eligible (full cohort).
    final_metrics = _metrics_from_scored(scored_cases)
    final_metrics["duration_ms"] = duration_ms
    final_metrics["runtime"] = _host_runtime_info()
    if relations:
        final_metrics["label_relations_path"] = rel_path
        final_metrics["label_relations_n"] = len(relations)
    used_nearby = "nearby_candidates" in selected_params
    final_metrics["candidate_limit"] = candidate_limit
    final_metrics["score_k"] = candidate_limit
    final_metrics["accuracy_at_k"] = candidate_limit is not None and used_nearby
    final_metrics["scoring_note"] = (
        f"strict accuracy with nearby_candidates truncated to k={candidate_limit}"
        if candidate_limit is not None and used_nearby
        else (
            "strict accuracy; nearby list not truncated (candidate_limit=null)"
            if used_nearby
            else "strict accuracy; nearby_candidates not in params"
        )
    )
    final_metrics["n_completed"] = len(scored_cases)

    record = {
        **record_base,
        "metrics": final_metrics,
        "cases": scored_cases,
        "status": "done",
        "job_id": ctx["job_id"],
        "progress": {"done": len(scored_cases), "total": n_total},
    }
    out_path = os.path.join(runs_dir, f"{safe}__v{version}.json")
    with file_lock(os.path.join(runs_dir, ".runs")):
        atomic_write_json(out_path, record)
        try:
            if os.path.isfile(live_path):
                os.unlink(live_path)
        except OSError:
            pass

    return {k: v for k, v in record.items() if k not in ("script_text", "cases")} | {
        "metrics": record["metrics"],
        "n_cases": len(scored_cases),
        "status": "done",
    }


def run_submission(*, name: str, script_text: str, lang: str, dataset: str, mode: str,
                   params: Optional[List[str]], save_mode: str, csv_path: str, config_path: str,
                   candidate_paths: List[str], runs_dir: str,
                   candidate_limit: Optional[int] = None,
                   label_relations_path: Optional[str] = None,
                   job_id: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous prepare + execute (CLI and tests)."""
    ctx = prepare_submission(
        name=name, script_text=script_text, lang=lang, dataset=dataset, mode=mode,
        params=params, save_mode=save_mode, csv_path=csv_path, config_path=config_path,
        candidate_paths=candidate_paths, runs_dir=runs_dir,
        candidate_limit=candidate_limit, label_relations_path=label_relations_path,
        job_id=job_id,
    )
    return execute_submission(ctx)


def _summarize_run_record(r: Dict[str, Any]) -> Dict[str, Any]:
    m = r.get("metrics", {}) or {}
    stored_hash = r.get("script_sha256")
    stored_evaluation_hash = r.get("evaluation_set_sha256")
    derived_evaluation_hash = (
        evaluation_set_sha256(r.get("cases") or [])
        if not stored_evaluation_hash and r.get("cases") is not None
        else None
    )
    has_script = bool(str(r.get("script_text") or "").strip())
    status = r.get("status") or "done"
    progress = r.get("progress") or {}
    return {
        "run_id": f"{r.get('safe_name') or _safe_name(r.get('name') or '')}__v{r.get('version')}",
        "name": r.get("name"),
        "safe_name": r.get("safe_name"),
        "version": r.get("version"),
        "scope": r.get("scope"),
        "mode": r.get("mode"),
        "params": r.get("params", []),
        "candidate_limit": r.get("candidate_limit"),
        "score_k": m.get("score_k", r.get("candidate_limit")),
        "lang": r.get("lang"),
        "has_script": has_script,
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
        "n_completed": m.get("n_completed", len(r.get("cases") or [])),
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
        "status": status,
        "job_id": r.get("job_id"),
        "progress": progress,
        "error": r.get("error"),
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
        if not r.get("status"):
            r["status"] = "done"
        out.append(_summarize_run_record(r))

    live_dir = live_runs_dir(runs_dir)
    if os.path.isdir(live_dir):
        for fn in sorted(os.listdir(live_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(live_dir, fn), encoding="utf-8") as f:
                    r = json.load(f)
            except Exception:
                continue
            if not r.get("status"):
                r["status"] = "running"
            out.append(_summarize_run_record(r))

    # Dedupe by (name, version): prefer done over live, scored over empty.
    dedup: Dict[Any, Dict[str, Any]] = {}
    status_rank = {"done": 3, "failed": 2, "running": 1}
    for r in out:
        key = (r.get("name"), r.get("version"))
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = r
            continue
        pr = status_rank.get(prev.get("status") or "done", 0)
        nr = status_rank.get(r.get("status") or "done", 0)
        if nr > pr:
            dedup[key] = r
        elif nr == pr and (prev.get("n_completed") or 0) < (r.get("n_completed") or 0):
            dedup[key] = r
    out = list(dedup.values())
    out.sort(key=lambda r: (r.get("created_at") or "", r.get("version") or 0), reverse=True)
    return out


def _run_path(runs_dir: str, name: str, version: Any) -> str:
    """Resolve one persisted run by logical identity, never by a client path."""
    if type(version) is not int or version < 1:
        raise RunError("version must be a positive integer")
    return os.path.join(runs_dir, f"{_safe_name(name)}__v{version}.json")


def _find_live_run(runs_dir: str, name: str, version: Any) -> Optional[Dict[str, Any]]:
    live_dir = live_runs_dir(runs_dir)
    if not os.path.isdir(live_dir):
        return None
    for fn in os.listdir(live_dir):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(live_dir, fn)
        try:
            with open(path, encoding="utf-8") as f:
                run = json.load(f)
        except Exception:
            continue
        if run.get("name") == name and run.get("version") == version:
            return run
    return None


def get_run(runs_dir: str, name: str, version: Any) -> Dict[str, Any]:
    path = _run_path(runs_dir, name, version)
    run = None
    try:
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
        if not run.get("status"):
            run["status"] = "done"
    except FileNotFoundError:
        run = _find_live_run(runs_dir, name, version)
        if run is None:
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
    run["has_script"] = bool(str(run.get("script_text") or "").strip())
    return run


def delete_run(runs_dir: str, name: str, version: Any) -> Dict[str, Any]:
    with file_lock(os.path.join(runs_dir, ".runs")):
        run = get_run(runs_dir, name, version)
        path = _run_path(runs_dir, name, version)
        removed = False
        if os.path.isfile(path):
            try:
                os.unlink(path)
                removed = True
            except OSError as e:
                raise RunError(f"could not delete run: {e}")
        live_dir = live_runs_dir(runs_dir)
        if os.path.isdir(live_dir):
            for fn in os.listdir(live_dir):
                if not fn.endswith(".json"):
                    continue
                lp = os.path.join(live_dir, fn)
                try:
                    with open(lp, encoding="utf-8") as f:
                        other = json.load(f)
                except Exception:
                    continue
                if other.get("name") == name and other.get("version") == version:
                    try:
                        os.unlink(lp)
                        removed = True
                    except OSError as e:
                        raise RunError(f"could not delete live run: {e}")
        if not removed:
            raise RunError(f"run not found: {_safe_name(name)} v{version}")
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
