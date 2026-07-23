#!/usr/bin/env python3
"""Curate the three named seed baselines (code + frozen results).

Seed contract (names and published metrics on the 166-eligible cohort)::

    baseline-nearest  v1   38% strict (63/166)     — MapKit distance rank-1
    mapkit-baseline   v1   39% strict (64/166)     — Bloggo + unique OCR override
    mapkit-baseline   v2   48% strict / 68% canon   — OCR + cascade + free-text VLM

Source runs live under ``poi-data/generated/runs/`` (full history). This tool
rewrites them into the curated names/versions with attached ``script_text`` so
the seed bundle is self-describing in Results / Case inspector.

Usage:
  python3 tools/curate_seed_baselines.py
  python3 tools/curate_seed_baselines.py --out /tmp/seed-runs
  # then pack:
  python3 tools/pack_seed_bundle.py --clean --runs-glob 'baseline-nearest__v1.json'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

# (name, version) → how to build the curated run
CURATED: List[Dict[str, Any]] = [
    {
        "name": "baseline-nearest",
        "version": 1,
        "label": "MapKit nearest — distance rank-1 pick",
        "source_candidates": [
            "baseline-nearest__v5.json",
            "baseline-nearest__v4.json",
            "baseline-nearest__v3.json",
        ],
        "script_paths": ["examples/baseline_nearest.py"],
        "params": ["nearby_candidates"],
        "lang": "python",
        "expect": {
            "accuracy_pct": 38,
            "correct": 63,
            "n_eligible": 166,
        },
    },
    {
        "name": "mapkit-baseline",
        "version": 1,
        "label": "MapKit baseline v1 — Bloggo weighted + unique OCR name override",
        # Historical mapkit-baseline__v2 is the 39% OCR-override result.
        "source_candidates": [
            "mapkit-baseline__v2.json",
        ],
        "script_paths": [
            "examples/mapkit_weighted.py",
            "examples/poi_confidence_policy.py",
            "examples/mapkit_ocr_override.py",
        ],
        "script_compose": "ocr_override",
        "params": ["ocr_text", "nearby_candidates"],
        "lang": "python",
        "expect": {
            "accuracy_pct": 39,
            "correct": 64,
            "n_eligible": 166,
        },
    },
    {
        "name": "mapkit-baseline",
        "version": 2,
        "label": (
            "MapKit baseline v2 — OCR + cascade + free-text VLM ensemble "
            "(~48% strict · ~68% canonical)"
        ),
        # Best published cohort result was stored as selector-loop70.
        "source_candidates": [
            "selector-loop70__v7.json",
            "selector-loop70__v6.json",
            "selector-loop70__v5.json",
            "selector-loop70__v4.json",
            "selector-loop70__v3.json",
        ],
        "script_paths": [
            "examples/mapkit_baseline_v2.py",
            "examples/selector_list_fit.py",
            "examples/selector_access_ocr.py",
            "examples/mapkit_weighted.py",
        ],
        "script_compose": "ensemble_v2",
        "params": ["nearby_candidates", "ocr_text", "image"],
        "lang": "python",
        "expect": {
            "accuracy_pct": 48,
            "accuracy_canonical_pct": 68,
            "correct": 80,
            "n_eligible": 166,
        },
    },
]


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_source(runs_dir: Path, names: List[str]) -> Path:
    for name in names:
        p = runs_dir / name
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"none of {names} found under {runs_dir} — need full poi-data runs"
    )


def _read_text(rel: str) -> str:
    p = _ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(f"missing script source: {p}")
    return p.read_text(encoding="utf-8")


def _compose_script(kind: Optional[str], paths: List[str]) -> str:
    """Build a single script_text suitable for display / re-submit.

    Multi-module algorithms are concatenated with section headers. The harness
    runs one file; multi-module imports only work when those modules are on
    PYTHONPATH (examples/). Seed results remain frozen either way.
    """
    if not kind or kind == "single":
        return _read_text(paths[0]).rstrip() + "\n"

    if kind == "ocr_override":
        parts = [
            '"""mapkit-baseline v1 — self-describing seed script.',
            "",
            "Primary modules (also under examples/):",
            "  - mapkit_weighted.py",
            "  - poi_confidence_policy.py",
            "  - mapkit_ocr_override.py",
            "",
            "Frozen seed metrics: 39% strict (64/166). Re-run requires the",
            "examples/ package on PYTHONPATH (or paste mapkit_ocr_override.py",
            "into New Run after installing examples next to tools/).",
            '"""',
            "",
            "# === examples/mapkit_ocr_override.py ===",
            _read_text("examples/mapkit_ocr_override.py").rstrip(),
            "",
            "# --- supporting modules (reference; not executed inline) ---",
            "# See examples/mapkit_weighted.py and examples/poi_confidence_policy.py",
            "# in the repository for the full Bloggo + OCR name-support policy.",
            "",
        ]
        return "\n".join(parts)

    if kind == "ensemble_v2":
        parts = [
            '"""mapkit-baseline v2 — seed reference script.',
            "",
            "Published seed metrics (frozen predictions in this run JSON):",
            "  48% strict (80/166) · 68% canonical",
            "",
            "Offline builder: tools/stitch_loop70_ensemble.py",
            "  list_fit@K20 + photo-match cascade + residual free-text VLM",
            "  rescored with eval_label_relations.v1.jsonl",
            "",
            "The predict() below is the deterministic core only. Full accuracy",
            "needs the offline VLM residual caches used when the seed was built.",
            '"""',
            "",
            _read_text("examples/mapkit_baseline_v2.py").rstrip(),
            "",
        ]
        return "\n".join(parts)

    # Fallback: first file
    return _read_text(paths[0]).rstrip() + "\n"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def curate_one(spec: Dict[str, Any], runs_dir: Path) -> dict:
    src_path = _find_source(runs_dir, spec["source_candidates"])
    src = _load_json(src_path)
    metrics = src.get("metrics") or {}
    expect = spec.get("expect") or {}

    # Soft validation — warn, don't hard-fail, so slightly rescored cohorts still pack.
    for key, want in expect.items():
        got = metrics.get(key)
        if got is not None and got != want:
            print(
                f"[curate] warn: {spec['name']} v{spec['version']} "
                f"{key}={got} expected {want} (source {src_path.name})",
                file=sys.stderr,
            )

    script_text = _compose_script(spec.get("script_compose"), spec["script_paths"])
    # Prefer source script when it already embeds a full self-contained predict
    # and matches our single-file baseline case.
    if (
        not spec.get("script_compose")
        and isinstance(src.get("script_text"), str)
        and src["script_text"].strip()
    ):
        script_text = src["script_text"]

    out = {
        "name": spec["name"],
        "safe_name": spec["name"],
        "version": int(spec["version"]),
        "created_at": src.get("created_at") or "",
        "scope": src.get("scope") or "all",
        "mode": src.get("mode") or "exact",
        "params": list(spec.get("params") or src.get("params") or []),
        "candidate_limit": src.get("candidate_limit"),
        "lang": spec.get("lang") or src.get("lang") or "python",
        "label": spec["label"],
        "seed_baseline": True,
        "seed_source_run": src_path.name,
        "script_sha256": _sha256_text(script_text),
        "script_text": script_text,
        "evaluation_set_sha256": src.get("evaluation_set_sha256"),
        "data_snapshot_sha256": src.get("data_snapshot_sha256"),
        "label_relations_path": src.get("label_relations_path"),
        "metrics": metrics,
        "cases": src.get("cases") or [],
    }
    # Preserve useful provenance without polluting the identity fields.
    if src.get("rescored_from"):
        out["rescored_from"] = src["rescored_from"]
    if src.get("rule_version"):
        out["rule_version"] = src["rule_version"]
    return out


def curate_all(runs_dir: Path, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for spec in CURATED:
        rec = curate_one(spec, runs_dir)
        fname = f"{rec['safe_name']}__v{rec['version']}.json"
        dest = out_dir / fname
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
            f.write("\n")
        m = rec["metrics"]
        print(
            f"[curate] {fname}  "
            f"acc={m.get('accuracy_pct')}% "
            f"canon={m.get('accuracy_canonical_pct')}% "
            f"correct={m.get('correct')}/{m.get('n_eligible')} "
            f"script={len(rec.get('script_text') or '')}B "
            f"← {rec.get('seed_source_run')}"
        )
        written.append(dest)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--runs-dir",
        default=str(_ROOT / "poi-data" / "generated" / "runs"),
        help="source runs directory (full history)",
    )
    ap.add_argument(
        "--out",
        default=str(_ROOT / "poi-data" / "generated" / "seed-baselines"),
        help="output directory for curated baseline JSON files",
    )
    args = ap.parse_args()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    if not runs_dir.is_dir():
        print(f"[curate] missing runs dir: {runs_dir}", file=sys.stderr)
        return 1
    paths = curate_all(runs_dir, out_dir)
    print(f"[curate] wrote {len(paths)} baselines → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
