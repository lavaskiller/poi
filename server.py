import http.server, socketserver, functools, json, csv, os, sys, tempfile, urllib.parse
import threading, subprocess, uuid, time, math, shutil, queue, statistics, io, zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_DIR, "tools"))
from validate_upload_package import (
    validate_zip, ValidationError, build_dataset_template_zip,
    _norm_zip_name, _is_unsafe_path,
)
from match_score import (
    evaluate as evaluate_matchrate,
    load_candidates as load_match_candidates,
    read_rows as read_match_rows,
    provider_for_row,
    gt_resolution,
    canonical_country,
    load_gt_mapkit_overrides,
    overlay_gt_mapkit_overrides,
)
from run_algorithm import run_submission, list_runs, get_run, delete_run, RunError
from gt_classify_common import read_csv as gc_read_csv, write_csv as gc_write_csv, backup_csv as gc_backup_csv
import run_algorithm as algorithm
import match_score as match_score

# Data root. Resolution order:
#   1. POI_DATA_DIR — explicit override.
#   2. repo-local poi-data/ — the modern bundle, when it holds the reconciled CSV.
#   3. repo root — legacy layout, only when a dataset actually sits there.
#   4. otherwise (fresh / empty install) default to poi-data/ so the onboarding
#      seed materializes into the gitignored bundle — never the tracked repo root.
_repo_data_dir = os.path.join(REPO_DIR, "poi-data")


def _resolve_data_dir():
    env = os.environ.get("POI_DATA_DIR")
    if env:
        return env
    if os.path.isfile(os.path.join(_repo_data_dir, "eval_set_reconciled.csv")):
        return _repo_data_dir
    if os.path.isfile(os.path.join(REPO_DIR, "eval_set_reconciled.csv")):
        return REPO_DIR  # legacy repository-root layout
    return _repo_data_dir  # fresh install: seed target is poi-data/, not REPO_DIR


DIRECTORY = _resolve_data_dir()
PORT = int(os.environ.get("POI_PORT", "8420"))
# Optional shared secret for mutating requests. Empty = local-trust mode (default).
# Set POI_API_TOKEN and send Authorization: Bearer <token> or X-POI-Token.
API_TOKEN = (os.environ.get("POI_API_TOKEN") or "").strip()
# Comma-separated Origin allowlist for browser POSTs (CSRF-ish). Defaults to
# common local dev origins; empty string disables the check.
_origins_raw = os.environ.get("POI_ALLOWED_ORIGINS")
if _origins_raw is None:
    ALLOWED_ORIGINS = {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8420",
        "http://localhost:8420",
    }
elif not _origins_raw.strip():
    ALLOWED_ORIGINS = None  # explicitly disabled
else:
    ALLOWED_ORIGINS = {o.strip() for o in _origins_raw.split(",") if o.strip()}
# Bind address — default loopback only. Set POI_BIND=0.0.0.0 only intentionally.
BIND_HOST = (os.environ.get("POI_BIND") or "127.0.0.1").strip() or "127.0.0.1"
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

# Onboarding seed bundle. Lives at the repo root and is gitignored (real user
# data, shared privately). Onboarding discovers what is on disk here and offers
# it as a dropdown; an absent bundle is surfaced to the UI, not a hard error.
SEED_DIR = os.path.join(REPO_DIR, "poi-data-seed")


def _seed_preset_summary(src_dir):
    """Cheap on-disk summary for a seed source dir: (rows, runs)."""
    rows = 0
    csv_path = os.path.join(src_dir, "eval_set_reconciled.csv")
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            rows = max(0, sum(1 for _ in f) - 1)  # minus header
    except OSError:
        rows = 0
    runs = 0
    runs_dir = os.path.join(src_dir, "generated", "runs")
    try:
        runs = sum(1 for fn in os.listdir(runs_dir) if fn.endswith(".json"))
    except OSError:
        runs = 0
    return rows, runs


def _seed_source_dir(preset_id):
    """Resolve a preset id to its seed source dir, or None if unavailable.

    A preset maps to a subdirectory of SEED_DIR via the optional presets.json
    manifest (``path``); the flat/default bundle is SEED_DIR itself. A source is
    valid only when it actually holds eval_set_reconciled.csv.
    """
    for p in discover_seed_presets()["presets"]:
        if p["id"] == preset_id and p["available"]:
            return os.path.join(SEED_DIR, p.get("_path") or ".")
    return None


def discover_seed_presets():
    """Enumerate onboarding seed presets from disk for the dropdown.

    Uses SEED_DIR/presets.json when present (supports multiple named bundles);
    otherwise synthesizes a single ``default`` preset from the flat bundle.
    Each preset reports ``available`` + a cheap (rows, runs) summary so the UI
    can render and gate the dropdown without guessing.
    """
    bundle_present = os.path.isdir(SEED_DIR)
    seed_rel = os.path.relpath(SEED_DIR, REPO_DIR)
    if not bundle_present:
        return {"bundle_present": False, "seed_path": seed_rel, "presets": []}

    raw_presets = []
    manifest = os.path.join(SEED_DIR, "presets.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
            raw_presets = data.get("presets", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            raw_presets = []
    if not raw_presets:
        raw_presets = [{
            "id": "default",
            "label": "Bundled default setup",
            "desc": "Evaluation set + baseline runs + case photos.",
            "path": ".",
        }]

    presets = []
    for p in raw_presets:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        sub = p.get("path") or "."
        src_dir = os.path.join(SEED_DIR, sub)
        available = os.path.isfile(os.path.join(src_dir, "eval_set_reconciled.csv"))
        rows, runs = _seed_preset_summary(src_dir) if available else (0, 0)
        presets.append({
            "id": str(p["id"]),
            "label": p.get("label") or str(p["id"]),
            "desc": p.get("desc") or "",
            "available": available,
            "rows": rows,
            "runs": runs,
            "_path": sub,
        })
    return {"bundle_present": True, "seed_path": seed_rel, "presets": presets}


# Uploaded seed bundle limits (zip-bomb guard). Photo-inclusive seeds are ~0.4–1 GiB.
_SEED_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_SEED_MAX_FILES = 20000
_SEED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
# Known / allowed photo-dir roots that may be extracted from a seed bundle.
_SEED_PHOTO_DIR_PREFIXES = (
    "photos/",
    "linkedspaces-photos/",
    "poi-dataset-20260708-photos/",
    "union-city-trip/",
)


def _seed_allowed_photo_prefixes(cfg=None):
    """Return path prefixes under the data root that may hold seed photos."""
    prefixes = set(_SEED_PHOTO_DIR_PREFIXES)
    try:
        cfg = cfg or load_config()
        for src in (cfg.get("sources") or {}).values():
            pdir = (src or {}).get("photo_dir") or ""
            pdir = str(pdir).strip().strip("/\\").replace("\\", "/")
            if pdir and ".." not in pdir.split("/"):
                prefixes.add(pdir.rstrip("/") + "/")
    except Exception:
        pass
    return prefixes


def _seed_is_photo_member(rel_path):
    """True if rel_path is an image under an allowed photo_dir prefix."""
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel or _is_unsafe_path(rel):
        return False
    ext = PurePosixPath(rel).suffix.lower()
    if ext not in _SEED_PHOTO_EXTS:
        return False
    for prefix in _seed_allowed_photo_prefixes():
        if rel.startswith(prefix):
            return True
    return False


def _copy_seed_photos(seed_dir, dest_root):
    """Copy photo trees from a filesystem seed bundle into the live data root.

    Returns (files_copied, bytes_copied).
    """
    import shutil as _shutil
    n, nbytes = 0, 0
    seed_dir = os.path.abspath(seed_dir)
    dest_root = os.path.abspath(dest_root)
    for dirpath, _dirnames, filenames in os.walk(seed_dir):
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, seed_dir).replace("\\", "/")
            if not _seed_is_photo_member(rel):
                continue
            dst = os.path.join(dest_root, rel)
            # zip-slip / escape guard
            if not os.path.abspath(dst).startswith(dest_root + os.sep):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _shutil.copy2(src, dst)
            n += 1
            try:
                nbytes += os.path.getsize(src)
            except OSError:
                pass
    return n, nbytes


def _apply_seed_bundle(zip_bytes):
    """Materialize a drag-and-dropped seed-bundle ZIP into the live data root.

    Accepts the same shape as poi-data-seed/ (files at the ZIP root or nested
    under a single top folder): eval_set_reconciled.csv (required),
    dashboard_config.json (optional), generated/runs/*.json (optional),
    and photo trees under known photo_dir prefixes (optional, for image
    display). Safe against zip-slip and zip-bombs; idempotent; never overwrites
    the tracked repo config template.
    Returns a JSON-ready dict with a ``code`` for the HTTP status.
    """
    if os.path.isfile(CSV_PATH):
        return {"ok": True, "message": "already seeded", "code": 200}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return {"ok": False, "message": "not a valid ZIP archive", "code": 400}
    with zf:
        by_name, total = {}, 0
        for zi in zf.infolist():
            name = _norm_zip_name(zi.filename)
            if not name or name.endswith("/"):
                continue
            if "__MACOSX" in name.split("/"):
                continue
            if _is_unsafe_path(name):
                return {"ok": False, "message": f"unsafe path in ZIP: {zi.filename}", "code": 400}
            total += zi.file_size
            if zi.file_size > _SEED_MAX_TOTAL_BYTES or total > _SEED_MAX_TOTAL_BYTES:
                return {"ok": False, "message": "seed bundle too large", "code": 413}
            by_name[name] = zi
        if len(by_name) > _SEED_MAX_FILES:
            return {"ok": False, "message": "too many files in ZIP", "code": 413}

        # Locate the bundle base by the required CSV (shallowest match wins).
        csv_matches = sorted(
            (n for n in by_name if PurePosixPath(n).name == "eval_set_reconciled.csv"),
            key=lambda n: len(PurePosixPath(n).parts),
        )
        if not csv_matches:
            return {"ok": False, "message": "eval_set_reconciled.csv not found in bundle", "code": 400}
        base_dir = str(PurePosixPath(csv_matches[0]).parent)
        base = "" if base_dir == "." else base_dir + "/"

        os.makedirs(DIRECTORY, exist_ok=True)
        for rel in ("eval_set_reconciled.csv", "dashboard_config.json"):
            zi = by_name.get(base + rel)
            if zi is None:
                continue
            dst = os.path.join(DIRECTORY, rel)
            if os.path.abspath(dst) == os.path.abspath(REPO_CONFIG_PATH):
                continue  # never clobber the tracked config template
            with zf.open(zi) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)

        runs, runs_prefix = 0, base + "generated/runs/"
        run_members = [(n, zi) for n, zi in by_name.items()
                       if n.startswith(runs_prefix) and n.endswith(".json")
                       and "/" not in n[len(runs_prefix):]]
        if run_members:
            os.makedirs(RUNS_DIR, exist_ok=True)
            for n, zi in run_members:
                with zf.open(zi) as src, open(os.path.join(RUNS_DIR, PurePosixPath(n).name), "wb") as out:
                    shutil.copyfileobj(src, out)
                runs += 1

        # Photos: any image under allowed photo_dir prefixes (relative to base).
        photos = 0
        for n, zi in by_name.items():
            if not n.startswith(base):
                continue
            rel = n[len(base):]
            if not _seed_is_photo_member(rel):
                continue
            dst = os.path.join(DIRECTORY, rel)
            if not os.path.abspath(dst).startswith(os.path.abspath(DIRECTORY) + os.sep):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with zf.open(zi) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            photos += 1

    rows, _ = _seed_preset_summary(DIRECTORY)
    msg = f"seeded from upload ({rows} rows · {runs} baselines"
    if photos:
        msg += f" · {photos} photos"
    msg += ")"
    return {"ok": True, "rows": rows, "runs": runs, "photos": photos,
            "message": msg, "code": 200}


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
    """Manual GT↔MapKit matches saved by the reconciliation UI, keyed by (dataset, photo).

    Shared implementation with match_score so Reconcile queue skips and
    matchrate / algorithm scoring all see the same override set.
    """
    return load_gt_mapkit_overrides(_gt_overrides_path())


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
                "image": (
                    f"/api/poi-case-photo?dataset={urllib.parse.quote(dataset)}"
                    f"&photo={urllib.parse.quote(photo)}&thumb=1&w=480"
                ),
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


# Default / app-path wide radius; optional override for sparse-list investigate.
MAPKIT_DEFAULT_WIDE_RADIUS_M = 250.0
MAPKIT_MAX_WIDE_RADIUS_M = 5000.0


def mapkit_probe(lat, lon, radius_m=None):
    """Live MapKit nearby query for an arbitrary coordinate (Investigate flow).

    Runs ``ls_mapkit_probe.swift`` — slow (~20–30s: swift compile + network).

    ``radius_m`` optionally overrides the probe's *wide* radius (default 250 m).
    Used by Case inspector sparse-list expand (500 / 1000 / 2000 m). Batch eval
    and Reconcile keep the default when omitted.
    """
    swift_file = os.path.join(REPO_DIR, "tools", "swift", "ls_mapkit_probe.swift")
    if not os.path.isfile(swift_file):
        return {"ok": False, "message": "probe script missing", "candidates": []}
    wide = MAPKIT_DEFAULT_WIDE_RADIUS_M
    if radius_m is not None:
        try:
            wide = float(radius_m)
        except (TypeError, ValueError):
            return {"ok": False, "message": "radius_m must be a number", "candidates": []}
        if not (0 < wide <= MAPKIT_MAX_WIDE_RADIUS_M):
            return {
                "ok": False,
                "message": "radius_m must be in (0, %s]" % int(MAPKIT_MAX_WIDE_RADIUS_M),
                "candidates": [],
            }
    in_tsv = out_tsv = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, newline="") as f:
            f.write("photo\tlat\tlon\tkw\n")
            f.write("probe\t%s\t%s\t\n" % (lat, lon))
            in_tsv = f.name
        out_tsv = in_tsv + ".out"
        cmd = ["swift", swift_file, in_tsv]
        if radius_m is not None:
            cmd.append(str(wide))
        with open(out_tsv, "w", encoding="utf-8") as out:
            proc = subprocess.run(cmd, stdout=out,
                                  stderr=subprocess.PIPE, text=True, timeout=150)
        if proc.returncode != 0:
            return {"ok": False, "message": "probe failed: %s" % (proc.stderr or "")[:200],
                    "candidates": [], "radius_m": wide}
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
        return {"ok": True, "lat": lat, "lon": lon, "radius_m": wide, "candidates": norm}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "probe timed out", "candidates": [], "radius_m": wide}
    except Exception as e:
        return {"ok": False, "message": str(e), "candidates": [], "radius_m": wide}
    finally:
        for p in (in_tsv, out_tsv):
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass


# Soft cap for Case inspector lists (retrieval diagnosis needs more than top-3;
# full MapKit wide lists are routinely 20–50).
_CASE_CANDIDATE_DISPLAY_CAP = 50


def _norm_case_candidates(raw, *, limit=None):
    """Normalize candidate dicts for the Case inspector API."""
    out = []
    for i, c in enumerate(raw or []):
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "rank": c.get("rank") or i + 1,
            "name": name,
            "distance": c.get("distance") if c.get("distance") is not None else c.get("distance_m"),
            "category": c.get("category") or "",
            "lat": c.get("lat"),
            "lon": c.get("lon"),
        })
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def _case_mapkit_candidates(dataset, photo, row=None):
    """MapKit nearby list for a case — same artifact algorithms score against.

    Priority:
      1. Active MapKit / Kakao candidate JSONL (MATCH_CANDIDATE_PATHS)
      2. Legacy probe TSV fallback (``_load_original_mapkit_outputs``)

    Returns ``(candidates, meta)`` where meta has source / total / provider.
    """
    photo_base = os.path.basename((photo or "").strip())
    ds = (dataset or "").strip()
    cfg = {}
    try:
        cfg = match_score.load_config(config_read_path())
    except Exception:
        cfg = {}
    provider = "mapkit"
    if row is not None:
        try:
            p = provider_for_row(row, cfg)
            # unresolved must not fall back to mapkit candidate lookup
            if p and p != "unresolved":
                provider = p
        except Exception:
            provider = "mapkit"

    # 1) Versioned full-candidate snapshot (what predict() receives).
    try:
        grouped = load_match_candidates(MATCH_CANDIDATE_PATHS)
    except Exception:
        grouped = {}
    qualified = (provider, f"{ds}/{photo_base}") if ds else None
    bare = (provider, photo_base)
    source_key = None
    raw = []
    if qualified and qualified in grouped:
        raw = grouped[qualified]
        source_key = "active_snapshot"
    elif bare in grouped:
        raw = grouped[bare]
        source_key = "active_snapshot"
    if source_key:
        cands = _norm_case_candidates(raw, limit=_CASE_CANDIDATE_DISPLAY_CAP)
        return cands, {
            "source": source_key,
            "provider": provider,
            "total": len(raw),
            "shown": len(cands),
        }

    # 2) Legacy probe TSV (ls / rerun) — often top-N only, but better than empty.
    legacy = (_load_original_mapkit_outputs(limit=_CASE_CANDIDATE_DISPLAY_CAP)
              .get(photo_base) or {})
    raw = legacy.get("candidates") or []
    cands = _norm_case_candidates(raw, limit=_CASE_CANDIDATE_DISPLAY_CAP)
    total = len(raw)
    try:
        reported = int(legacy.get("reportedWideCount") or 0)
        if reported > total:
            total = reported
    except (TypeError, ValueError):
        pass
    return cands, {
        "source": legacy.get("source") or "none",
        "provider": "mapkit",
        "total": total,
        "shown": len(cands),
    }


def case_detail(dataset, photo, run_name=None, version=None):
    """Single-case detail for the Case inspector — composed from stable sources
    (eval CSV row + MapKit candidate list + a specific or best run's prediction).

    When run_name + version are provided, predictions come from that run so deep
    links stay reproducible even after a newer best run appears.
    """
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
    # Read-time reconcile overlay (same as matchrate) so the inspector shows the
    # effective MapKit GT after a manual match, not the stale NON_MAPKIT cell.
    overlaid_rows, _ = overlay_gt_mapkit_overrides([row], path=_gt_overrides_path())
    row = overlaid_rows[0] if overlaid_rows else row
    chosen, pred, full_run = None, {}, None
    try:
        if run_name and version is not None:
            full_run = get_run(RUNS_DIR, run_name, int(version))
            chosen = {"name": full_run.get("name") or run_name,
                      "version": full_run.get("version") or int(version)}
            for c in full_run.get("cases", []):
                if c.get("dataset") == dataset and c.get("photo") == photo:
                    pred = c
                    break
        else:
            scored = [r for r in list_runs(RUNS_DIR) if isinstance(r.get("accuracy_pct"), (int, float))]
            best = max(scored, key=lambda r: r.get("accuracy_pct") or 0) if scored else None
            if best:
                chosen = {"name": best["name"], "version": best["version"]}
                full_run = get_run(RUNS_DIR, best["name"], best["version"])
                for c in full_run.get("cases", []):
                    if c.get("dataset") == dataset and c.get("photo") == photo:
                        pred = c
                        break
    except Exception:
        chosen, pred, full_run = None, {}, None

    cand, cand_meta = _case_mapkit_candidates(dataset, photo, row)
    run_limit = None
    if full_run is not None:
        try:
            lim = full_run.get("candidate_limit")
            run_limit = int(lim) if lim is not None else None
        except (TypeError, ValueError):
            run_limit = None
    # Annotate which ranks were inside the run's candidate window (selection scope).
    if run_limit is not None and run_limit > 0:
        for c in cand:
            try:
                rk = int(c.get("rank") or 0)
            except (TypeError, ValueError):
                rk = 0
            c["in_run_window"] = rk > 0 and rk <= run_limit

    lat = (row.get("capture_lat") or "").strip()[:9]
    lon = (row.get("capture_lon") or "").strip()[:9]
    nearby_signal = (row.get("app_nearby_n_wide") or "").strip()
    if not nearby_signal and cand_meta.get("total"):
        nearby_signal = str(cand_meta["total"])
    return {
        "dataset": dataset, "photo": photo,
        "image": f"/api/poi-case-photo?dataset={urllib.parse.quote(dataset)}&photo={urllib.parse.quote(photo)}",
        "gt": (row.get("input_place_name") or "").strip(),
        "gt_mapkit": (row.get("gt_mapkit") or "").strip(),
        "prediction": pred.get("prediction", ""),
        "reason": pred.get("reason", ""),
        "match_kind": pred.get("match_kind", ""),
        "correct": bool(pred.get("correct")),
        "run": chosen,
        "candidate_limit": run_limit,
        "candidate_total": cand_meta.get("total", len(cand)),
        "candidate_source": cand_meta.get("source") or "none",
        "lat": lat, "lon": lon,
        "signals": {
            "gps": (", ".join(x for x in (lat, lon) if x)),
            "ocr": (row.get("caption_ondevice") or "").strip()[:240],
            "nearby": nearby_signal,
            "category": (row.get("category") or "").strip(),
        },
        "candidates": cand,
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


def poi_case_photo(photo, dataset=None):
    """Locate an original image without a copied report-asset directory.

    When ``dataset`` is known, prefer that source's ``photo_dir`` so same-basename
    collisions across datasets resolve to the right file.

    Name resolution is unified via ``tools/photo_names.photo_name_aliases``:
    historical LinkedSpaces long names, preferred short names, and extension
    variants (.JPEG/.jpg) all resolve to the same file when present.
    """
    if not photo or os.path.basename(photo) != photo:
        return None
    try:
        from photo_names import photo_name_aliases, provenance_basename
    except ImportError:
        sys.path.insert(0, os.path.join(REPO_DIR, "tools"))
        from photo_names import photo_name_aliases, provenance_basename

    aliases = photo_name_aliases(photo)
    roots = []
    if dataset:
        pdir = _photo_dir_for(dataset)
        if pdir:
            roots.append(os.path.join(DIRECTORY, pdir))
    roots.extend(
        os.path.join(DIRECTORY, name)
        for name in (
            "linkedspaces-photos",
            "photos",
            "poi-dataset-20260708-photos",
            "union-city-trip/photos",
        )
    )
    # Config-registered upload dirs (may not be in the hardcoded list).
    try:
        for pdir in sorted(_config_photo_dirs() or []):
            if pdir:
                roots.append(os.path.join(DIRECTORY, pdir))
    except Exception:
        pass
    # Legacy: long export names on disk vs short provenance form in some tools.
    preferred = provenance_basename(photo)
    seen = set()
    for root in roots:
        root = os.path.realpath(root)
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        # 1) direct path hits for every alias (includes local 0001.jpg keys)
        for name in aliases:
            direct = os.path.join(root, name)
            if os.path.isfile(direct):
                return direct
        # 2) recursive exact basename hits (nested photo dirs)
        for name in aliases:
            found = next((p for p in Path(root).rglob(name) if p.is_file()), None)
            if found:
                return str(found)
        # 3) long-on-disk ↔ stripped provenance (pre-local-id history)
        for path in Path(root).rglob("*"):
            if path.is_file() and provenance_basename(path.name) == preferred:
                return str(path)
    return None


def _thumb_cache_path(src_path, max_px):
    """Deterministic cache path under generated/thumbs for a source image."""
    import hashlib
    try:
        st = os.stat(src_path)
        key = f"{os.path.realpath(src_path)}|{st.st_mtime_ns}|{st.st_size}|{max_px}"
    except OSError:
        key = f"{src_path}|{max_px}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    cache_dir = os.path.join(DIRECTORY, "generated", "thumbs")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{digest}_w{int(max_px)}.jpg")


def poi_case_photo_thumb(src_path, max_px=360, quality=82):
    """Return a JPEG thumbnail path (cached), or None if generation fails.

    Mirrors tools/render_case_types.thumb_data_uri geometry: long edge ≤ max_px,
    EXIF-aware, LANCZOS. Falls back to None so the caller can serve the original.
    """
    if not src_path or not os.path.isfile(src_path):
        return None
    max_px = max(64, min(int(max_px or 360), 1280))
    cache = _thumb_cache_path(src_path, max_px)
    if os.path.isfile(cache) and os.path.getmtime(cache) >= os.path.getmtime(src_path):
        return cache
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            resample = getattr(Image, "Resampling", Image).LANCZOS
            im.thumbnail((max_px, max_px), resample)
            tmp = cache + ".tmp"
            im.save(tmp, format="JPEG", quality=quality, optimize=True)
            os.replace(tmp, cache)
        return cache
    except Exception:
        try:
            if os.path.isfile(cache + ".tmp"):
                os.unlink(cache + ".tmp")
        except OSError:
            pass
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
    "geocode":        {"script": os.path.join(REPO_DIR, "tools", "rerun_geocode.py")},
    # Intentionally unavailable rather than pretending enrichment ran.
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
    """EXIF → geocode (country for provider routing), then parallel enrichments."""
    dataset = (params.get("dataset") or "").strip()
    if not dataset:
        return {"ok": False, "error": "pipeline requires dataset"}
    # Geocode before provider-sensitive steps. MapKit GT labels against the
    # nearby list (≤250 m), so mapkit_nearby must finish before gt_mapkit.
    stages = []
    warnings = []
    sequence = ["exif", "geocode", "ocr", "mapkit_nearby", "gt_mapkit"]
    if os.environ.get("KAKAO_REST_API_KEY", "").strip():
        sequence.append("gt_kakao")
    else:
        stages.append({"step": "gt_kakao", "status": "skipped", "reason": "KAKAO_REST_API_KEY is not set"})
    env = dict(os.environ)
    env["POI_DATA_DIR"] = DIRECTORY

    def run_batch(steps, completed):
        procs, lines, events = {}, {x: [] for x in steps}, queue.Queue()
        def relay(name, stream):
            for raw in iter(stream.readline, ""):
                events.put((name, raw.rstrip("\n")))
            stream.close()
        for name in steps:
            print(f"[pipeline] starting {name}", file=log, flush=True)
            p = subprocess.Popen(
                _job_argv(name, {"dataset": dataset, "only_empty": True}),
                cwd=REPO_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                stdin=subprocess.DEVNULL, close_fds=True, start_new_session=True,
            )
            procs[name] = p
            threading.Thread(target=relay, args=(name, p.stdout), daemon=True).start()
        live = {x: {"status": "running", "done": 0, "total": 0, "step": "starting", "retries": 0} for x in steps}
        while any(p.poll() is None for p in procs.values()) or not events.empty():
            try:
                name, line = events.get(timeout=.15)
            except queue.Empty:
                continue
            lines[name].append(line)
            print(f"[{name}] {line}", file=log, flush=True)
            if line.startswith("PROGRESS "):
                try:
                    ev = json.loads(line[9:])
                    live[name].update({k: ev[k] for k in ("done", "total", "step", "retries", "retry_reason") if k in ev})
                except (json.JSONDecodeError, TypeError):
                    pass
                print(
                    "PROGRESS " + json.dumps({
                        "done": completed, "total": len(sequence),
                        "step": "parallel", "substeps": live,
                    }),
                    file=log, flush=True,
                )
        for p in procs.values():
            p.wait()
        results = {}
        for name, p in procs.items():
            result = None
            for line in reversed(lines[name]):
                if line.startswith("RESULT "):
                    try:
                        result = json.loads(line[7:])
                    except json.JSONDecodeError:
                        pass
                    break
            status = "done" if p.returncode == 0 else "error"
            reason = None
            if status == "done" and result and not result.get("targets", 1):
                status, reason = "skipped", result.get("skip_reason") or "no eligible rows"
            live[name]["status"] = status
            stages.append({
                "step": name, "status": status, "reason": reason,
                "returncode": p.returncode, "result": result,
            })
            results[name] = result
        return results, live

    # 1) EXIF — fill coords/time when still empty
    first, _ = run_batch(["exif"], 0)
    exif = first.get("exif") or {}
    targets, no_gps = exif.get("targets", 0), exif.get("no_gps", 0)
    if targets and no_gps:
        w = {
            "code": "exif_gps_missing", "dataset": dataset, "count": no_gps,
            "targets": targets,
            "message": (
                f"{no_gps}/{targets} source photos are missing EXIF GPS coordinates. "
                "Coordinate-based steps have no targets."
            ),
        }
        warnings.append(w)
        print("WARNING " + json.dumps(w, ensure_ascii=False), file=log, flush=True)
    no_timestamp = exif.get("no_timestamp", 0)
    if targets and no_timestamp:
        w = {
            "code": "exif_timestamp_missing", "dataset": dataset, "count": no_timestamp,
            "targets": targets,
            "message": f"{no_timestamp}/{targets} source photos are missing EXIF capture timestamps.",
        }
        warnings.append(w)
        print("WARNING " + json.dumps(w, ensure_ascii=False), file=log, flush=True)
    print("PROGRESS " + json.dumps({"done": 1, "total": len(sequence), "step": "exif"}), file=log, flush=True)

    # 2) Geocode — country/city/address before provider-sensitive steps
    geo_results, _ = run_batch(["geocode"], 1)
    geo = geo_results.get("geocode") or {}
    empty_geo = geo.get("empty_result", 0) or 0
    geo_targets = geo.get("targets", 0) or 0
    if geo_targets and empty_geo:
        w = {
            "code": "geocode_empty", "dataset": dataset, "count": empty_geo,
            "targets": geo_targets,
            "message": (
                f"{empty_geo}/{geo_targets} reverse-geocode lookups returned empty. "
                "Provider routing falls back to GPS region (KR bbox vs non-KR)."
            ),
        }
        warnings.append(w)
        print("WARNING " + json.dumps(w, ensure_ascii=False), file=log, flush=True)
    print("PROGRESS " + json.dumps({"done": 2, "total": len(sequence), "step": "geocode"}), file=log, flush=True)

    # 3) OCR ∥ MapKit nearby ∥ GT Kakao (independent of MapKit nearby list)
    parallel = ["ocr", "mapkit_nearby"]
    if "gt_kakao" in sequence:
        parallel.append("gt_kakao")
    _, live = run_batch(parallel, 2)
    print(
        "PROGRESS " + json.dumps({
            "done": 3, "total": len(sequence),
            "step": "ocr_nearby", "substeps": live,
        }),
        file=log, flush=True,
    )

    # 4) GT MapKit — same nearby set, distance-cut name match (needs step 3)
    _, live_gt = run_batch(["gt_mapkit"], 3)
    print(
        "PROGRESS " + json.dumps({
            "done": len(sequence), "total": len(sequence),
            "step": "pipeline", "substeps": {**live, **live_gt},
        }),
        file=log, flush=True,
    )
    errors = [x["step"] for x in stages if x["status"] == "error"]
    outcome = {
        "ok": True, "step": "pipeline", "dataset": dataset,
        "stages": stages, "warnings": warnings,
        "partial": bool(errors), "errors": errors,
    }
    print("RESULT " + json.dumps(outcome, ensure_ascii=False), file=log, flush=True)
    return outcome


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
        # Same authority order as match_score.canonical_country (row country /
        # GPS KR, not dataset map first). Dataset map is display fallback only.
        try:
            return canonical_country(r, cfg)
        except Exception:
            c = (r.get("country") or "").strip()
            return (cfg.get("country_normalize") or {}).get(c, c or "Unknown")

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

    Rows are overlaid with Reconcile overrides at read time so gt_mapkit fill /
    label breakdown reflects manual matches (same as matchrate).
    """
    cfg = load_config()
    signals = cfg.get("signals") or {}
    sources = cfg.get("sources") or {}
    _, rows = read_eval_csv()
    rows, _ = overlay_gt_mapkit_overrides(rows, path=_gt_overrides_path())
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
        if provider == "unresolved":
            return ("unresolved_country", "Country/region unresolved (geocode or GPS needed)")
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
    # Flatten metrics to top-level so a single-run detail matches the runs-list
    # shape (accuracy_pct, n_eligible, correct, …) — Compare/consumers read these
    # at the top level.
    m = run.get("metrics") or {}
    for k in ("n_eligible", "correct", "correct_canonical", "abstained", "errored",
              "accuracy_pct", "accuracy_canonical_pct", "match_kind_counts", "duration_ms"):
        if run.get(k) is None:
            run[k] = m.get(k)
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
        overrides_path=_gt_overrides_path(),
    )


# Static requests under these prefixes are dataset files served from DIRECTORY;
# everything else (the UI, templates) is tool code served from the repo.
DATA_PREFIXES = ("linkedspaces-photos", "photos", "union-city-trip", "generated")
# Paths that must never be served as static files (source, secrets, VCS).
_BLOCKED_STATIC_PREFIXES = (
    ".git/", ".ssh/", ".grok/", ".worktrees/", "tools/", "web/node_modules/",
    "poi-data-seed/", ".env", ".gitignore",
)
_BLOCKED_STATIC_NAMES = {
    "server.py", ".env", "dashboard_config.json",
}


def _is_blocked_static(rel_url: str) -> bool:
    """True when a static path would leak source, VCS, or config."""
    rel = (rel_url or "").lstrip("/").replace("\\", "/")
    if not rel or rel in _BLOCKED_STATIC_NAMES:
        return True
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in _BLOCKED_STATIC_PREFIXES):
        return True
    # Hide Python sources and private env files anywhere in the tree.
    base = os.path.basename(rel)
    if base.startswith(".env") or base.endswith((".py", ".pyc", ".pyo")):
        return True
    if "/." in f"/{rel}" and not rel.startswith("web/dist/"):
        # Dot-directories other than well-known public assets.
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts[:-1]):
            return True
    return False


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

    def _client_token(self):
        auth = (self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (self.headers.get("X-POI-Token") or "").strip()

    def _origin_allowed(self) -> bool:
        """Browser Origin check for state-changing requests.

        Non-browser clients (no Origin header) are allowed; CSRF risk is
        browser-initiated. When ALLOWED_ORIGINS is None the check is off.
        """
        if ALLOWED_ORIGINS is None:
            return True
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            # curl / same-origin navigation without Origin — allow.
            return True
        if origin in ALLOWED_ORIGINS:
            return True
        # Also accept Origin matching this server's own host when page is served
        # from the same process (legacy mvp-eval-ui.html on :8420).
        host = (self.headers.get("Host") or "").strip()
        if host and origin in (f"http://{host}", f"https://{host}"):
            return True
        return False

    def _require_mutating_access(self) -> bool:
        """Gate POST/DELETE: Origin allowlist + optional API token.

        Returns True when the request may proceed. On failure an error response
        has already been written.
        """
        if not self._origin_allowed():
            self._send_api_error(
                "forbidden", 403,
                detail=f"Origin not allowed: {self.headers.get('Origin')!r}",
            )
            return False
        if API_TOKEN and self._client_token() != API_TOKEN:
            self._send_api_error(
                "unauthorized", 401,
                detail="missing or invalid API token (set POI_API_TOKEN / X-POI-Token)",
            )
            return False
        return True

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
        "unauthorized": "authentication required",
        "forbidden": "request origin not allowed",
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
        # Prefer the React build when present; fall back to legacy HTML only
        # if dist is missing (fresh checkout before npm build).
        if route == "/":
            dist_index = os.path.join(REPO_DIR, "web", "dist", "index.html")
            if os.path.isfile(dist_index):
                self.send_response(302)
                self.send_header("Location", "/web/dist/index.html")
                self.end_headers()
                return
            legacy = os.path.join(REPO_DIR, "mvp-eval-ui.html")
            if os.path.isfile(legacy):
                self.send_response(302)
                self.send_header("Location", "/mvp-eval-ui.html")
                self.end_headers()
                return
            self._send_json({
                "ok": True,
                "service": "poi-eval",
                "hint": "run npm --prefix web run dev (or build) for the UI; API is at /api/*",
            })
            return
        if route == "/api/health":
            self._send_json({
                "ok": True,
                "bind": BIND_HOST,
                "port": PORT,
                "auth_required": bool(API_TOKEN),
                "origin_check": ALLOWED_ORIGINS is not None,
                "data_dir": DIRECTORY,
            })
            return
        # Block sensitive static paths before SimpleHTTP fallback.
        if not route.startswith("/api/"):
            rel = route.lstrip("/")
            if _is_blocked_static(rel):
                self._send_api_error("not_found", 404, detail="not found")
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
            dataset = (q.get("dataset", [""])[0]).strip() or None
            # thumb=1 | thumb=true → long-edge JPEG (default 360px). w= sets px.
            thumb_raw = (q.get("thumb", [""])[0]).strip().lower()
            want_thumb = thumb_raw in ("1", "true", "yes", "y")
            try:
                max_px = int((q.get("w", ["360"])[0]).strip() or "360")
            except ValueError:
                max_px = 360
            path = poi_case_photo(photo, dataset=dataset)
            if not path:
                self._send_api_error("not_found", 404, detail="photo not found")
                return
            serve = path
            content_type = self.guess_type(path)
            if want_thumb:
                thumb = poi_case_photo_thumb(path, max_px=max_px)
                if thumb:
                    serve = thumb
                    content_type = "image/jpeg"
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(os.path.getsize(serve)))
                # Thumbnails are content-addressed by mtime in the cache key;
                # short client cache is fine. Full-res stays no-store via end_headers.
                if want_thumb and serve != path:
                    self.send_header("Cache-Control", "private, max-age=86400")
                self.end_headers()
                with open(serve, "rb") as image:
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
        if route == "/api/seed/presets":
            try:
                disc = discover_seed_presets()
                # Strip internal path hints before returning to the browser.
                disc = {**disc, "presets": [
                    {k: v for k, v in p.items() if not k.startswith("_")}
                    for p in disc["presets"]
                ]}
                self._send_json(disc)
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
        if route == "/api/dataset-template":
            try:
                payload = build_dataset_template_zip()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="poi-dataset-template.zip"',
                )
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                self.log_error("dataset template request failed: %s", e)
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
            run_name = (q.get("run_name", q.get("name", [""]))[0]).strip() or None
            version_raw = (q.get("version", [""])[0]).strip()
            version = None
            if version_raw:
                try:
                    version = int(version_raw)
                except ValueError:
                    self._send_api_error("invalid_request", 400, detail="version must be an integer")
                    return
            d = case_detail(ds, ph, run_name=run_name, version=version)
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
        if not self._require_mutating_access():
            return
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
        if not os.path.isdir(SEED_DIR):
            self._send_json(
                {"ok": False, "message": f"seed bundle not found — place it at {os.path.relpath(SEED_DIR, REPO_DIR)}/"},
                code=404)
            return
        seed_dir = _seed_source_dir(preset)
        if seed_dir is None:
            self._send_json({"ok": False, "message": f"unknown or unavailable seed preset '{preset}'"}, code=400)
            return
        if os.path.isfile(CSV_PATH):
            self._send_json({"ok": True, "message": "already seeded"}, code=200)
            return
        try:
            os.makedirs(DIRECTORY, exist_ok=True)
            for name in ("eval_set_reconciled.csv", "dashboard_config.json"):
                src = os.path.join(seed_dir, name)
                dst = os.path.join(DIRECTORY, name)
                # Never clobber the tracked repo-root config template (legacy
                # root layout). Reads fall back to it, so skipping is safe.
                if os.path.abspath(dst) == os.path.abspath(REPO_CONFIG_PATH):
                    continue
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
            seed_runs = os.path.join(seed_dir, "generated", "runs")
            if os.path.isdir(seed_runs):
                os.makedirs(RUNS_DIR, exist_ok=True)
                for fn in os.listdir(seed_runs):
                    if fn.endswith(".json"):
                        shutil.copy2(os.path.join(seed_runs, fn), os.path.join(RUNS_DIR, fn))
            # Photos (optional in older seeds; required for case images).
            n_photos, photo_bytes = _copy_seed_photos(seed_dir, DIRECTORY)
            msg = f"seeded from {preset}"
            if n_photos:
                msg += f" ({n_photos} photos · {photo_bytes / (1024 * 1024):.1f} MiB)"
            else:
                msg += " (no photos in seed bundle — case images will be missing)"
            self._send_json({
                "ok": True, "message": msg,
                "photos": n_photos, "photos_bytes": photo_bytes,
            }, code=200)
        except Exception as e:
            self._send_json({"ok": False, "message": str(e)}, code=500)

    def _handle_seed_upload(self):
        """Onboarding: materialize a drag-and-dropped seed-bundle ZIP.

        The raw request body is the ZIP (mirrors /api/ingest). Extraction is
        whitelisted and zip-slip/zip-bomb safe (see _apply_seed_bundle)."""
        upload = self._read_body(_SEED_MAX_TOTAL_BYTES)
        if upload is None:
            return
        try:
            result = _apply_seed_bundle(upload)
        except Exception as e:
            self.log_error("seed upload failed: %s", e)
            self._send_json({"ok": False, "message": str(e)}, code=500)
            return
        code = result.pop("code", 200 if result.get("ok") else 400)
        self._send_json(result, code=code)

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
            from file_ops import file_lock
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            fields = ["dataset", "photo", "gt", "chosen", "chosen_none", "manual", "ts"]
            with file_lock(path):
                # Recover from a corrupt/non-TSV file (e.g. header written without tabs).
                need_header = True
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    with open(path, encoding="utf-8") as rf:
                        first = rf.readline()
                    need_header = "\t" not in first
                    if need_header:
                        # Replace broken file so DictWriter/writes stay tab-separated.
                        bak = path + ".bak-corrupt"
                        try:
                            os.replace(path, bak)
                        except OSError:
                            os.remove(path)
                mode = "w" if need_header or not os.path.isfile(path) else "a"
                with open(path, mode, newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
                    if mode == "w":
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
        if not self._require_mutating_access():
            return
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
            radius_m = payload.get("radius_m") if isinstance(payload, dict) else None
            self._send_json(mapkit_probe(lat, lon, radius_m=radius_m))
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
        if route == "/api/seed/upload":
            self._handle_seed_upload()
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
    if BIND_HOST not in ("127.0.0.1", "localhost", "::1") and not API_TOKEN:
        print(
            f"WARNING: binding to {BIND_HOST} without POI_API_TOKEN — "
            "mutating APIs are open to the network. Set POI_API_TOKEN.",
            file=sys.stderr,
        )
    with http.server.ThreadingHTTPServer((BIND_HOST, PORT), handler) as httpd:
        where = REPO_DIR if DIRECTORY == REPO_DIR else f"{REPO_DIR} (UI) + {DIRECTORY} (data)"
        auth = "token-required" if API_TOKEN else "local-trust"
        print(
            f"serving {where} at http://{BIND_HOST}:{PORT}  "
            f"[{auth}; origin_check={'on' if ALLOWED_ORIGINS is not None else 'off'}]"
        )
        httpd.serve_forever()
