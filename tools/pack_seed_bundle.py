#!/usr/bin/env python3
"""Build an onboarding seed bundle *with photos* for a fresh clone.

Default layout (same shape the server expects under ``poi-data-seed/``)::

    poi-data-seed/
      eval_set_reconciled.csv
      dashboard_config.json
      generated/runs/*.json
      photos/…
      linkedspaces-photos/…
      union-city-trip/…
      poi-dataset-20260708-photos/…
      MANIFEST.json          # counts, missing photos, pack time

Only photos **referenced by the eval CSV** are copied (not the whole tree), so
size tracks the seed cohort. Destination paths preserve each source's
``photo_dir`` layout so ``/api/poi-case-photo`` resolves the same way as live
``poi-data/``.

Usage:
  # Refresh repo-local poi-data-seed/ from poi-data/
  python3 tools/pack_seed_bundle.py

  # Write a shareable ZIP (Drive / seed upload)
  python3 tools/pack_seed_bundle.py --zip /tmp/poi-seed-with-photos.zip

  # Custom source / dest
  POI_DATA_DIR=/path/to/poi-data python3 tools/pack_seed_bundle.py \\
      --out /path/to/poi-data-seed --runs-glob 'baseline-*__v*.json'
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
import match_score as ms  # noqa: E402

FALLBACK_PHOTO_DIR = {
    "linkedspaces": "linkedspaces-photos",
    "vancouver": "photos",
    "union-city": "union-city-trip",
    "poi-dataset-20260708": "poi-dataset-20260708-photos",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def _data_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(ms.DATA_ROOT).resolve()


def _load_config(data_root: Path) -> dict:
    for p in (data_root / "dashboard_config.json", _ROOT / "dashboard_config.json"):
        if p.is_file():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _photo_dir_for(dataset: str, cfg: dict) -> str:
    src = (cfg.get("sources") or {}).get(dataset) or {}
    if src.get("photo_dir"):
        return str(src["photo_dir"]).strip().strip("/\\")
    return FALLBACK_PHOTO_DIR.get(dataset, f"{dataset}-photos")


def _find_photo(data_root: Path, photo_dir: str, photo: str) -> Optional[Path]:
    """Locate a photo under photo_dir (direct, then recursive basename)."""
    base = (photo or "").strip()
    if not base or base != os.path.basename(base):
        return None
    root = (data_root / photo_dir).resolve()
    if not root.is_dir():
        return None
    # Stay inside photo_dir (zip-slip / path escape guard).
    try:
        root.relative_to(data_root.resolve())
    except ValueError:
        return None
    direct = root / base
    if direct.is_file():
        return direct
    for p in root.rglob(base):
        if p.is_file():
            try:
                p.resolve().relative_to(root)
            except ValueError:
                continue
            return p
    # Extension variants
    stem = Path(base).stem
    for p in root.rglob("*"):
        if p.is_file() and p.stem == stem and p.suffix.lower() in IMAGE_EXTS:
            try:
                p.resolve().relative_to(root)
            except ValueError:
                continue
            return p
    return None


def _rel_under(data_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(data_root.resolve())).replace("\\", "/")


def collect_photo_plan(
    data_root: Path,
    csv_path: Path,
    cfg: dict,
) -> Tuple[List[Tuple[Path, str]], List[dict]]:
    """Return (copy_jobs as (src, dest_rel), missing row records)."""
    jobs: Dict[str, Path] = {}  # dest_rel -> src (dedupe)
    missing: List[dict] = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        ds = (r.get("dataset") or "").strip()
        ph = (r.get("photo") or "").strip()
        if not ds or not ph:
            missing.append({"dataset": ds, "photo": ph, "reason": "empty dataset/photo"})
            continue
        pdir = _photo_dir_for(ds, cfg)
        src = _find_photo(data_root, pdir, ph)
        if src is None:
            missing.append({"dataset": ds, "photo": ph, "photo_dir": pdir, "reason": "file not found"})
            continue
        # Prefer CSV basename under the configured photo_dir so serving is stable.
        dest_rel = f"{pdir}/{os.path.basename(ph)}".replace("\\", "/")
        # If the file lives in a nested subfolder of photo_dir, keep that relative path.
        try:
            nested = src.resolve().relative_to((data_root / pdir).resolve())
            dest_rel = f"{pdir}/{nested.as_posix()}"
        except ValueError:
            pass
        jobs[dest_rel] = src
    return [(src, rel) for rel, src in sorted(jobs.items(), key=lambda x: x[0])], missing


def _select_runs(runs_dir: Path, pattern: str) -> List[Path]:
    if not runs_dir.is_dir():
        return []
    out = []
    for p in sorted(runs_dir.iterdir()):
        if p.is_file() and p.suffix == ".json" and fnmatch.fnmatch(p.name, pattern):
            out.append(p)
    return out


def _copy_mapkit_candidate_artifacts(data_root: Path, out_dir: Path) -> Tuple[List[str], int]:
    """Copy active MapKit candidate snapshot (+ pointer, legacy JSONL) into seed.

    Case inspector loads candidates from MATCH_CANDIDATE_PATHS / active snapshot,
    not from photos. Omitting these yields candidate_total=0 and the sparse banner.
    """
    copied: List[str] = []
    nbytes = 0
    gen = data_root / "generated"
    out_gen = out_dir / "generated"
    out_gen.mkdir(parents=True, exist_ok=True)

    def _copy_file(src: Path, dest: Path) -> None:
        nonlocal nbytes
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(out_dir)).replace("\\", "/"))
        try:
            nbytes += src.stat().st_size
        except OSError:
            pass

    # Active pointer + referenced snapshot directory (authoritative for UI/runs).
    pointer = gen / "active-mapkit-candidate-snapshot.json"
    if pointer.is_file():
        _copy_file(pointer, out_gen / pointer.name)
        try:
            with open(pointer, encoding="utf-8") as f:
                meta = json.load(f)
            snap_id = meta.get("snapshot_id")
            artifact = meta.get("candidate_artifact") or "mapkit_candidates.jsonl"
            if isinstance(snap_id, str) and snap_id:
                snap_dir = gen / "candidate-snapshots" / snap_id
                if snap_dir.is_dir():
                    for src in sorted(snap_dir.rglob("*")):
                        if not src.is_file():
                            continue
                        rel = src.relative_to(gen)
                        _copy_file(src, out_gen / rel)
                # Always try the named artifact path if present.
                art = snap_dir / artifact
                if art.is_file() and str((out_gen / "candidate-snapshots" / snap_id / artifact).relative_to(out_dir)).replace("\\", "/") not in copied:
                    _copy_file(art, out_gen / "candidate-snapshots" / snap_id / artifact)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            print(f"[pack] warn: active snapshot pointer unreadable: {e}")

    # Legacy flat JSONL + nearby-cache used by GT / fallback loaders.
    for name in (
        "mapkit_candidates.jsonl",
        "mapkit_nearby_candidates.jsonl",
        "kakao_local_candidates.jsonl",
    ):
        src = gen / name
        if src.is_file():
            _copy_file(src, out_gen / name)

    # Latest probe TSV (full wide_candidates_json) if present — small, useful fallback.
    for name in ("rerun_mapkit_output.tsv", "ls_nearby_results.tsv"):
        src = data_root / name
        if src.is_file():
            _copy_file(src, out_dir / name)

    return copied, nbytes


def pack(
    data_root: Path,
    out_dir: Path,
    *,
    runs_glob: str = "*.json",
    include_photos: bool = True,
    clean: bool = False,
) -> dict:
    csv_src = data_root / "eval_set_reconciled.csv"
    if not csv_src.is_file():
        raise SystemExit(f"missing eval CSV: {csv_src}")
    cfg = _load_config(data_root)
    cfg_src = data_root / "dashboard_config.json"
    if not cfg_src.is_file():
        cfg_src = _ROOT / "dashboard_config.json"

    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(csv_src, out_dir / "eval_set_reconciled.csv")
    if cfg_src.is_file():
        shutil.copy2(cfg_src, out_dir / "dashboard_config.json")

    runs_src = data_root / "generated" / "runs"
    runs_dst = out_dir / "generated" / "runs"
    runs_dst.mkdir(parents=True, exist_ok=True)
    run_files = _select_runs(runs_src, runs_glob)
    for p in run_files:
        shutil.copy2(p, runs_dst / p.name)

    # MapKit candidate artifacts — Case inspector / predict() nearby lists.
    # Without these, seeded installs show "Sparse list — 0 candidates".
    cand_files, cand_bytes = _copy_mapkit_candidate_artifacts(data_root, out_dir)

    photo_jobs: List[Tuple[Path, str]] = []
    missing: List[dict] = []
    bytes_photos = 0
    if include_photos:
        photo_jobs, missing = collect_photo_plan(data_root, csv_src, cfg)
        for src, rel in photo_jobs:
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            bytes_photos += src.stat().st_size

    # Row count
    with open(csv_src, encoding="utf-8") as f:
        n_rows = max(0, sum(1 for _ in f) - 1)

    manifest = {
        "packed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_data_root": str(data_root),
        "rows": n_rows,
        "runs": [p.name for p in run_files],
        "runs_glob": runs_glob,
        "photos_included": include_photos,
        "photos_copied": len(photo_jobs),
        "photos_bytes": bytes_photos,
        "photos_missing": missing,
        "photo_dirs": sorted({rel.split("/")[0] for _, rel in photo_jobs}),
        "mapkit_candidate_files": cand_files,
        "mapkit_candidate_bytes": cand_bytes,
    }
    with open(out_dir / "MANIFEST.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return manifest


def write_zip(out_dir: Path, zip_path: Path) -> int:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out_dir.rglob("*")):
            if not path.is_file():
                continue
            arc = path.relative_to(out_dir).as_posix()
            zf.write(path, arcname=arc)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Pack poi-data-seed (CSV + runs + photos)")
    ap.add_argument("--data-dir", default=None, help="source data root (default: POI_DATA_DIR / poi-data)")
    ap.add_argument(
        "--out",
        default=str(_ROOT / "poi-data-seed"),
        help="output seed directory (default: repo poi-data-seed/)",
    )
    ap.add_argument("--zip", default=None, metavar="PATH", help="also write a ZIP at PATH")
    ap.add_argument("--runs-glob", default="*.json", help="which run JSON files to include")
    ap.add_argument("--no-photos", action="store_true", help="CSV + runs only (legacy minimal seed)")
    ap.add_argument("--clean", action="store_true", help="delete --out before packing")
    args = ap.parse_args()

    data_root = _data_root(args.data_dir)
    out_dir = Path(args.out).expanduser().resolve()
    print(f"[pack] source={data_root}")
    print(f"[pack] out={out_dir}")
    manifest = pack(
        data_root,
        out_dir,
        runs_glob=args.runs_glob,
        include_photos=not args.no_photos,
        clean=args.clean,
    )
    print(
        f"[pack] rows={manifest['rows']} runs={len(manifest['runs'])} "
        f"photos={manifest['photos_copied']} "
        f"({manifest['photos_bytes'] / (1024 * 1024):.1f} MiB) "
        f"missing={len(manifest['photos_missing'])} "
        f"mapkit_artifacts={len(manifest.get('mapkit_candidate_files') or [])} "
        f"({(manifest.get('mapkit_candidate_bytes') or 0) / (1024 * 1024):.1f} MiB)"
    )
    if manifest["photos_missing"]:
        for m in manifest["photos_missing"][:10]:
            print(f"  MISSING {m.get('dataset')}/{m.get('photo')}: {m.get('reason')}")
        if len(manifest["photos_missing"]) > 10:
            print(f"  … +{len(manifest['photos_missing']) - 10} more (see MANIFEST.json)")
    if args.zip:
        zpath = Path(args.zip).expanduser().resolve()
        n = write_zip(out_dir, zpath)
        print(f"[pack] zip={zpath} files={n} size={zpath.stat().st_size / (1024 * 1024):.1f} MiB")
    return 0 if not manifest["photos_missing"] else 0  # missing photos are warnings, not hard fail


if __name__ == "__main__":
    raise SystemExit(main())
