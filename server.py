import http.server, socketserver, functools, json, csv, os, sys, tempfile, urllib.parse
import threading, subprocess, uuid, time, math, shutil, queue, statistics
from collections import Counter, defaultdict
from pathlib import Path

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_DIR, "tools"))
from validate_upload_package import validate_zip, ValidationError
from match_score import (
    evaluate as evaluate_matchrate,
    load_candidates as load_match_candidates,
    read_rows as read_match_rows,
    provider_for_row,
    gt_resolution,
)
from run_algorithm import run_submission, list_runs, get_run, delete_run, RunError
from gt_classify_common import read_csv as gc_read_csv, write_csv as gc_write_csv, backup_csv as gc_backup_csv
import run_algorithm as algorithm
import match_score as match_score

# Data root. POI_DATA_DIR is the explicit override. For an ordinary checkout,
# prefer a repository-local poi-data bundle when it contains the reconciled CSV;
# otherwise retain the legacy repository-root layout.
_repo_data_dir = os.path.join(REPO_DIR, "poi-data")
DIRECTORY = os.environ.get("POI_DATA_DIR") or (
    _repo_data_dir if os.path.isfile(os.path.join(_repo_data_dir, "eval_set_reconciled.csv")) else REPO_DIR
)
PORT = int(os.environ.get("POI_PORT", "8420"))
CSV_PATH = os.path.join(DIRECTORY, "eval_set_reconciled.csv")
# Config is part of the tool: prefer a copy shipped alongside the data, else the
# tracked repo copy, so the server still boots before any dataset is dropped in.
DATA_CONFIG_PATH = os.path.join(DIRECTORY, "dashboard_config.json")
REPO_CONFIG_PATH = os.path.join(REPO_DIR, "dashboard_config.json")
# Reads may fall back to the tracked template so a fresh store can boot. Writes
# must always target DATA_CONFIG_PATH; repository configuration is read-only.


def config_read_path():
    """Current effective config; ingestion may create the data copy at runtime."""
    return DATA_CONFIG_PATH if os.path.exists(DATA_CONFIG_PATH) else REPO_CONFIG_PATH
MATCH_CANDIDATE_PATHS = [
    match_score.active_mapkit_candidate_file(DIRECTORY),
    os.path.join(DIRECTORY, "generated", "kakao_local_candidates.jsonl"),
]
RUNS_DIR = os.path.join(DIRECTORY, "generated", "runs")


def _parse_source_candidate_text(value):
    return [{"rank": i + 1, "name": c.get("name", ""),
             "distance_m": c.get("distance_m"), "category": ""}
            for i, c in enumerate(match_score.parse_top_candidates(value or ""))]


def _load_original_mapkit_outputs(limit=5):
    """Read original MapKit probe TSVs, never generated candidate JSONL."""
    records = {}
    for filename, rich_field in (("rerun_mapkit_output.tsv", "wide_candidates_json"),
                                 ("ls_nearby_results.tsv", "top3_wide")):
        path = os.path.join(DIRECTORY, filename)
        if not os.path.isfile(path):
            continue
        grouped = defaultdict(list)
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                photo = os.path.basename((row.get("photo") or "").strip())
                if photo:
                    grouped[photo].append(row)
        for photo, rows in grouped.items():
            if photo in records:
                continue
            variants, signatures = [], set()
            for row in rows:
                try:
                    parsed = json.loads(row.get(rich_field) or "") if rich_field == "wide_candidates_json" else []
                except json.JSONDecodeError:
                    parsed = []
                candidates = parsed if isinstance(parsed, list) and parsed else _parse_source_candidate_text(row.get("top3_wide"))
                signature = json.dumps(candidates, ensure_ascii=False, sort_keys=True)
                if signature not in signatures:
                    signatures.add(signature)
                    variants.append(candidates)
            chosen = variants[-1] if variants else []
            has_rich = rich_field == "wide_candidates_json" and bool((rows[-1].get(rich_field) or "").strip())
            records[photo] = {"candidates": chosen[:limit], "source": filename,
                "sourceField": rich_field if has_rich else "top3_wide",
                "sourceRows": len(rows), "sourceVariants": len(variants),
                "sourceRetained": len(chosen), "reportedWideCount": rows[-1].get("wide_n", "")}
    return records


def _load_result_evidence():
    """Read raw model logs directly; create no explorer-specific artifact."""
    specs = {
        "fastvlm-top5-reranker": "fastvlm_results.tsv",
        "fastvlm-top10-reranker": "fastvlm_top10_results.tsv",
        "fastvlm-top20-reranker": "fastvlm_top20_results.tsv",
        "fastvlm-bloggo-verified-top5": "fastvlm_bloggo_hybrid_results.tsv",
        "mapkit-bloggo-ocr-reranker-exploratory": "bloggo_ocr_reranker_results.tsv",
        "fastvlm-bloggo-ocr-fastvlm-semantic-v5-permissive-exploratory":
            "fastvlm_bloggo_ocr_fastvlm_semantic_v5_permissive_results.tsv",
    }
    result = {}
    for run_name, filename in specs.items():
        path = os.path.join(DIRECTORY, filename)
        if not os.path.isfile(path):
            continue
        grouped = defaultdict(list)
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                key = ((row.get("dataset") or "").strip(), os.path.basename((row.get("photo") or "").strip()))
                grouped[key].append(row)
        result[run_name] = {"file": filename, "rows": grouped}
    return result


def _gt_overrides_path():
    return os.path.join(DIRECTORY, "gt_mapkit_overrides.tsv")


def _load_gt_overrides():
    """Manual GT↔MapKit matches saved by the reconciliation UI, keyed by (dataset, photo)."""
    path = _gt_overrides_path()
    done = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                done[(row.get("dataset", ""), row.get("photo", ""))] = row
    return done


def gt_reconcile_queue(limit=300):
    """Cases whose GT could not be matched to any MapKit name (gt_mapkit == NON_MAPKIT)
    and are not yet manually reconciled — with their MapKit candidate list to pick from.

    Candidates are keyed by photo basename (cohort-independent), so the whole
    NON_MAPKIT backlog is reachable, not just a frozen run cohort.
    """
    if not os.path.isfile(CSV_PATH):
        return {"total_non_mapkit": 0, "done": 0, "remaining": 0, "cases": []}
    done = _load_gt_overrides()
    cand_map = _load_original_mapkit_outputs(limit=50)
    out, total_non = [], 0
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("gt_mapkit") or "").strip() != "NON_MAPKIT":
                continue
            total_non += 1
            dataset = (r.get("dataset") or "").strip()
            photo = (r.get("photo") or "").strip()
            if (dataset, photo) in done:
                continue
            if limit and len(out) >= limit:
                continue
            rec = cand_map.get(os.path.basename(photo)) or {}
            cands = rec.get("candidates", [])
            out.append({
                "dataset": dataset, "photo": photo,
                "image": f"/api/poi-case-photo?dataset={urllib.parse.quote(dataset)}&photo={urllib.parse.quote(photo)}",
                "gt": (r.get("input_place_name") or "").strip(),
                "lat": (r.get("capture_lat") or "").strip(),
                "lon": (r.get("capture_lon") or "").strip(),
                "ocr": (r.get("ocr_text") or r.get("caption_ondevice") or "").strip(),
                "candidates": [{"rank": c.get("rank") or i + 1, "name": c.get("name", ""),
                                "distance": c.get("distance") or c.get("distance_m"),
                                "category": c.get("category", ""),
                                "lat": c.get("lat"), "lon": c.get("lon")}
                               for i, c in enumerate(cands)],
            })
    no_candidate = sum(1 for c in out if not c["candidates"])
    return {"total_non_mapkit": total_non, "done": len(done),
            "remaining": total_non - len(done), "no_candidate": no_candidate, "cases": out}


def mapkit_probe(lat, lon):
    """Live MapKit nearby query for an arbitrary coordinate (Investigate flow).
    Runs ls_mapkit_probe.swift — slow (~20–30s: swift compile + network)."""
    swift_file = os.path.join(REPO_DIR, "tools", "swift", "ls_mapkit_probe.swift")
    if not os.path.isfile(swift_file):
        return {"ok": False, "message": "probe script missing", "candidates": []}
    in_tsv = out_tsv = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, newline="") as f:
            f.write("photo\tlat\tlon\tkw\n")
            f.write("probe\t%s\t%s\t\n" % (lat, lon))
            in_tsv = f.name
        out_tsv = in_tsv + ".out"
        with open(out_tsv, "w", encoding="utf-8") as out:
            proc = subprocess.run(["swift", swift_file, in_tsv], stdout=out,
                                  stderr=subprocess.PIPE, text=True, timeout=150)
        if proc.returncode != 0:
            return {"ok": False, "message": "probe failed: %s" % (proc.stderr or "")[:200],
                    "candidates": []}
        cands = []
        with open(out_tsv, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    cands = json.loads(row.get("wide_candidates_json") or "[]")
                except Exception:
                    cands = []
                break
        norm = [{"rank": c.get("rank") or i + 1, "name": c.get("name", ""),
                 "distance": c.get("distance_m"), "category": c.get("category", ""),
                 "lat": c.get("lat"), "lon": c.get("lon")}
                for i, c in enumerate(cands) if (c.get("name") or "").strip()]
        return {"ok": True, "lat": lat, "lon": lon, "candidates": norm}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "probe timed out", "candidates": []}
    except Exception as e:
        return {"ok": False, "message": str(e), "candidates": []}
    finally:
        for p in (in_tsv, out_tsv):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


def case_detail(dataset, photo):
    """Single-case detail for the Case inspector — composed from stable sources
    (eval CSV row + MapKit candidate list + the best run's prediction), so it
    doesn't depend on the frozen 166-cohort explorer artifacts."""
    if not os.path.isfile(CSV_PATH):
        return None
    row = None
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("dataset") or "").strip() == dataset and (r.get("photo") or "").strip() == photo:
                row = r
                break
    if row is None:
        return None
    cand = (_load_original_mapkit_outputs().get(os.path.basename(photo)) or {}).get("candidates", [])
    best, pred = None, {}
    try:
        scored = [r for r in list_runs(RUNS_DIR) if isinstance(r.get("accuracy_pct"), (int, float))]
        best = max(scored, key=lambda r: r.get("accuracy_pct") or 0) if scored else None
        if best:
            full = get_run(RUNS_DIR, best["name"], best["version"])
            for c in full.get("cases", []):
                if c.get("dataset") == dataset and c.get("photo") == photo:
                    pred = c
                    break
    except Exception:
        best, pred = None, {}
    lat = (row.get("capture_lat") or "").strip()[:9]
    lon = (row.get("capture_lon") or "").strip()[:9]
    return {
        "dataset": dataset, "photo": photo,
        "image": f"/api/poi-case-photo?dataset={urllib.parse.quote(dataset)}&photo={urllib.parse.quote(photo)}",
        "gt": (row.get("input_place_name") or "").strip(),
        "gt_mapkit": (row.get("gt_mapkit") or "").strip(),
        "prediction": pred.get("prediction", ""),
        "reason": pred.get("reason", ""),
        "match_kind": pred.get("match_kind", ""),
        "correct": bool(pred.get("correct")),
        "run": {"name": best["name"], "version": best["version"]} if best else None,
        "lat": lat, "lon": lon,
        "signals": {
            "gps": (", ".join(x for x in (lat, lon) if x)),
            "ocr": (row.get("caption_ondevice") or "").strip()[:240],
            "nearby": (row.get("app_nearby_n_wide") or "").strip(),
            "category": (row.get("category") or "").strip(),
        },
        "candidates": [{"rank": c.get("rank") or i + 1, "name": c.get("name", ""),
                        "distance": c.get("distance") or c.get("distance_m"),
                        "category": c.get("category", "")}
                       for i, c in enumerate(cand)],
    }


def poi_case_explorer_data():
    """Compose cards from canonical run artifacts; write no report JSON.

    Include only the newest version of each algorithm whose cases cover exactly
    the frozen 166-case cohort. Partial/smoke runs are not silently padded.
    """
    config = match_score.load_config(config_read_path())
    cases = algorithm.build_cases(
        match_score.read_rows(CSV_PATH), config,
        match_score.load_candidates([MATCH_CANDIDATE_PATHS[0]]),
        "all", ["image", "ocr_text", "nearby_candidates"], 5,
    )
    by_name = {}
    for filename in os.listdir(RUNS_DIR):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(RUNS_DIR, filename), encoding="utf-8") as f:
            run = json.load(f)
        name, version = run.get("name"), run.get("version", 0)
        if name and (name not in by_name or version > by_name[name].get("version", 0)):
            by_name[name] = run
    runs = {name: run for name, run in by_name.items()
            if len(run.get("cases", [])) == len(cases) == 166}
    if not runs:
        raise RuntimeError("No complete frozen 166-case run snapshots were found")
    indexes = {}
    for name, run in runs.items():
        grouped = defaultdict(list)
        for row in run["cases"]:
            grouped[(row["dataset"], row["photo"])].append(row)
        indexes[name] = grouped
    result_evidence = _load_result_evidence()
    occurrence = Counter()
    with open(os.path.join(DIRECTORY, "fastvlm_bloggo_ocr_fastvlm_semantic_v5_permissive_results.tsv"), encoding="utf-8") as f:
        audit = {(row["dataset"], row["photo"]): row for row in csv.DictReader(f, delimiter="\t")}
    result = []
    for number, case in enumerate(cases, 1):
        key = (case["_dataset"], case["_photo"])
        row_occurrence = occurrence[key]
        occurrence[key] += 1
        data, gt = case["input"], case["_gt"]
        # Render precisely the object delivered to every algorithm. This uses
        # the same JSONL-to-app_nearby_top1 fallback and raw ranks as evaluation.
        candidates = data.get("nearby_candidates", [])
        details = audit.get(key, {})
        record = {"id": number, "dataset": key[0], "photo": key[1],
            "image": f"/api/poi-case-photo?dataset={urllib.parse.quote(key[0])}&photo={urllib.parse.quote(key[1])}",
            "gt": gt, "top5": any(c.get("name") == gt for c in candidates),
            "candidateSource": {"source": "evaluation case input",
                                "sourceField": "nearby_candidates",
                                "candidateLimit": 5},
            "candidates": [{"rank": c.get("rank") or i + 1, "name": c.get("name", ""),
                            "distance": c.get("distance_m"), "category": c.get("category", "")}
                           for i, c in enumerate(candidates)],
            "ocr": data.get("ocr_text", ""), "v5Decision": details.get("decision", ""),
            "v5Raw": details.get("selection_raw", ""), "v5Nomination": details.get("nominated_candidate", ""),
            "predictions": {}}
        for name, index in indexes.items():
            frozen_rows = index.get(key) or []
            frozen = frozen_rows[min(row_occurrence, len(frozen_rows) - 1)] if frozen_rows else None
            if not frozen:
                raise RuntimeError(f"Missing frozen {name} result for {key}")
            record["predictions"][name] = {"name": frozen["prediction"], "correct": frozen["correct"],
                                           "reason": frozen.get("reason", "")}
            evidence_source = result_evidence.get(name)
            if evidence_source:
                evidence_rows = evidence_source["rows"].get(key) or []
                if evidence_rows:
                    evidence_row = evidence_rows[min(row_occurrence, len(evidence_rows) - 1)]
                    record["predictions"][name]["evidence"] = evidence_row
                    record["predictions"][name]["evidenceSource"] = evidence_source["file"]
        result.append(record)
    # Names are verbatim canonical run names, as displayed by the Runs UI.
    algorithms = [{"id": name, "label": name, "version": run.get("version"),
                   "accuracy": (run.get("metrics") or {}).get("accuracy"),
                   "correct": (run.get("metrics") or {}).get("correct")}
                  for name, run in sorted(runs.items())]
    return {"algorithms": algorithms, "cases": result}


def poi_case_photo(photo):
    """Locate an original image without a copied report-asset directory."""
    if os.path.basename(photo) != photo:
        return None
    roots = [os.path.join(DIRECTORY, name) for name in
             ("linkedspaces-photos", "photos", "poi-dataset-20260708-photos", "union-city-trip/photos")]
    for root in roots:
        direct = os.path.join(root, photo)
        if os.path.isfile(direct):
            return direct
        if os.path.isdir(root):
            found = next((path for path in Path(root).rglob(photo) if path.is_file()), None)
            if found:
                return str(found)
    return None

# ---------------------------------------------------------------------------
# Background job registry. Every CSV-mutating operation (GT classify, signal
# re-run, dataset delete) runs as a single-slot job: only ONE runs at a time
# (they all rewrite eval_set_reconciled.csv) — a 2nd request returns 409.
# Subprocess steps run tools/<script> in a daemon thread; builtin steps run a
# Python function in-thread. Worker stdout is logged; the last `RESULT {json}`
# line becomes job.result and `PROGRESS {json}` lines feed live progress.
# ---------------------------------------------------------------------------
JOBS_DIR = os.path.join(DIRECTORY, "generated", "jobs")

# step -> how to run it. Executable mapping (repo paths) lives here; UI labels
# and enabled/disabled state come from dashboard_config.json "signals".
STEP_REGISTRY = {
    "gt_mapkit":      {"script": os.path.join(REPO_DIR, "tools", "gt_classify_mapkit.py")},
    "gt_kakao":       {"script": os.path.join(REPO_DIR, "tools", "gt_classify_kakao.py")},
    "ocr":            {"script": os.path.join(REPO_DIR, "tools", "rerun_ocr.py")},
    "mapkit_nearby":  {"script": os.path.join(REPO_DIR, "tools", "rerun_mapkit_nearby.py")},
    "ingest":         {"script": os.path.join(REPO_DIR, "tools", "ingest_dataset.py")},
    "delete_dataset": {"builtin": "delete_dataset"},
    "pipeline":       {"builtin": "post_ingest_pipeline"},
    "exif":           {"script": os.path.join(REPO_DIR, "tools", "rerun_exif.py")},
    # These are intentionally unavailable rather than pretending enrichment ran.
    "geocode":        {"disabled": "Not implemented (no CLGeocoder worker)"},
    "vlm_caption":    {"disabled": "Not implemented"},
}

_jobs = {}                      # job_id -> job dict
_job_lock = threading.Lock()
_active = {"id": None}          # id of the currently-running job (only one allowed)


def _tail_log(path, n=25):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


def _read_progress(log_path):
    """Last `PROGRESS {json}` line written by a worker, or None."""
    if not log_path or not os.path.exists(log_path):
        return None
    try:
        last = None
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("PROGRESS "):
                    last = ln
        return json.loads(last[len("PROGRESS "):]) if last else None
    except Exception:
        return None


def _read_warnings(log_path):
    """Structured warnings emitted by a job, including ones found mid-pipeline."""
    if not log_path or not os.path.exists(log_path):
        return []
    warnings = []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("WARNING "):
                    try: warnings.append(json.loads(line[8:]))
                    except json.JSONDecodeError: pass
    except Exception:
        pass
    return warnings


def _job_public(job):
    out = dict(job)
    started, finished = job.get("started"), job.get("finished")
    out["elapsed_s"] = round((finished or time.time()) - started, 1) if started else None
    out["progress"] = _read_progress(job.get("log_path"))
    out["warnings"] = _read_warnings(job.get("log_path"))
    return out


def _job_argv(step, params):
    argv = [sys.executable, STEP_REGISTRY[step]["script"]]
    p = params or {}
    if p.get("zip_path"):
        argv += ["--zip", p["zip_path"]]
    if p.get("dataset"):
        argv += ["--dataset", p["dataset"]]
    if p.get("only_empty"):
        argv += ["--only-empty"]
    return argv


def _run_job(job_id):
    job = _jobs[job_id]
    step = job["step"]
    log_path = os.path.join(JOBS_DIR, f"{job_id}.log")
    job["log_path"] = log_path
    try:
        os.makedirs(JOBS_DIR, exist_ok=True)
        spec = STEP_REGISTRY[step]
        if spec.get("builtin"):
            with open(log_path, "w", encoding="utf-8") as log:
                result = _run_builtin(spec["builtin"], job["params"], log)
            rc = 0 if (result or {}).get("ok") else 1
            job.update(status=("done" if rc == 0 else "error"), returncode=rc,
                       finished=time.time(), result=result, log_tail=_tail_log(log_path))
            return
        env = dict(os.environ)
        env["POI_DATA_DIR"] = DIRECTORY
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(
                _job_argv(step, job["params"]),
                cwd=REPO_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
                # Detach: no inherited client socket / stdin, own session, so a
                # minutes-long child never holds the caller's connection open.
                stdin=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        result = None
        for ln in reversed(lines):
            if ln.startswith("RESULT "):
                try:
                    result = json.loads(ln[len("RESULT "):])
                except Exception:
                    result = None
                break
        # A successful upload immediately flows through the implemented
        # enrichment stages under this same CSV-mutating job lock.  It is not a
        # second reservable job, avoiding a race with another writer.
        if step == "ingest" and proc.returncode == 0 and (result or {}).get("dataset"):
            with open(log_path, "a", encoding="utf-8") as log:
                pipeline = _post_ingest_pipeline({"dataset": result["dataset"]}, log)
            result = {"ingest": result, "pipeline": pipeline}
        lines = _tail_log(log_path, 25)
        job.update(status=("done" if proc.returncode == 0 else "error"),
                   returncode=proc.returncode, finished=time.time(),
                   result=result, log_tail=lines)
    except Exception as e:
        job.update(status="error", finished=time.time(), error=str(e))
    finally:
        # Ingest archives are transient worker inputs, not retained dataset
        # artifacts. Remove them after either success or failure.
        if step == "ingest":
            zip_path = (job.get("params") or {}).get("zip_path")
            if zip_path:
                try:
                    os.unlink(zip_path)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    job["cleanup_error"] = f"could not remove upload archive: {e}"
        with _job_lock:
            if _active["id"] == job_id:
                _active["id"] = None


def reserve(step, params):
    """Reserve the single job slot. Returns (job_id, None) or (None, (code, msg)).

    Does NOT start the worker — the caller sends the HTTP response first, then
    calls launch(), so the client's connection is never inherited by the fork.
    """
    spec = STEP_REGISTRY.get(step)
    if spec is None:
        return None, ("unknown_step", f"unknown step {step!r}")
    if spec.get("disabled"):
        return None, ("disabled", f"step {step!r} {spec['disabled']}")
    with _job_lock:
        if _active["id"] is not None:
            return None, ("busy", f"a job is already running ({_active['id']})")
        job_id = uuid.uuid4().hex[:12]
        _active["id"] = job_id
        _jobs[job_id] = {
            "job_id": job_id, "step": step, "params": params or {},
            "status": "running", "started": time.time(), "finished": None,
            "returncode": None, "result": None, "error": None,
            "log_tail": [], "log_path": None,
        }
    return job_id, None


def launch(job_id):
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()


def _photo_dir_for(dataset):
    src = (load_config().get("sources") or {}).get(dataset) or {}
    if src.get("photo_dir"):
        return src["photo_dir"]
    return {"linkedspaces": "linkedspaces-photos", "vancouver": "photos",
            "union-city": "union-city-trip"}.get(dataset)


def _config_photo_dirs():
    """photo_dir values from config sources, so uploaded datasets' photos serve."""
    try:
        return {s.get("photo_dir") for s in (load_config().get("sources") or {}).values() if s.get("photo_dir")}
    except Exception:
        return set()


def _run_builtin(name, params, log):
    if name == "delete_dataset":
        return _delete_dataset(params, log)
    if name == "post_ingest_pipeline":
        return _post_ingest_pipeline(params, log)
    return {"ok": False, "error": f"unknown builtin {name!r}"}


def _post_ingest_pipeline(params, log):
    """Run EXIF first, then independent enrichments in parallel with live logs."""
    dataset = (params.get("dataset") or "").strip()
    if not dataset:
        return {"ok": False, "error": "pipeline requires dataset"}
    stages = [{"step": "geocode", "status": "skipped", "reason": "no CLGeocoder worker is implemented"}]
    warnings, sequence = [], ["exif", "ocr", "mapkit_nearby", "gt_mapkit"]
    if os.environ.get("KAKAO_REST_API_KEY", "").strip(): sequence.append("gt_kakao")
    else: stages.append({"step": "gt_kakao", "status": "skipped", "reason": "KAKAO_REST_API_KEY is not set"})
    env = dict(os.environ); env["POI_DATA_DIR"] = DIRECTORY

    def run_batch(steps, completed):
        procs, lines, events = {}, {x: [] for x in steps}, queue.Queue()
        def relay(name, stream):
            for raw in iter(stream.readline, ""): events.put((name, raw.rstrip("\n")))
            stream.close()
        for name in steps:
            print(f"[pipeline] starting {name}", file=log, flush=True)
            p = subprocess.Popen(_job_argv(name, {"dataset": dataset, "only_empty": True}), cwd=REPO_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, stdin=subprocess.DEVNULL,
                close_fds=True, start_new_session=True)
            procs[name] = p; threading.Thread(target=relay, args=(name,p.stdout), daemon=True).start()
        live = {x: {"status":"running", "done":0, "total":0, "step":"starting", "retries":0} for x in steps}
        while any(p.poll() is None for p in procs.values()) or not events.empty():
            try: name, line = events.get(timeout=.15)
            except queue.Empty: continue
            lines[name].append(line); print(f"[{name}] {line}", file=log, flush=True)
            if line.startswith("PROGRESS "):
                try:
                    ev=json.loads(line[9:]); live[name].update({k:ev[k] for k in ("done","total","step","retries","retry_reason") if k in ev})
                except (json.JSONDecodeError, TypeError): pass
                print("PROGRESS "+json.dumps({"done":completed,"total":len(sequence),"step":"parallel","substeps":live}),file=log,flush=True)
        for p in procs.values(): p.wait()
        results={}
        for name,p in procs.items():
            result=None
            for line in reversed(lines[name]):
                if line.startswith("RESULT "):
                    try: result=json.loads(line[7:])
                    except json.JSONDecodeError: pass
                    break
            status="done" if p.returncode==0 else "error"; reason=None
            if status=="done" and result and not result.get("targets",1): status,reason="skipped",result.get("skip_reason") or "no eligible rows"
            live[name]["status"]=status; stages.append({"step":name,"status":status,"reason":reason,"returncode":p.returncode,"result":result}); results[name]=result
        return results,live

    first,_=run_batch(["exif"],0); exif=first.get("exif") or {}
    targets,no_gps=exif.get("targets",0),exif.get("no_gps",0)
    if targets and no_gps:
        w={"code":"exif_gps_missing","dataset":dataset,"count":no_gps,"targets":targets,"message":f"{no_gps}/{targets} source photos are missing EXIF GPS coordinates. Coordinate-based steps have no targets."}; warnings.append(w); print("WARNING "+json.dumps(w,ensure_ascii=False),file=log,flush=True)
    no_timestamp=exif.get("no_timestamp",0)
    if targets and no_timestamp:
        w={"code":"exif_timestamp_missing","dataset":dataset,"count":no_timestamp,"targets":targets,"message":f"{no_timestamp}/{targets} source photos are missing EXIF capture timestamps."}; warnings.append(w); print("WARNING "+json.dumps(w,ensure_ascii=False),file=log,flush=True)
    print("PROGRESS "+json.dumps({"done":1,"total":len(sequence),"step":"exif"}),file=log,flush=True)
    parallel=["ocr","mapkit_nearby","gt_mapkit"] + (["gt_kakao"] if "gt_kakao" in sequence else [])
    _,live=run_batch(parallel,1)
    print("PROGRESS "+json.dumps({"done":len(sequence),"total":len(sequence),"step":"pipeline","substeps":live}),file=log,flush=True)
    errors=[x["step"] for x in stages if x["status"]=="error"]
    outcome={"ok":True,"step":"pipeline","dataset":dataset,"stages":stages,"warnings":warnings,"partial":bool(errors),"errors":errors}
    print("RESULT "+json.dumps(outcome,ensure_ascii=False),file=log,flush=True); return outcome


def _delete_dataset(params, log):
    dataset = (params.get("dataset") or "").strip()
    if not dataset:
        return {"ok": False, "error": "no dataset given"}
    fieldnames, rows = gc_read_csv(CSV_PATH)
    present = sorted({(r.get("dataset") or "").strip() for r in rows if (r.get("dataset") or "").strip()})
    if dataset not in present:
        return {"ok": False, "error": f"unknown dataset {dataset!r}", "datasets": present}
    # Last remaining dataset may be deleted; empty eval set / zero-dataset UI is supported.
    removed = [r for r in rows if (r.get("dataset") or "").strip() == dataset]
    kept = [r for r in rows if (r.get("dataset") or "").strip() != dataset]

    # A server-managed upload owns both its dedicated photo directory and its
    # generated config entry. Treat them as one unit so deleting an upload
    # really frees its slug for a later re-upload. Never apply this broader
    # cleanup to curated sources: their photo directories can be shared.
    full_upload_cleanup = bool(params.get("delete_photos") and params.get("remove_config_source"))
    upload_photo_dir = None
    if full_upload_cleanup:
        cfg = load_config()
        source = (cfg.get("sources") or {}).get(dataset) or {}
        photo_dir = source.get("photo_dir") or ""
        candidate = os.path.realpath(os.path.join(DIRECTORY, photo_dir))
        expected_dir = f"{dataset}-photos"
        if source.get("source_type") != "upload" or photo_dir != expected_dir:
            return {"ok": False, "error": "full cleanup is allowed only for server-managed uploads"}
        if not (candidate.startswith(os.path.realpath(DIRECTORY) + os.sep) and
                os.path.basename(candidate) == expected_dir and not os.path.islink(candidate)):
            return {"ok": False, "error": "unsafe upload photo directory"}
        upload_photo_dir = candidate

    backup = gc_backup_csv(CSV_PATH)
    print(f"backup: {backup}", file=log)
    gc_write_csv(CSV_PATH, fieldnames, kept)
    print(f"removed {len(removed)} rows for dataset {dataset}", file=log)

    photos_deleted = photos_missing = 0
    if upload_photo_dir:
        if os.path.isdir(upload_photo_dir):
            photos_deleted = sum(len(files) for _, _, files in os.walk(upload_photo_dir))
            shutil.rmtree(upload_photo_dir)
        print(f"removed upload photo directory ({photos_deleted} files): {upload_photo_dir}", file=log)
    elif params.get("delete_photos"):
        pdir = _photo_dir_for(dataset)
        if pdir:
            base = os.path.realpath(os.path.join(DIRECTORY, pdir))
            for r in removed:
                ph = (r.get("photo") or "").strip()
                if not ph:
                    continue
                p = os.path.realpath(os.path.join(base, ph))
                if not (p == base or p.startswith(base + os.sep)):
                    continue  # never escape the dataset's own photo dir
                if os.path.isfile(p):
                    os.remove(p)
                    photos_deleted += 1
                else:
                    photos_missing += 1
            print(f"photos deleted={photos_deleted} missing={photos_missing}", file=log)

    config_source_removed = False
    if params.get("remove_config_source"):
        try:
            with open(config_read_path(), encoding="utf-8") as f:
                cfg = json.load(f)
            if dataset in (cfg.get("sources") or {}):
                os.makedirs(DIRECTORY, exist_ok=True)
                bak = None
                if os.path.exists(DATA_CONFIG_PATH):
                    bak = f"{DATA_CONFIG_PATH}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
                    with open(bak, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                del cfg["sources"][dataset]
                tmp = f"{DATA_CONFIG_PATH}.tmp-{os.getpid()}"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                os.replace(tmp, DATA_CONFIG_PATH)
                config_source_removed = True
                print(f"removed sources[{dataset}] from {DATA_CONFIG_PATH} (backup {bak or 'none'})", file=log)
        except Exception as e:
            print(f"config source removal failed: {e}", file=log)

    result = {"ok": True, "step": "delete_dataset", "dataset": dataset,
              "removed_rows": len(removed), "backup": backup,
              "photos_deleted": photos_deleted, "photos_missing": photos_missing,
              "config_source_removed": config_source_removed,
              "upload_photo_directory_removed": bool(upload_photo_dir)}
    print("RESULT " + json.dumps(result, ensure_ascii=False), file=log)
    return result


def load_config():
    with open(config_read_path(), encoding="utf-8") as f:
        return json.load(f)


def nonempty(rows, col):
    return sum(1 for r in rows if (r.get(col) or "").strip())


def read_eval_csv():
    """Return (columns, rows), including the valid first-run/no-data state."""
    if not os.path.isfile(CSV_PATH):
        return [], []
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def tsv_counts(path, textcol=1):
    """(rows_with_text_in_col, total_data_rows) for a TSV with a header."""
    if not os.path.exists(path):
        return 0, 0
    total = withtext = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        next(f, None)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            total += 1
            if len(parts) > textcol and parts[textcol].strip():
                withtext += 1
    return withtext, total


def tsv_datarows(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8", errors="replace") as f:
        return max(0, sum(1 for _ in f) - 1)


def build_overview():
    cfg = load_config()
    cols, rows = read_eval_csv()
    n = len(rows)
    warnings = []

    # ---- helpers driven by config ----
    def norm_country(r):
        ds = r.get("dataset")
        if ds in cfg["country_by_dataset"]:
            return cfg["country_by_dataset"][ds]
        c = (r.get("country") or "").strip()
        return cfg["country_normalize"].get(c, c or "Unknown")

    # ---- sources (structure from data, labels from config; unknown -> flagged) ----
    src_counts = Counter((r.get("dataset") or "").strip() for r in rows)
    sources = []
    for i, (k, v) in enumerate(src_counts.most_common()):
        c = cfg["sources"].get(k)
        if c is None:
            warnings.append(f"source '{k}' — missing from config (add under dashboard_config.json > sources)")
        sources.append({"key": k, "count": v,
                        "label": (c or {}).get("label", ""),
                        "color": (c or {}).get("color", cfg["palette"][i % len(cfg["palette"])]),
                        "owner": (c or {}).get("owner", ""),
                        "source_type": (c or {}).get("source_type", ""),
                        "desc": (c or {}).get("desc", ""),
                        "known": c is not None})

    # ---- confidence: roll raw gt_confidence up into canonical tiers (config-driven) ----
    raw_counts = Counter((r.get("gt_confidence") or "").strip() for r in rows)
    tier_counts, tier_members = Counter(), {}
    for raw, cnt in raw_counts.items():
        canon = cfg["confidence_rollup"].get(raw)
        if canon is None:
            warnings.append(f"gt_confidence '{raw}' — missing from confidence_rollup (add a mapping)")
            canon = raw  # surface as its own tier rather than dropping
        tier_counts[canon] += cnt
        tier_members.setdefault(canon, []).append([raw, cnt])
    tiers_cfg = cfg["confidence_tiers"]
    confidence = []
    for canon in sorted(tier_counts, key=lambda k: (tiers_cfg.get(k, {}).get("order", 99), -tier_counts[k])):
        meta = tiers_cfg.get(canon)
        if meta is None:
            warnings.append(f"canonical tier '{canon}' — not defined in confidence_tiers")
        members = sorted(tier_members[canon], key=lambda m: -m[1])
        confidence.append({"key": canon, "count": tier_counts[canon],
                           "color": (meta or {}).get("color", "ink3"),
                           "desc": (meta or {}).get("desc", ""),
                           "members": members, "known": meta is not None})

    # ---- countries ----
    country_counts = Counter(norm_country(r) for r in rows)
    countries = [{"key": k, "count": v, "flag": cfg["country_flags"].get(k, "·")}
                 for k, v in country_counts.most_common()]

    # ---- categories (pure data) ----
    cat_counts = Counter((r.get("category") or "").strip() for r in rows if (r.get("category") or "").strip())

    # ---- per-column fill (all rows + per-dataset, for the source dropdown) ----
    fill = {c: nonempty(rows, c) for c in cols}
    ds_keys = [k for k, _ in src_counts.most_common() if k]
    total_by_dataset = {ds: 0 for ds in ds_keys}
    fill_by_dataset = {ds: {c: 0 for c in cols} for ds in ds_keys}
    for r in rows:
        ds = (r.get("dataset") or "").strip()
        if ds not in total_by_dataset:
            continue
        total_by_dataset[ds] += 1
        for c in cols:
            if (r.get(c) or "").strip():
                fill_by_dataset[ds][c] += 1

    # ---- schema: driven by REAL columns. Config supplies grouping/role/desc.
    #      Any real column not covered by a config group is surfaced, not dropped. ----
    covered = set()
    schema = []
    for g in cfg["schema_groups"]:
        present = [c for c in g["cols"] if c in fill]
        covered.update(g["cols"])
        if not present:
            continue  # group's columns don't exist in this CSV — skip silently (config ahead of data)
        rep = present[0]
        role = cfg["roles"].get(g["role"], {"label": g["role"], "tag": "t-mt"})
        schema.append({"group": g["group"], "role_key": g["role"], "role_label": role["label"],
                       "role_tag": role["tag"], "fill": fill[rep], "cols": present,
                       "desc": g["desc"], "known": True})
    uncovered = [c for c in cols if c not in covered]
    for c in uncovered:
        warnings.append(f"column '{c}' — missing from schema_groups (add role/description)")
        schema.append({"group": c, "role_key": "?", "role_label": "Unclassified", "role_tag": "t-mt",
                       "fill": fill[c], "cols": [c], "desc": "⚠ Missing config description — add under dashboard_config.json > schema_groups.", "known": False})

    # ---- sample rows (one per dataset) ----
    samples = {}
    for r in rows:
        d = r.get("dataset")
        if d and d not in samples:
            samples[d] = {k: (r.get(k) or "") for k in
                          ("input_place_name", "gt_mapkit", "gt_kakao", "gt_confidence", "category",
                           "capture_lat", "capture_lon", "city", "country", "photo", "photo_url")}

    # ---- pipeline: labels from config, counts from real files/columns ----
    def tsv_photoset(path):
        s = set()
        p = os.path.join(DIRECTORY, path)
        if not os.path.exists(p):
            return s
        with open(p, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                k = line.split("\t", 1)[0].strip()
                if k:
                    s.add(k)
        return s

    ls_ocr_text, _ = tsv_counts(os.path.join(DIRECTORY, "ls_ocr_text.tsv"))
    our_ocr_text, _ = tsv_counts(os.path.join(DIRECTORY, "ocr_text.tsv"))
    ocr_photos = tsv_photoset("ls_ocr_text.tsv") | tsv_photoset("ocr_text.tsv")   # processed photos (with or without text)
    base_photos = tsv_photoset("ls_nearby_results.tsv")                            # photos with baseline computed
    csv_photos = [(r.get("photo") or "").strip() for r in rows]
    ocr_cov = sum(1 for p in csv_photos if p and p in ocr_photos)                  # CSV rows covered by OCR
    base_avail = sum(1 for r in rows if (r.get("photo") or "").strip() in base_photos
                     or (r.get("app_poi_rank") or "").strip())                     # rows with baseline (file ∪ CSV)

    # Status rule (single source of truth, shown in UI):
    #   extracted = rows with signal computed · merged = rows reflected in CSV
    #   wait : extracted==0        (not started)
    #   done : merged >= extracted (all extracted rows are in CSV; out-of-scope never extracted)
    #   run  : otherwise           (extracted but not yet merged into CSV)
    def mk(p, extracted, merged, note=""):
        st = "wait" if extracted == 0 else ("done" if merged >= extracted else "run")
        return {"label": p["label"], "extracted": extracted, "merged": merged,
                "total": n, "status": st, "note": note}

    def step(p):
        kind = p["kind"]
        if kind == "column":
            f = fill.get(p["column"], 0)
            return mk(p, f, f)  # column data: extracted == merged
        if kind == "ocr":
            txt = ls_ocr_text + our_ocr_text
            return mk(p, ocr_cov, ocr_cov, f"{txt} with text · {ocr_cov-txt} empty OCR")
        if kind == "baseline":
            merged = fill.get("app_poi_rank", 0)
            deferred = n - base_avail
            return mk(p, base_avail, merged, f"{deferred} rows excluded (Korea / no photo, kr_deferred)")
        if kind == "tsv":
            return mk(p, tsv_datarows(os.path.join(DIRECTORY, p["file"])), 0, "Not merged into CSV")
        if kind == "file_exists":
            ok = os.path.exists(os.path.join(DIRECTORY, p["file"]))
            r = mk(p, n if ok else 0, n if ok else 0)
            if not ok:
                r["note"] = p.get("detail_wait", "")
            return r
        return mk(p, 0, 0)

    pipeline = [step(p) for p in cfg["pipeline"]]

    return {
        "generated_from": "eval_set_reconciled.csv + dashboard_config.json (live)",
        "data_state": "ready" if n else "empty",
        "csv_present": os.path.isfile(CSV_PATH),
        "total": n,
        "n_columns": len(cols),
        "palette": cfg["palette"],
        "sources": sources,
        "confidence": confidence,
        "countries": countries,
        "categories": cat_counts.most_common(12),
        "category_total_kinds": len(cat_counts),
        "fill": fill,
        "datasets": ds_keys,
        "total_by_dataset": total_by_dataset,
        "fill_by_dataset": fill_by_dataset,
        "photo_present": fill.get("photo", 0),
        "gt_present": fill.get("input_place_name", 0),
        "schema": schema,
        "samples": samples,
        "pipeline": pipeline,
        "config_warnings": warnings,
    }



def build_field_profile(group, dataset="__all"):
    """Return a compact semantic health profile, never a raw-value dump."""
    import re
    from urllib.parse import urlparse

    cfg = load_config()
    cols, all_rows = read_eval_csv()
    spec = next((g for g in cfg["schema_groups"] if g["group"] == group), None)
    selected_cols = ([c for c in spec["cols"] if c in cols] if spec else ([group] if group in cols else []))
    if not selected_cols:
        raise ValueError("unknown field group")
    rows = all_rows if dataset in ("", "__all", "all") else [
        r for r in all_rows if (r.get("dataset") or "").strip() == dataset]

    def clipped(value, limit=90):
        value = " ".join(str(value).split())
        return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"

    def as_numbers(values):
        try:
            return [float(v) for v in values]
        except (TypeError, ValueError):
            return None

    def bins(numbers):
        if not numbers:
            return []
        lo, hi = min(numbers), max(numbers)
        if lo == hi:
            return [{"label": f"{lo:g}", "count": len(numbers)}]
        count = min(8, max(4, int(math.sqrt(len(numbers)))))
        width, result = (hi - lo) / count, [0] * count
        for value in numbers:
            result[min(count - 1, int((value - lo) / width))] += 1
        return [{"label": f"{lo + i * width:.4g}–{lo + (i + 1) * width:.4g}", "count": n}
                for i, n in enumerate(result)]

    def semantic_kind(col, values, numbers):
        lower = col.lower()
        if lower == "caption_ondevice" or "ocr" in lower:
            return "ocr", "OCR text"
        if lower in {"capture_lat", "capture_lon", "lat", "lon", "lng", "latitude", "longitude"}:
            return "coordinate", "Coordinate"
        if any(part in lower for part in ("photo", "image", "url", "file", "path")):
            return "asset", "File/URL"
        if any(part in lower for part in ("timestamp", "date", "time")):
            return "date", "Date/time"
        if lower == "id" or lower.endswith("_id") or lower in {"photo", "dataset"}:
            return "identifier", "Identifier"
        if numbers is not None:
            return "number", "Number"
        unique = len(set(values))
        if unique <= min(24, max(4, len(values) // 3)):
            return "category", "Category"
        return "text", "Text"

    stop_terms = {
        "and", "are", "for", "from", "has", "have", "not", "the", "this", "that", "was", "with",
        "you", "your", "our", "all", "one", "two", "off", "www", "com", "http", "https",
    }

    def useful_words(value):
        """Extract readable OCR/text words while dropping fragments and numeric noise."""
        words = []
        for word in re.findall(r"[^\W\d_][\w'-]*", value, re.UNICODE):
            normalized = word.strip("_'-").casefold()
            letters = sum(ch.isalpha() for ch in normalized)
            if letters < 3 or len(normalized) > 28 or normalized in stop_terms:
                continue
            words.append(normalized)
        return words

    def script_label(value):
        has_korean = bool(re.search(r"[가-힣]", value))
        has_latin = bool(re.search(r"[A-Za-z]", value))
        if has_korean and has_latin:
            return "mixed"
        if has_korean:
            return "korean"
        if has_latin:
            return "latin"
        return "other"

    def sample_context(row, value, quality=""):
        dataset_name = (row.get("dataset") or "").strip()
        photo = (row.get("photo") or "").strip()
        return {
            "text": value,
            "preview": clipped(value, 150),
            "dataset": dataset_name,
            "photo": photo,
            "photo_url": _photo_url(dataset_name, photo),
            "place": clipped(row.get("input_place_name") or row.get("gt_mapkit") or "", 54),
            "quality": quality,
            "characters": len(value),
            "useful_tokens": len(useful_words(value)),
        }

    profiles = []
    for col in selected_cols:
        present_rows = [(row, (row.get(col) or "").strip()) for row in rows
                        if (row.get(col) or "").strip()]
        present = [value for _, value in present_rows]
        counts = Counter(present)
        numbers = as_numbers(present) if present else None
        kind, kind_label = semantic_kind(col, present, numbers)
        profile = {
            "column": col, "kind": kind, "kind_label": kind_label,
            "present": len(present), "missing": len(rows) - len(present),
            "unique": len(counts),
        }

        if kind == "ocr":
            lengths = [len(value) for value in present]
            token_counts = [len(useful_words(value)) for value in present]
            has_processed = any("ocr_processed" in row for row in rows)
            processed = (sum(1 for row in rows if str(row.get("ocr_processed") or "").strip().lower()
                             in {"1", "true", "yes", "done"}) if has_processed else len(present))
            processed = max(processed, len(present))

            terms = Counter()
            display_variants = defaultdict(Counter)
            language_counts = Counter()
            example_buckets = {"clear": [], "dense": [], "noisy": []}
            for row, value in present_rows:
                words = useful_words(value)
                language_counts[script_label(value)] += 1
                seen = set(words)
                terms.update(seen)  # count rows containing a term, not repetitions in one image
                for original in re.findall(r"[^\W\d_][\w'-]*", value, re.UNICODE):
                    normalized = original.strip("_'-").casefold()
                    if normalized in seen:
                        display_variants[normalized][original.strip("_'-")] += 1

                parts = [part for part in re.split(r"\s*\|\s*|\s+", value) if part]
                useful_ratio = len(words) / max(1, len(parts))
                quality = ("dense" if len(value) >= 180 or len(words) >= 18 else
                           "noisy" if len(words) < 2 or useful_ratio < .28 else "clear")
                example_buckets[quality].append(sample_context(row, value, quality))

            term_items = []
            for key, count in terms.most_common(12):
                variants = display_variants.get(key)
                label = variants.most_common(1)[0][0] if variants else key
                term_items.append({"value": clipped(label, 30), "count": count})

            examples = []
            order = (("clear", 2), ("dense", 1), ("noisy", 1))
            for bucket, limit in order:
                candidates = example_buckets[bucket]
                if bucket == "clear":
                    candidates.sort(key=lambda item: (not bool(item["photo_url"]), -item["useful_tokens"], item["characters"]))
                elif bucket == "dense":
                    candidates.sort(key=lambda item: (not bool(item["photo_url"]), -item["characters"]))
                else:
                    candidates.sort(key=lambda item: (not bool(item["photo_url"]), item["useful_tokens"], item["characters"]))
                examples.extend(candidates[:limit])

            profile["ocr"] = {
                "processed": processed,
                "detected": len(present),
                "no_text": max(0, processed - len(present)),
                "unprocessed": max(0, len(rows) - processed),
                "processed_pct": round(processed * 100 / len(rows), 1) if rows else 0,
                "detection_pct": round(len(present) * 100 / processed, 1) if processed else 0,
                "median_characters": round(statistics.median(lengths), 1) if lengths else 0,
                "median_useful_tokens": round(statistics.median(token_counts), 1) if token_counts else 0,
                "language_distribution": [
                    {"value": key, "count": count,
                     "pct": round(count * 100 / len(present), 1) if present else 0}
                    for key, count in language_counts.most_common()
                ],
            }
            profile["terms"] = term_items
            profile["examples"] = examples

        elif kind == "coordinate":
            if numbers:
                ordered = sorted(numbers)
                profile["numeric"] = {"min": min(numbers), "median": ordered[len(ordered) // 2],
                                      "max": max(numbers), "histogram": bins(numbers)}

        elif kind == "number":
            ordered = sorted(numbers or [])
            if ordered:
                profile["numeric"] = {"min": ordered[0], "median": ordered[len(ordered) // 2],
                                      "max": ordered[-1], "histogram": bins(ordered)}

        elif kind == "date":
            dates = sorted(v[:10] for v in present if len(v) >= 10)
            profile["date"] = {"earliest": dates[0] if dates else "", "latest": dates[-1] if dates else ""}
            profile["date_counts"] = [{"value": v, "count": n}
                                      for v, n in Counter(d[:7] for d in dates).most_common(8)]

        elif kind == "asset":
            urls = [v for v in present if urlparse(v).scheme in {"http", "https"} and urlparse(v).netloc]
            domains = Counter(urlparse(v).netloc.lower() for v in urls)
            profile["asset"] = {"valid_urls": len(urls), "other_references": len(present) - len(urls),
                                "domains": [{"value": d, "count": n} for d, n in domains.most_common(5)]}

        elif kind == "identifier":
            profile["identifier"] = {"duplicate_rows": len(present) - len(counts),
                                     "unique_rate": round(100 * len(counts) / len(present), 1) if present else 0}

        elif kind == "category":
            shown = counts.most_common(7)
            profile["top"] = [{"value": clipped(v, 48), "count": n} for v, n in shown]
            profile["other"] = len(present) - sum(n for _, n in shown)

        else:
            lengths = sorted(len(v) for v in present)
            profile["text"] = {"median_length": lengths[len(lengths) // 2] if lengths else 0}
            words = Counter()
            for value in present:
                words.update(w.casefold() for w in re.findall(r"[^\W\d_][\w'-]{2,}", value, re.UNICODE))
            profile["terms"] = [{"value": w, "count": n} for w, n in words.most_common(6) if n > 1]
            profile["samples"] = [clipped(v, 72) for v in present[:3]]
        profiles.append(profile)

    group_summary = None
    if {"capture_lat", "capture_lon"}.issubset(selected_cols):
        pairs = []
        for row in rows:
            try:
                pairs.append((float(row.get("capture_lat") or ""), float(row.get("capture_lon") or "")))
            except ValueError:
                pass
        if pairs:
            lats, lons = zip(*pairs)
            group_summary = {"kind": "geo_extent", "paired": len(pairs),
                             "north": max(lats), "south": min(lats),
                             "east": max(lons), "west": min(lons)}
    return {"group": group, "dataset": dataset, "total": len(rows),
            "group_summary": group_summary, "columns": profiles}

def build_datasets():
    """One entry per dataset for tab ④: label, count, per-signal fill, photo dir.

    The set of signals reported is driven by config `signals` so it stays in
    sync with the re-run step dropdown; a signal maps to one or more CSV columns
    and is measured on its representative (first) column.
    """
    cfg = load_config()
    signals = cfg.get("signals") or {}
    sources = cfg.get("sources") or {}
    _, rows = read_eval_csv()
    by = {}
    for r in rows:
        ds = (r.get("dataset") or "").strip()
        if ds:
            by.setdefault(ds, []).append(r)

    out = []
    for ds, drows in by.items():
        total = len(drows)
        sig = {}
        for name, meta in signals.items():
            scols = meta.get("cols") or ([meta["col"]] if meta.get("col") else [])
            rep = scols[0] if scols else None
            processed_col = meta.get("processed_col")
            label_breakdown = None
            coverage_metrics = []
            for metric in meta.get("coverage_metrics") or []:
                metric_cols = metric.get("cols") or []
                require_all = metric.get("require", "all") == "all"

                def has_coverage(r):
                    values = [bool((r.get(col) or "").strip()) for col in metric_cols]
                    return bool(values) and (all(values) if require_all else any(values))

                count = sum(1 for r in drows if has_coverage(r))
                coverage_metrics.append({
                    "key": metric.get("key", ""),
                    "label": metric.get("label", "Result available"),
                    "count": count,
                    "pct": round(100 * count / total) if total else 0,
                })
            if meta.get("result_rule") == "mapkit_candidates":
                def has_result(r):
                    try:
                        n = int((r.get("app_nearby_n_wide") or "0").strip())
                    except ValueError:
                        n = 0
                    return n > 0 or bool((r.get("app_nearby_top1") or "").strip())
                fill = sum(1 for r in drows if has_result(r))
            else:
                fill = sum(1 for r in drows if rep and (r.get(rep) or "").strip()) if rep else 0
            if meta.get("result_rule") == "mapkit_gt_labels":
                values = [(r.get(rep) or "").strip() for r in drows]
                category_counts = {
                    "canonical": sum(1 for value in values if value and value not in
                                     {"KOR", "SIM_MAPKIT", "NON_MAPKIT"}),
                    "similar": sum(1 for value in values if value == "SIM_MAPKIT"),
                    "not_found": sum(1 for value in values if value == "NON_MAPKIT"),
                }
                label_breakdown = {
                    "total": total,
                    "items": [
                        {"key": key, "count": count,
                         "pct": round(100 * count / total) if total else 0}
                        for key, count in category_counts.items()
                    ],
                    "excluded": {
                        "kor": sum(1 for value in values if value == "KOR"),
                        "empty": sum(1 for value in values if not value),
                    },
                }
            processed = (sum(1 for r in drows if str(r.get(processed_col) or "").strip().lower()
                             in {"1", "true", "yes", "done"})
                         if processed_col else None)
            sig[name] = {"label": meta.get("label", name), "col": rep, "cols": scols,
                         "fill": fill, "empty": total - fill,
                         "pct": round(100 * fill / total) if total else 0,
                         "processed": processed,
                         "unprocessed": ((total - processed) if processed is not None else None),
                         "processed_pct": ((round(100 * processed / total) if total else 0)
                                           if processed is not None else None),
                         "coverage_metrics": coverage_metrics,
                         "label_breakdown": label_breakdown,
                         "result_label": meta.get("result_label", "Result filled"),
                         "step": meta.get("step"), "status": meta.get("status", "ok")}
        src = sources.get(ds) or {}
        out.append({"key": ds, "label": src.get("label", ""), "count": total,
                    "known": ds in sources, "config_source": ds in sources,
                    "source_type": src.get("source_type", ""),
                    "photo_dir": _photo_dir_for(ds), "signals": sig})
    out.sort(key=lambda d: -d["count"])
    return {"datasets": out, "signals_meta": signals}


def _photo_url(dataset, photo):
    """Return a safely encoded URL for an existing photo below the data root."""
    if not photo:
        return ""
    photo_dir = _photo_dir_for(dataset)
    if not photo_dir:
        return ""
    from urllib.parse import quote
    root = os.path.realpath(DIRECTORY)
    base = os.path.realpath(os.path.join(root, photo_dir))
    target = os.path.realpath(os.path.join(base, photo))
    if not base.startswith(root + os.sep) or not target.startswith(base + os.sep):
        return ""
    if not os.path.isdir(base) or not os.path.isfile(target):
        return ""
    rel_dir = os.path.relpath(base, root).replace(os.sep, "/")
    rel_photo = os.path.relpath(target, base).replace(os.sep, "/")
    encoded = [quote(part, safe="") for part in (rel_dir + "/" + rel_photo).split("/")]
    return "/" + "/".join(encoded)


def _parse_candidates(top3):
    out = []
    for part in (top3 or "").split(" | "):
        part = part.strip()
        if not part:
            continue
        name, _, dist = part.rpartition("@")
        out.append({"name": (name or part).strip(), "dist": dist.strip()})
    return out


def build_records(dataset_filter):
    cfg = load_config()
    roll = cfg["confidence_rollup"]
    _, rows = read_eval_csv()
    # candidate lists from the MapKit probe
    cand = {}
    p = os.path.join(DIRECTORY, "ls_nearby_results.tsv")
    if os.path.exists(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 9 and c[0]:
                    cand[c[0]] = {"n": c[4], "rank": c[5], "dist": c[6], "top3": _parse_candidates(c[8])}

    def gt_info(r):
        """Provider-canonical label and its resolution status for display.

        Sentinel values are state markers, not labels.  In particular, do not
        manufacture a GT from input_place_name when the provider GT is blank.
        """
        provider = provider_for_row(r, cfg)
        gt, status = gt_resolution(r, provider)
        return provider, gt, status

    def outcome(r):
        provider, gt, gt_status = gt_info(r)
        conf = roll.get((r.get("gt_confidence") or "").strip(), "")
        rk = (r.get("app_poi_rank") or "").strip()
        if provider == "kakao_local":
            return ("korea_pending_kakao", "Awaiting Kakao candidates")
        if conf == "non_poi":
            return ("non_poi", "non_poi")
        if gt_status != "canonical":
            return (gt_status, f"GT excluded: {gt_status}")
        if not rk:
            return ("deferred", "deferred")
        if rk == "MISS":
            return ("retrieval", "retrieval miss")
        if rk == "1":
            return ("correct", "correct")
        if rk.isdigit():
            return ("selection", "selection miss")
        return ("other", rk)

    recs = []
    for r in rows:
        ds = r.get("dataset", "")
        if dataset_filter and dataset_filter != "all" and ds != dataset_filter:
            continue
        oc, ocl = outcome(r)
        photo = (r.get("photo") or "").strip()
        cd = cand.get(photo, {})
        ocr = (r.get("caption_ondevice") or "").strip()
        recs.append({
            "dataset": ds, "photo": photo, "photo_url": _photo_url(ds, photo),
            "gt": gt_info(r)[1],
            "gt_status": gt_info(r)[2],
            "provider": gt_info(r)[0],
            "input_place_name": (r.get("input_place_name") or "").strip(),
            "gt_confidence": (r.get("gt_confidence") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "lat": (r.get("capture_lat") or "").strip()[:9],
            "lon": (r.get("capture_lon") or "").strip()[:9],
            "ocr_text": ocr[:240],
            "baseline_pick": (r.get("app_nearby_top1") or "").strip(),
            "rank": (r.get("app_poi_rank") or "").strip(),
            "n_wide": (r.get("app_nearby_n_wide") or "").strip() or cd.get("n", ""),
            "dist": (r.get("app_poi_dist_m") or "").strip() or cd.get("dist", ""),
            "candidates": cd.get("top3", []),
            "outcome": oc, "oc_label": ocl,
        })
    return recs


def enrich_run_cases(run):
    """Attach current display context without altering historical run evidence."""
    _, rows = read_eval_csv()
    row_by_case = {
        ((r.get("dataset") or "").strip(), (r.get("photo") or "").strip()): r
        for r in rows
    }
    for case in run.get("cases") or []:
        dataset = (case.get("dataset") or "").strip()
        photo = (case.get("photo") or "").strip()
        row = row_by_case.get((dataset, photo), {})
        case["photo_url"] = _photo_url(dataset, photo)
        case["context"] = {
            "input_place_name": (row.get("input_place_name") or "").strip(),
            "category": (row.get("category") or "").strip(),
            "city": (row.get("city") or "").strip(),
            "country": (row.get("country") or "").strip(),
            "ocr_text": (row.get("caption_ondevice") or "").strip()[:240],
            "lat": (row.get("capture_lat") or "").strip()[:9],
            "lon": (row.get("capture_lon") or "").strip()[:9],
        }
    return run


def build_matchrate(dataset_filter="all", mode="exact"):
    """Live MVP candidate-retrieval API.

    Scoring is intentionally provider-aware and exact by default:
    South Korea is currently held out until Kakao Local data is available;
    all other countries use MapKit as the candidate provider. These are
    candidate coverage/rank metrics, not algorithm identification accuracy.
    provider_place_id is optional/nullable and not required for matching.
    """
    return evaluate_matchrate(
        dataset=dataset_filter or "all",
        mode=mode or "exact",
        rows=read_match_rows(CSV_PATH),
        candidates=load_match_candidates(MATCH_CANDIDATE_PATHS),
    )


# Static requests under these prefixes are dataset files served from DIRECTORY;
# everything else (the UI, templates) is tool code served from the repo.
DATA_PREFIXES = ("linkedspaces-photos", "photos", "union-city-trip", "generated")


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Base resolves under self.directory (the repo). When data lives in a
        # separate POI_DATA_DIR, remap only dataset prefixes there so the tool
        # always serves its own UI, not a stale copy in the data folder.
        resolved = super().translate_path(path)
        if DIRECTORY == REPO_DIR:
            return resolved
        rel = os.path.relpath(resolved, REPO_DIR)
        rel_url = rel.replace(os.sep, "/")
        allowed = set(DATA_PREFIXES) | _config_photo_dirs()
        if any(rel_url == prefix or rel_url.startswith(prefix.rstrip("/") + "/")
               for prefix in allowed):
            return os.path.join(DIRECTORY, rel)
        return resolved

    def end_headers(self):
        # Live dashboard: never let the browser serve a stale UI or API response.
        # Dataset files (photos) stay cacheable — large and rarely changing.
        p = self.path.split("?")[0]
        if p == "/" or p.startswith("/api/") or p.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, payload_obj, code=200):
        payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    _API_ERROR_TEXT = {
        "busy": "another data job is already running",
        "disabled": "this operation is disabled",
        "not_implemented": "this operation is not implemented",
        "unknown_step": "unknown extraction step",
        "not_found": "requested item was not found",
        "invalid_request": "invalid request",
        "invalid_provider": "invalid provider",
        "upload_save_failed": "upload could not be saved",
        "run_failed": "algorithm run failed",
        "internal_error": "server could not complete the request",
    }

    def _send_api_error(self, error_code, http_status, *, detail=None, **extra):
        """Send a stable code for localization and a legacy English message."""
        payload = {"ok": False, "error_code": error_code,
                   "error": self._API_ERROR_TEXT.get(error_code, "request failed"),
                   **extra}
        if detail:
            payload["detail"] = str(detail)
        self._send_json(payload, code=http_status)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/":
            self.send_response(302)
            self.send_header("Location", "/mvp-eval-ui.html")
            self.end_headers()
            return
        if route == "/api/runs":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            name = (q.get("name", [""])[0]).strip()
            version_raw = (q.get("version", [""])[0]).strip()
            try:
                if name or version_raw:
                    if not name or not version_raw:
                        self._send_api_error("invalid_request", 400, detail="name and version are required together")
                    else:
                        self._send_json({"run": enrich_run_cases(get_run(RUNS_DIR, name, int(version_raw)))})
                else:
                    self._send_json({"runs": list_runs(RUNS_DIR)})
            except RunError as e:
                self._send_api_error("not_found", 404, detail=e)
            except (TypeError, ValueError):
                self._send_api_error("invalid_request", 400, detail="version must be a positive integer")
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/poi-case-explorer":
            try:
                self._send_json(poi_case_explorer_data())
            except Exception as e:
                self.log_error("POI case explorer request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/poi-case-photo":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            photo = (q.get("photo", [""])[0]).strip()
            path = poi_case_photo(photo)
            if not path:
                self._send_api_error("not_found", 404, detail="photo not found")
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", self.guess_type(path))
                self.send_header("Content-Length", str(os.path.getsize(path)))
                self.end_headers()
                with open(path, "rb") as image:
                    shutil.copyfileobj(image, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if route == "/api/records":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ds = (q.get("dataset", ["all"])[0])
            try:
                self._send_json(build_records(ds))
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/matchrate":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ds = (q.get("dataset", ["all"])[0])
            mode = (q.get("mode", ["exact"])[0])
            try:
                self._send_json(build_matchrate(ds, mode))
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/overview":
            try:
                self._send_json(build_overview())
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/field-profile":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            group, dataset = (q.get("group", [""])[0]).strip(), q.get("dataset", ["__all"])[0]
            try:
                self._send_json(build_field_profile(group, dataset))
            except ValueError as e:
                self._send_api_error("invalid_request", 400, detail=e)
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route == "/api/datasets":
            try:
                self._send_json(build_datasets())
            except Exception as e:
                self.log_error("API request failed: %s", e)
                self._send_api_error("internal_error", 500)
            return
        if route in ("/api/jobs/status", "/api/gt/classify/status"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            job_id = (q.get("job_id", [""])[0]).strip()
            job = _jobs.get(job_id)
            if not job:
                self._send_api_error("not_found", 404, detail="unknown job_id")
                return
            self._send_json({"ok": True, **_job_public(job)})
            return
        if route in ("/api/jobs", "/api/gt/classify"):
            self._send_json({"ok": True, "active": _active["id"],
                             "steps": {s: (v.get("disabled") or "ok") for s, v in STEP_REGISTRY.items()},
                             "jobs": [_job_public(j) for j in _jobs.values()]})
            return
        if route == "/api/case":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ds = (q.get("dataset", [""])[0]).strip()
            ph = (q.get("photo", [""])[0]).strip()
            d = case_detail(ds, ph)
            if d is None:
                self._send_json({"error": "case not found"}, code=404)
            else:
                self._send_json(d)
            return
        if route == "/api/gt/reconcile":
            try:
                self._send_json(gt_reconcile_queue())
            except Exception as e:
                self._send_json({"total_non_mapkit": 0, "done": 0, "remaining": 0,
                                 "cases": [], "error": str(e)}, code=200)
            return
        super().do_GET()

    def _read_body(self, max_bytes):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_api_error("invalid_request", 400, detail="invalid Content-Length")
            return None
        if content_length <= 0:
            self._send_api_error("invalid_request", 400, detail="empty request body")
            return None
        if content_length > max_bytes:
            self._send_api_error("invalid_request", 413, detail="request body is too large", max_bytes=max_bytes)
            return None
        return self.rfile.read(content_length)

    def do_DELETE(self):
        from urllib.parse import urlparse, parse_qs
        route = self.path.split("?")[0]
        if route != "/api/runs":
            self._send_api_error("not_found", 404)
            return
        q = parse_qs(urlparse(self.path).query)
        name = (q.get("name", [""])[0]).strip()
        version_raw = (q.get("version", [""])[0]).strip()
        if not name or not version_raw:
            self._send_api_error("invalid_request", 400, detail="name and version are required")
            return
        try:
            deleted = delete_run(RUNS_DIR, name, int(version_raw))
            self._send_json({"ok": True, "deleted": deleted})
        except RunError as e:
            self._send_api_error("not_found", 404, detail=e)
        except (TypeError, ValueError):
            self._send_api_error("invalid_request", 400, detail="version must be a positive integer")
        except Exception as e:
            self.log_error("API request failed: %s", e)
            self._send_api_error("internal_error", 500)

    def _handle_seed(self):
        """Onboarding: materialize the bundled seed (initial dataset + baseline
        runs) into the data dir when the install is empty. Idempotent."""
        import shutil
        raw = self._read_body(1024 * 1024)
        if raw is None:
            raw = b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        preset = (payload or {}).get("preset", "default")
        seed_dir = os.path.join(REPO_DIR, "poi-data-seed")
        if not os.path.isdir(seed_dir):
            self._send_json({"ok": False, "message": "seed bundle not found"}, code=500)
            return
        if os.path.isfile(CSV_PATH):
            self._send_json({"ok": True, "message": "already seeded"}, code=200)
            return
        try:
            os.makedirs(DIRECTORY, exist_ok=True)
            for name in ("eval_set_reconciled.csv", "dashboard_config.json"):
                src = os.path.join(seed_dir, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(DIRECTORY, name))
            seed_runs = os.path.join(seed_dir, "generated", "runs")
            if os.path.isdir(seed_runs):
                os.makedirs(RUNS_DIR, exist_ok=True)
                for fn in os.listdir(seed_runs):
                    if fn.endswith(".json"):
                        shutil.copy2(os.path.join(seed_runs, fn), os.path.join(RUNS_DIR, fn))
            self._send_json({"ok": True, "message": f"seeded from {preset}"}, code=200)
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, code=500)

    def _handle_gt_reconcile_save(self):
        """Persist a manual GT↔MapKit match chosen in the reconciliation UI."""
        raw = self._read_body(1024 * 1024)
        if raw is None:
            raw = b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        dataset = str((payload or {}).get("dataset", ""))
        photo = str((payload or {}).get("photo", ""))
        gt = str((payload or {}).get("gt", ""))
        chosen = str((payload or {}).get("chosen", "") or "").strip()
        # manual = the name was typed in (no candidate to pick), not chosen from the list
        manual = bool((payload or {}).get("manual"))
        if not photo:
            self._send_json({"ok": False, "message": "photo required"}, code=400)
            return
        path = _gt_overrides_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            new_file = not os.path.isfile(path)
            fields = ["dataset", "photo", "gt", "chosen", "chosen_none", "manual", "ts"]
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
                if new_file:
                    w.writeheader()
                w.writerow({"dataset": dataset, "photo": photo, "gt": gt, "chosen": chosen,
                            "chosen_none": "" if chosen else "1",
                            "manual": "1" if manual else "",
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            q = gt_reconcile_queue(limit=1)
            self._send_json({"ok": True, "done": q["done"], "remaining": q["remaining"]}, code=200)
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, code=500)

    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/gt/reconcile":
            self._handle_gt_reconcile_save()
            return
        if route == "/api/mapkit/probe":
            raw = self._read_body(64 * 1024) or b"{}"
            try:
                payload = json.loads(raw or b"{}")
                lat = float(payload["lat"])
                lon = float(payload["lon"])
            except Exception:
                self._send_json({"ok": False, "message": "lat and lon (numbers) required"}, code=400)
                return
            self._send_json(mapkit_probe(lat, lon))
            return
        if route == "/api/run":
            self._handle_run()
            return
        if route == "/api/jobs":
            self._handle_job_start()
            return
        if route == "/api/ingest":
            self._handle_ingest()
            return
        if route == "/api/gt/classify":
            self._handle_gt_classify_shim()
            return
        if route == "/api/seed":
            self._handle_seed()
            return
        if route != "/api/validate-upload-package":
            self.send_error(404)
            return

        upload = self._read_body(500 * 1024 * 1024)
        if upload is None:
            return
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(upload)
                tmp_path = tmp.name
            result = validate_zip(tmp_path)
            self._send_json(result, code=200 if result.get("ok") else 422)
        except ValidationError as e:
            self._send_json({"ok": False, "errors": [{"code": "invalid_zip", "message": str(e)}], "warnings": [], "row_flags": []}, code=400)
        except Exception as e:
            self.log_error("API request failed: %s", e)
            self._send_api_error("internal_error", 500)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    _JOB_ERR_CODE = {"busy": 409, "disabled": 501, "unknown_step": 400}

    def _start_job(self, step, params, extra_resp=None):
        """reserve → respond+flush → launch. Shared by generic + shim handlers."""
        job_id, err = reserve(step, params)
        if err:
            self._send_api_error(err[0], self._JOB_ERR_CODE.get(err[0], 400),
                                 detail=err[1], step=step)
            return False
        resp = {"ok": True, "job_id": job_id, "step": step, "status": "running",
                "status_url": f"/api/jobs/status?job_id={job_id}"}
        resp.update(extra_resp or {})
        # Respond and flush BEFORE forking the worker, so the caller's connection
        # is fully served and never held open by the (minutes-long) subprocess.
        self._send_json(resp)
        try:
            self.wfile.flush()
        except Exception:
            pass
        launch(job_id)
        return True

    def _handle_job_start(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        step = (q.get("step", [""])[0]).strip()
        params = {
            "dataset": (q.get("dataset", [""])[0]).strip() or None,
            "only_empty": (q.get("only_empty", ["0"])[0]).strip() in ("1", "true", "yes"),
        }
        # Optional JSON body may carry step and extra params (delete flags).
        try:
            cl = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            cl = 0
        if cl > 0:
            try:
                b = json.loads(self.rfile.read(cl).decode("utf-8"))
                if not step:
                    step = (b.get("step") or "").strip()
                for k in ("dataset", "only_empty", "delete_photos", "remove_config_source"):
                    if k in b:
                        params[k] = b[k]
            except Exception:
                pass
        self._start_job(step, params)

    def _handle_ingest(self):
        # Save the uploaded ZIP as a non-public temporary input, then run ingest
        # as a tracked job (append rows + copy photos + register source). The job
        # removes the archive after success or failure and is mutually exclusive
        # with all other CSV-mutating jobs via the single lock.
        from urllib.parse import urlparse, parse_qs
        upload = self._read_body(500 * 1024 * 1024)
        if upload is None:
            return
        zip_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(upload)
                zip_path = tmp.name
        except Exception as e:
            if zip_path:
                try:
                    os.unlink(zip_path)
                except OSError:
                    pass
            self.log_error("could not save upload: %s", e)
            self._send_api_error("upload_save_failed", 500)
            return
        q = parse_qs(urlparse(self.path).query)
        dataset = (q.get("dataset", [""])[0]).strip() or None
        if not self._start_job("ingest", {"zip_path": zip_path, "dataset": dataset}):
            try:
                os.unlink(zip_path)
            except FileNotFoundError:
                pass
            except OSError:
                # The request already reports the reservation failure. A failed
                # cleanup is intentionally not hidden, but cannot safely trigger
                # a second HTTP response here.
                self.log_error("could not remove rejected ingest upload %s", zip_path)

    def _handle_gt_classify_shim(self):
        # Back-compat: /api/gt/classify?provider=mapkit → step=gt_mapkit.
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        provider = (q.get("provider", [""])[0]).strip()
        try:
            cl = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            cl = 0
        if cl > 0 and not provider:
            try:
                provider = (json.loads(self.rfile.read(cl).decode("utf-8")).get("provider") or "").strip()
            except Exception:
                pass
        step = {"mapkit": "gt_mapkit", "kakao": "gt_kakao"}.get(provider)
        if not step:
            self._send_api_error("invalid_provider", 400,
                                 detail=f"unknown provider {provider!r}")
            return
        self._start_job(step, {}, extra_resp={"provider": provider})

    def _handle_run(self):
        body = self._read_body(20 * 1024 * 1024)
        if body is None:
            return
        try:
            req = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_api_error("invalid_request", 400, detail=f"invalid JSON body: {e}")
            return
        if not isinstance(req, dict):
            self._send_api_error("invalid_request", 400, detail="JSON body must be an object")
            return
        if "params" in req and not isinstance(req["params"], list):
            self._send_api_error("invalid_request", 400, detail="params must be an array")
            return
        if "params" in req and not all(isinstance(p, str) for p in req["params"]):
            self._send_api_error("invalid_request", 400,
                                 detail="params must contain only string signal keys")
            return
        try:
            result = run_submission(
                name=(req.get("name") or "").strip(),
                script_text=req.get("script_text") or "",
                lang=(req.get("lang") or "python").strip(),
                dataset=(req.get("scope") or "all").strip(),
                mode=(req.get("mode") or "exact").strip(),
                params=req.get("params"),
                save_mode=(req.get("save_mode") or "auto").strip(),
                csv_path=CSV_PATH,
                config_path=config_read_path(),
                candidate_paths=MATCH_CANDIDATE_PATHS,
                runs_dir=RUNS_DIR,
                candidate_limit=req.get("candidate_limit"),
            )
            self._send_json({"ok": True, **result})
        except RunError as e:
            self._send_api_error("run_failed", 422, detail=e)
        except Exception as e:
            self.log_error("algorithm run failed: %s", e)
            self._send_api_error("internal_error", 500)


if __name__ == "__main__":
    # Serve tool code (UI/templates) from the repo; dataset files are remapped
    # to DIRECTORY by Handler.translate_path.
    os.chdir(REPO_DIR)
    handler = functools.partial(Handler, directory=REPO_DIR)
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    # Long algorithm submissions must not block status/static/API requests.
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        where = REPO_DIR if DIRECTORY == REPO_DIR else f"{REPO_DIR} (UI) + {DIRECTORY} (data)"
        print(f"serving {where} at http://127.0.0.1:{PORT}  — open /mvp-eval-ui.html")
        httpd.serve_forever()
