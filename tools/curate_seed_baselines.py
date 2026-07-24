#!/usr/bin/env python3
"""Curate the three named seed baselines (code + frozen results).

Seed contract (names and published metrics on the 166-eligible cohort)::

    baseline-nearest  v1   38% strict (63/166)     — MapKit distance rank-1
    mapkit-baseline   v1   39% strict (64/166)     — Bloggo + unique OCR override
    mapkit-baseline   v2   48% strict / 68% canon   — live OCR + FastVLM cascade + residual

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
            "MapKit baseline v2 — live list_fit + FastVLM cascade + residual "
            "(~48% strict · ~68% canonical; re-run requires FastVLM venv)"
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
            "examples/mapkit_vlm_live.py",
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


def _comment_block(lines: List[str]) -> List[str]:
    """Prefix lines as ``#`` comments (blank lines stay blank).

    Seed preambles must NOT be string literals. Prepending a second module
    docstring before a real ``examples/*.py`` source that already has a
    docstring + ``from __future__`` triggers::

        SyntaxError: from __future__ imports must occur at the beginning of the file

    Comments and blank lines are the only safe preamble forms before
    ``from __future__`` (aside from a single module docstring, which the
    embedded source already owns).
    """
    out: List[str] = []
    for line in lines:
        if line == "":
            out.append("")
        else:
            out.append("# " + line if not line.startswith("#") else line)
    return out


def _compose_script(kind: Optional[str], paths: List[str]) -> str:
    """Build a single script_text suitable for display / re-submit.

    Multi-module algorithms are **self-contained bundles** (see
    ``tools/bundle_submission.py``). The harness blocks repo-local outside
    imports; only this file + stdlib + site-packages run. Seed *metrics* remain
    the frozen offline predictions either way.

    Any seed-only banner must be ``#`` comments (or empty lines), never a
    leading triple-quoted string — see ``_comment_block``.
    """
    # Local import: curate may run without tools/ already on path in odd envs.
    sys.path.insert(0, str(_HERE))
    import bundle_submission as bundle  # noqa: E402

    if not kind or kind == "single":
        return _read_text(paths[0]).rstrip() + "\n"

    if kind == "ocr_override":
        return bundle.bundle_example_ocr_override()

    if kind == "ensemble_v2":
        return bundle.bundle_example_ensemble_v2()

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

    # Fail fast: seed script_text is re-submitted via New Run / clone.
    # A leading seed docstring before an embedded ``from __future__`` used to
    # ship broken baselines that only failed at evaluation time.
    try:
        compile(script_text, f"{spec['name']}__v{spec['version']}.py", "exec")
    except SyntaxError as e:
        raise SystemExit(
            f"[curate] script_text for {spec['name']} v{spec['version']} "
            f"does not compile: {e}"
        ) from e

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
