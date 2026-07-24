#!/usr/bin/env python3
"""Build an onboarding seed bundle *with photos* for a fresh clone.

Default layout (same shape the server expects under ``poi-data-seed/``)::

    poi-data-seed/
      eval_set_reconciled.csv
      dashboard_config.json
      presets.json
      generated/runs/          # 3 curated baselines (code + results)
        baseline-nearest__v1.json   38%  distance rank-1
        mapkit-baseline__v1.json    39%  Bloggo + OCR override
        mapkit-baseline__v2.json    48% / 68% canonical  ensemble
      generated/active-mapkit-candidate-snapshot.json
      generated/candidate-snapshots/…
      photos/…
      linkedspaces-photos/…
      union-city-trip/…
      poi-dataset-20260708-photos/…
      MANIFEST.json

Only photos **referenced by the eval CSV** are copied (not the whole tree).

Usage:
  # Refresh repo-local poi-data-seed/ (curates 3 baselines, then packs)
  python3 tools/pack_seed_bundle.py --clean

  # Write a shareable ZIP (Drive / onboarding upload)
  python3 tools/pack_seed_bundle.py --clean --zip /tmp/poi-seed-with-photos.zip

  # Full historical runs instead of the 3 curated baselines
  python3 tools/pack_seed_bundle.py --all-runs --clean
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


def _ocr_text_from_row(row: dict) -> str:
    for key in ("ocr_text", "caption_ondevice", "text", "raw"):
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def load_ocr_sidecar_map(data_root: Path) -> Dict[str, str]:
    """Map photo basename / stem / full path → OCR text from known sidecars.

    Harness injects OCR via ``caption_ondevice`` on the eval CSV. Sidecars
    (``ocr_text.tsv``, ``ls_ocr_text.tsv``, …) are merged so a seed pack can
    backfill empty CSV cells before shipping.
    """
    out: Dict[str, str] = {}

    def consider(photo: str, text: str) -> None:
        text = (text or "").strip()
        photo = (photo or "").strip()
        if not photo or not text:
            return
        base = os.path.basename(photo)
        stem = Path(base).stem.lower()
        for key in (photo, base, stem):
            prev = out.get(key)
            if prev is None or len(text) > len(prev):
                out[key] = text

    patterns = (
        "ocr_text.tsv",
        "ls_ocr_text.tsv",
        "rerun_ocr_output.tsv",
        "*ocr*.tsv",
        "*ocr*.csv",
    )
    seen_files: set = set()
    for pat in patterns:
        for path in sorted(data_root.glob(pat)):
            if not path.is_file() or path in seen_files:
                continue
            # Skip huge unrelated result dumps that are not photo→text.
            name = path.name.lower()
            if "fastvlm" in name and "ocr" in name and "results" in name:
                continue
            seen_files.add(path)
            try:
                with open(path, encoding="utf-8", newline="") as f:
                    sample = f.read(2048)
                    f.seek(0)
                    delim = "\t" if sample.count("\t") >= sample.count(",") else ","
                    reader = csv.DictReader(f, delimiter=delim)
                    for row in reader:
                        consider(row.get("photo") or "", _ocr_text_from_row(row))
            except (OSError, csv.Error, UnicodeError) as e:
                print(f"[pack] warn: skip OCR sidecar {path.name}: {e}")

    # CSV itself is also a source when packing a filtered subset from full data.
    csv_path = data_root / "eval_set_reconciled.csv"
    if csv_path.is_file():
        try:
            with open(csv_path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    consider(row.get("photo") or "", row.get("caption_ondevice") or "")
        except (OSError, csv.Error):
            pass
    return out


def backfill_caption_ondevice(csv_path: Path, ocr_map: Dict[str, str]) -> dict:
    """Fill empty ``caption_ondevice`` from ``ocr_map``; rewrite CSV in place."""
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "caption_ondevice" not in fieldnames:
        fieldnames.append("caption_ondevice")
    if "ocr_processed" not in fieldnames:
        fieldnames.append("ocr_processed")

    before = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
    filled = 0
    for r in rows:
        if (r.get("caption_ondevice") or "").strip():
            r["ocr_processed"] = r.get("ocr_processed") or "1"
            continue
        ph = (r.get("photo") or "").strip()
        base = os.path.basename(ph)
        stem = Path(base).stem.lower()
        text = ocr_map.get(ph) or ocr_map.get(base) or ocr_map.get(stem) or ""
        if text:
            r["caption_ondevice"] = text
            r["ocr_processed"] = "1"
            filled += 1
    after = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
    tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, csv_path)
    return {
        "rows": len(rows),
        "ocr_filled_before": before,
        "ocr_backfilled": filled,
        "ocr_filled_after": after,
        "ocr_empty": len(rows) - after,
    }


def write_ocr_tsv(csv_path: Path, out_tsv: Path) -> int:
    """Write seed ``ocr_text.tsv`` (photo + ocr_text) for rows with OCR."""
    n = 0
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_tsv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["dataset", "photo", "ocr_text"])
        for r in rows:
            text = (r.get("caption_ondevice") or "").strip()
            if not text:
                continue
            w.writerow([
                (r.get("dataset") or "").strip(),
                (r.get("photo") or "").strip(),
                text,
            ])
            n += 1
    return n


def vision_fill_missing_ocr(seed_dir: Path, cfg: dict) -> dict:
    """Run Vision OCR (ocr_all.swift) for seed rows still missing caption_ondevice.

    Photos must already live under the seed photo dirs. Updates the seed CSV
    and returns coverage stats. No-op when Swift / probe is unavailable.
    """
    csv_path = seed_dir / "eval_set_reconciled.csv"
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "caption_ondevice" not in fieldnames:
        fieldnames.append("caption_ondevice")
    if "ocr_processed" not in fieldnames:
        fieldnames.append("ocr_processed")

    targets: List[Tuple[dict, Path, str]] = []
    for r in rows:
        if (r.get("caption_ondevice") or "").strip():
            continue
        ds = (r.get("dataset") or "").strip()
        ph = (r.get("photo") or "").strip()
        pdir = _photo_dir_for(ds, cfg)
        src = _find_photo(seed_dir, pdir, ph)
        if src is None:
            continue
        key = f"{ds}/{ph}"
        targets.append((r, src, key))

    if not targets:
        filled = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
        return {
            "vision_targets": 0,
            "vision_filled": 0,
            "ocr_filled_after": filled,
            "ocr_empty": len(rows) - filled,
        }

    swift = _ROOT / "tools" / "swift" / "ocr_all.swift"
    if not swift.is_file():
        print(f"[pack] warn: missing {swift}; skip vision OCR fill")
        filled = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
        return {
            "vision_targets": len(targets),
            "vision_filled": 0,
            "vision_skipped": "no ocr_all.swift",
            "ocr_filled_after": filled,
            "ocr_empty": len(rows) - filled,
        }

    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="poi-seed-ocr-") as td:
        in_tsv = Path(td) / "in.tsv"
        out_tsv = Path(td) / "out.tsv"
        with open(in_tsv, "w", encoding="utf-8") as f:
            for _row, src, key in targets:
                f.write(f"{key}\t{src}\n")
        print(f"[pack] vision OCR on {len(targets)} seed photos missing caption_ondevice…")
        try:
            proc = subprocess.run(
                ["swift", str(swift), str(in_tsv), str(out_tsv)],
                cwd=str(_ROOT),
                capture_output=True,
                text=True,
                timeout=max(120, 30 * len(targets)),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"[pack] warn: vision OCR failed: {e}")
            filled = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
            return {
                "vision_targets": len(targets),
                "vision_filled": 0,
                "vision_error": str(e),
                "ocr_filled_after": filled,
                "ocr_empty": len(rows) - filled,
            }
        if proc.returncode != 0:
            print(f"[pack] warn: ocr_all.swift exit {proc.returncode}: "
                  f"{(proc.stderr or proc.stdout or '')[-300:]}")

        text_by_key: Dict[str, str] = {}
        if out_tsv.is_file():
            with open(out_tsv, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    parts = line.rstrip("\n").split("\t")
                    if i == 0 and parts and parts[0] == "photo":
                        continue
                    if len(parts) >= 2:
                        text_by_key[parts[0]] = parts[1]

    filled_new = 0
    for r, _src, key in targets:
        val = (text_by_key.get(key) or "").strip()
        r["ocr_processed"] = "1"
        if val:
            r["caption_ondevice"] = val
            filled_new += 1

    tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, csv_path)
    after = sum(1 for r in rows if (r.get("caption_ondevice") or "").strip())
    return {
        "vision_targets": len(targets),
        "vision_filled": filled_new,
        "vision_empty_result": len(targets) - filled_new,
        "ocr_filled_after": after,
        "ocr_empty": len(rows) - after,
    }


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


# Default seed ships only the three curated named baselines (code + results).
# Full history remains under poi-data/generated/runs/.
DEFAULT_SEED_RUNS_GLOB = "baseline-nearest__v1.json"
CURATED_BASELINE_NAMES = (
    "baseline-nearest__v1.json",
    "mapkit-baseline__v1.json",
    "mapkit-baseline__v2.json",
)


def _resolve_runs_for_seed(
    data_root: Path,
    runs_glob: str,
    *,
    curated: bool,
) -> Tuple[List[Path], str]:
    """Return (run files to copy, description of source).

    When ``curated`` is True (default), regenerate the three named seed baselines
    into ``generated/seed-baselines/`` and pack only those. Pass
    ``--all-runs`` / ``runs_glob='*.json'`` with curated=False for the full set.
    """
    if curated:
        # Late import so pack stays usable without curate module in odd layouts.
        sys.path.insert(0, str(_HERE))
        import curate_seed_baselines as csb  # noqa: E402

        runs_src = data_root / "generated" / "runs"
        staged = data_root / "generated" / "seed-baselines"
        csb.curate_all(runs_src, staged)
        files = [staged / name for name in CURATED_BASELINE_NAMES if (staged / name).is_file()]
        if len(files) != len(CURATED_BASELINE_NAMES):
            missing = [n for n in CURATED_BASELINE_NAMES if not (staged / n).is_file()]
            raise SystemExit(f"curated seed baselines incomplete, missing: {missing}")
        return files, "curated:baseline-nearest@v1+mapkit-baseline@v1+v2"

    runs_src = data_root / "generated" / "runs"
    return _select_runs(runs_src, runs_glob), f"glob:{runs_glob}"


def pack(
    data_root: Path,
    out_dir: Path,
    *,
    runs_glob: str = DEFAULT_SEED_RUNS_GLOB,
    include_photos: bool = True,
    clean: bool = False,
    curated_baselines: bool = True,
    fill_ocr_vision: bool = False,
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

    seed_csv = out_dir / "eval_set_reconciled.csv"
    shutil.copy2(csv_src, seed_csv)
    if cfg_src.is_file():
        shutil.copy2(cfg_src, out_dir / "dashboard_config.json")

    # OCR: harness predict(case)["ocr_text"] comes from caption_ondevice.
    # Backfill empty cells from sidecars, then emit ocr_text.tsv for the seed.
    ocr_map = load_ocr_sidecar_map(data_root)
    ocr_stats = backfill_caption_ondevice(seed_csv, ocr_map)
    print(
        f"[pack] OCR CSV backfill: {ocr_stats['ocr_filled_before']} → "
        f"{ocr_stats['ocr_filled_after']} filled "
        f"(+{ocr_stats['ocr_backfilled']} from sidecars; "
        f"{ocr_stats['ocr_empty']} still empty)"
    )

    # Reviewed GT aliases / related-credit relations (scoring + match_kind).
    relations_src = data_root / "eval_label_relations.v1.jsonl"
    relations_copied = False
    if relations_src.is_file():
        shutil.copy2(relations_src, out_dir / relations_src.name)
        relations_copied = True

    runs_dst = out_dir / "generated" / "runs"
    runs_dst.mkdir(parents=True, exist_ok=True)
    run_files, runs_note = _resolve_runs_for_seed(
        data_root, runs_glob, curated=curated_baselines
    )
    for p in run_files:
        shutil.copy2(p, runs_dst / p.name)

    # MapKit candidate artifacts — Case inspector / predict() nearby lists.
    # Without these, seeded installs show "Sparse list — 0 candidates".
    cand_files, cand_bytes = _copy_mapkit_candidate_artifacts(data_root, out_dir)

    photo_jobs: List[Tuple[Path, str]] = []
    missing: List[dict] = []
    bytes_photos = 0
    if include_photos:
        photo_jobs, missing = collect_photo_plan(data_root, seed_csv, cfg)
        for src, rel in photo_jobs:
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            bytes_photos += src.stat().st_size

    vision_stats: dict = {}
    if fill_ocr_vision and include_photos:
        vision_stats = vision_fill_missing_ocr(out_dir, cfg)
        print(
            f"[pack] vision OCR: targets={vision_stats.get('vision_targets')} "
            f"filled={vision_stats.get('vision_filled')} "
            f"empty_after={vision_stats.get('ocr_empty')}"
        )
        ocr_stats["ocr_filled_after"] = vision_stats.get(
            "ocr_filled_after", ocr_stats["ocr_filled_after"]
        )
        ocr_stats["ocr_empty"] = vision_stats.get("ocr_empty", ocr_stats["ocr_empty"])
        ocr_stats["vision"] = vision_stats

    ocr_tsv_n = write_ocr_tsv(seed_csv, out_dir / "ocr_text.tsv")
    print(f"[pack] wrote ocr_text.tsv ({ocr_tsv_n} rows with text)")

    # Row count (seed CSV, post-OCR)
    with open(seed_csv, encoding="utf-8") as f:
        n_rows = max(0, sum(1 for _ in f) - 1)

    # Baseline legend for the seed (human-readable; UI may surface later).
    baselines_meta = []
    for p in run_files:
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            m = rec.get("metrics") or {}
            baselines_meta.append({
                "file": p.name,
                "name": rec.get("name"),
                "version": rec.get("version"),
                "label": rec.get("label") or "",
                "accuracy_pct": m.get("accuracy_pct"),
                "accuracy_canonical_pct": m.get("accuracy_canonical_pct"),
                "correct": m.get("correct"),
                "n_eligible": m.get("n_eligible"),
                "has_script": bool(rec.get("script_text")),
            })
        except (OSError, ValueError, TypeError):
            baselines_meta.append({"file": p.name})

    presets = {
        "presets": [
            {
                "id": "default",
                "label": "Demo seed — 3 named baselines",
                "desc": (
                    "Eval set + photos + MapKit candidates + "
                    "baseline-nearest v1 (38%), mapkit-baseline v1 (39%), "
                    "mapkit-baseline v2 (48% / 68% canonical)."
                ),
                "path": ".",
            }
        ]
    }
    with open(out_dir / "presets.json", "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
        f.write("\n")

    manifest = {
        "packed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_data_root": str(data_root),
        "rows": n_rows,
        "runs": [p.name for p in run_files],
        "runs_source": runs_note,
        "runs_glob": runs_glob,
        "curated_baselines": curated_baselines,
        "baselines": baselines_meta,
        "photos_included": include_photos,
        "photos_copied": len(photo_jobs),
        "photos_bytes": bytes_photos,
        "photos_missing": missing,
        "photo_dirs": sorted({rel.split("/")[0] for _, rel in photo_jobs}),
        "mapkit_candidate_files": cand_files,
        "mapkit_candidate_bytes": cand_bytes,
        "label_relations": relations_copied,
        "label_relations_path": "eval_label_relations.v1.jsonl" if relations_copied else None,
        "ocr_text_tsv": "ocr_text.tsv" if ocr_tsv_n else None,
        "ocr_rows_with_text": ocr_tsv_n,
        "ocr_coverage": ocr_stats,
        "fill_ocr_vision": bool(fill_ocr_vision),
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
    ap.add_argument(
        "--runs-glob",
        default=DEFAULT_SEED_RUNS_GLOB,
        help="which run JSON files to include when --all-runs is set",
    )
    ap.add_argument(
        "--all-runs",
        action="store_true",
        help="pack all matching --runs-glob runs instead of the 3 curated baselines",
    )
    ap.add_argument("--no-photos", action="store_true", help="CSV + runs only (legacy minimal seed)")
    ap.add_argument(
        "--fill-ocr-vision",
        action="store_true",
        help=(
            "After copying photos, run tools/swift/ocr_all.swift on rows still "
            "missing caption_ondevice and bake results into the seed CSV + ocr_text.tsv"
        ),
    )
    ap.add_argument("--clean", action="store_true", help="delete --out before packing")
    args = ap.parse_args()

    data_root = _data_root(args.data_dir)
    out_dir = Path(args.out).expanduser().resolve()
    print(f"[pack] source={data_root}")
    print(f"[pack] out={out_dir}")
    manifest = pack(
        data_root,
        out_dir,
        runs_glob="*.json" if args.all_runs else args.runs_glob,
        include_photos=not args.no_photos,
        clean=args.clean,
        curated_baselines=not args.all_runs,
        fill_ocr_vision=bool(args.fill_ocr_vision),
    )
    ocr_cov = manifest.get("ocr_coverage") or {}
    print(
        f"[pack] rows={manifest['rows']} runs={len(manifest['runs'])} "
        f"photos={manifest['photos_copied']} "
        f"({manifest['photos_bytes'] / (1024 * 1024):.1f} MiB) "
        f"missing={len(manifest['photos_missing'])} "
        f"mapkit_artifacts={len(manifest.get('mapkit_candidate_files') or [])} "
        f"({(manifest.get('mapkit_candidate_bytes') or 0) / (1024 * 1024):.1f} MiB) "
        f"label_relations={'yes' if manifest.get('label_relations') else 'no'} "
        f"ocr_text_rows={manifest.get('ocr_rows_with_text')} "
        f"ocr_empty={ocr_cov.get('ocr_empty')}"
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
