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
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

import match_score as ms

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_predict_runner.py")
RUN_TIMEOUT_S = 120
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
    slug = NAME_RE.sub("-", (name or "").strip()).strip("-")
    return slug or "algorithm"


def _candidate_names(candidates, provider: str, photo: str, row: Dict[str, str]) -> List[Dict[str, Any]]:
    out = []
    for c in candidates.get((provider, photo), []):
        out.append({
            "name": c.get("name") or "",
            "rank": c.get("rank"),
            "distance_m": c.get("distance_m"),
        })
    if not out:
        # Candidate JSONL is a lossy top-3 preview; fall back to the nearest POI
        # the MapKit probe already stored per row so a row with a real nearest
        # candidate is not treated as "no candidates".
        top1 = (row.get("app_nearby_top1") or "").strip()
        if top1:
            # app_nearby_top1 is stored as "Name@<dist>m"; keep only the name.
            name, sep, dist_s = top1.rpartition("@")
            name = (name if sep else top1).strip()
            dist = (row.get("app_poi_dist_m") or "").strip() or dist_s.replace("m", "").strip()
            if name:
                out.append({"name": name, "rank": 1,
                            "distance_m": ms._num_or_none(dist) if dist else None})
    return out


def build_cases(rows, cfg, candidates, dataset: str, params: Optional[List[str]],
                candidate_limit: Optional[int] = None) -> List[Dict[str, Any]]:
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
        provider = ms.provider_for_row(row, cfg)
        gt, gt_status = ms.gt_resolution(row, provider)
        tier = ms.confidence_tier(row, cfg)
        # Eligibility exactly mirrors match_score.evaluate: provider sentinels
        # and missing provider-canonical GT are holdouts, never answer labels.
        if (provider == "kakao_local" or tier == "non_poi"
                or gt_status != "canonical"):
            continue
        photo = (row.get("photo") or "").strip()

        full = {
            "photo": photo,
            "photo_url": (row.get("photo_url") or "").strip(),
            "lat": (row.get("capture_lat") or "").strip(),
            "lon": (row.get("capture_lon") or "").strip(),
            "timestamp": (row.get("timestamp") or "").strip(),
            "ocr_text": (row.get("caption_ondevice") or "").strip(),
            "vlm_caption": "",  # not extracted yet
            "nearby_candidates": _candidate_names(candidates, provider, photo, row)[:candidate_limit],
            "geocode": {
                "city": (row.get("city") or "").strip(),
                "country": (row.get("country") or "").strip(),
                "address": (row.get("address") or "").strip(),
            },

        }
        public = {k: v for k, v in full.items() if k in wanted}
        public["photo"] = photo  # always present as a reference id
        cases.append({"input": public, "_gt": gt, "_dataset": ds, "_photo": photo})
    return cases


def _run_subprocess(script_path: str, lang: str, cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if lang == "python":
        cmd = [sys.executable, RUNNER, script_path]
    else:
        cmd = [script_path]  # non-python: script speaks the JSONL protocol itself
    stdin_data = "".join(json.dumps(c["input"], ensure_ascii=False) + "\n" for c in cases)
    try:
        proc = subprocess.run(cmd, input=stdin_data, capture_output=True,
                              text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RunError(f"submission timed out after {RUN_TIMEOUT_S}s")
    except (PermissionError, OSError) as e:
        raise RunError(f"could not execute submission: {e}")
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
            preds.append({"prediction": "", "error": "non-JSON line from submission"})
    return preds


def _score(cases, preds, mode: str) -> Dict[str, Any]:
    matcher = ms.exact_equal if mode in ("exact", "raw") else ms.normalized_equal
    n = len(cases)
    correct = errored = abstained = 0
    by_dataset: Dict[str, Dict[str, int]] = {}
    scored_cases: List[Dict[str, Any]] = []
    for i, c in enumerate(cases):
        p = preds[i] if i < len(preds) else {"prediction": "", "error": "no output for case"}
        pred = (p.get("prediction") or "").strip()
        err = p.get("error")
        gt = c["_gt"]
        is_correct = bool(pred) and matcher(gt, pred)
        # An execution/protocol error is distinct from a blank prediction.
        # Keep outcome counts mutually exclusive for summaries and charts.
        if err:
            errored += 1
        elif not pred:
            abstained += 1
        if is_correct:
            correct += 1
        d = by_dataset.setdefault(c["_dataset"], {"n": 0, "correct": 0})
        d["n"] += 1
        d["correct"] += 1 if is_correct else 0
        scored_cases.append({
            "dataset": c["_dataset"], "photo": c["_photo"], "gt": gt,
            "prediction": pred, "reason": p.get("reason"),
            "correct": is_correct, "error": err,
        })
    accuracy = (correct / n) if n else 0.0
    return {
        "n_eligible": n,
        "correct": correct,
        "abstained": abstained,
        "errored": errored,
        "accuracy": accuracy,
        "accuracy_pct": round(100 * accuracy),
        "by_dataset": {k: {**v, "accuracy": (v["correct"] / v["n"] if v["n"] else 0.0)}
                       for k, v in sorted(by_dataset.items())},
        "cases": scored_cases,
    }


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
                   candidate_limit: Optional[int] = None) -> Dict[str, Any]:
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
    candidates = ms.load_candidates(candidate_paths)
    if candidate_limit is not None and (type(candidate_limit) is not int or candidate_limit < 1 or candidate_limit > 250):
        raise RunError("candidate_limit must be an integer between 1 and 250, or null")
    cases = build_cases(rows, cfg, candidates, dataset or "all", params, candidate_limit)
    if not cases:
        raise RunError(f"no eligible eval cases for scope '{dataset}' "
                       "(need rows with GT, non-Korea, not non_poi)")

    suffix = ".py" if lang == "python" else ""
    tmp = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    try:
        tmp.write(script_text)
        tmp.close()
        if lang != "python":
            os.chmod(tmp.name, 0o755)
        preds = _run_subprocess(tmp.name, lang, cases)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    scored = _score(cases, preds, mode or "exact")

    safe = _safe_name(name)
    version = _pick_version(runs_dir, safe, save_mode)
    os.makedirs(runs_dir, exist_ok=True)
    record = {
        "name": (name or safe).strip(),
        "safe_name": safe,
        "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": dataset or "all",
        "mode": "exact" if mode in ("exact", "raw", "") else "normalized",
        "params": ALL_PARAMS if params is None else params,
        "candidate_limit": candidate_limit,
        "lang": lang,
        "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        "script_text": script_text,
        "metrics": {k: v for k, v in scored.items() if k != "cases"},
        "cases": scored["cases"],
    }
    with open(os.path.join(runs_dir, f"{safe}__v{version}.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

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
        try:
            with open(os.path.join(runs_dir, fn), encoding="utf-8") as f:
                r = json.load(f)
        except Exception:
            continue
        m = r.get("metrics", {})
        stored_hash = r.get("script_sha256")
        out.append({
            "run_id": f"{r.get('safe_name') or _safe_name(r.get('name') or '')}__v{r.get('version')}",
            "name": r.get("name"),
            "safe_name": r.get("safe_name"),
            "version": r.get("version"),
            "scope": r.get("scope"),
            "mode": r.get("mode"),
            "params": r.get("params", []),
            "candidate_limit": r.get("candidate_limit"),
            "lang": r.get("lang"),
            "script_sha256": stored_hash or (
                hashlib.sha256(str(r["script_text"]).encode("utf-8")).hexdigest()
                if r.get("script_text")
                else None
            ),
            "script_sha256_derived": bool(not stored_hash and r.get("script_text")),
            "created_at": r.get("created_at"),
            "metrics": m,
            "n_eligible": m.get("n_eligible", 0),
            "correct": m.get("correct", 0),
            "abstained": m.get("abstained", 0),
            "errored": m.get("errored", 0),
            "accuracy_pct": m.get("accuracy_pct", 0),
        })
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
    return run


def delete_run(runs_dir: str, name: str, version: Any) -> Dict[str, Any]:
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
        candidate_paths=ms.DEFAULT_CANDIDATE_FILES, runs_dir=args.runs_dir,
        candidate_limit=args.candidate_limit,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
