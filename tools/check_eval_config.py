#!/usr/bin/env python3
"""Validate the committed eval-gate config without touching private data.

The frozen split *policy* and any release *baseline* are the contract the gate
enforces, and they live in git while the CSV they derive from does not. So CI
can't re-derive them (no private CSV), but it CAN check they are internally
coherent — the failure mode that a full re-derive would also catch, minus the
data: a schema rename, ratios that don't sum to 1, counts that don't add up, a
malformed source hash. See docs/release-gate.md and tools/eval_split.py.

A missing baseline is NOT an error: until one is committed the gate runs
report-only (exit 0) by design. Standard library only.

Exit 0 = all committed config is coherent (or absent); 1 = a file is malformed.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SPLITS_GLOB = os.path.join(_REPO_ROOT, "eval", "splits", "*.policy.json")
_BASELINES_GLOB = os.path.join(_REPO_ROOT, "eval", "baselines", "*.json")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _err(problems, path, msg):
    problems.append(f"{os.path.relpath(path, _REPO_ROOT)}: {msg}")


def _check_split_policy(path, problems):
    with open(path, "r", encoding="utf-8") as fh:
        pol = json.load(fh)
    if pol.get("schema") != "eval-split/v1":
        _err(problems, path, f"unexpected schema {pol.get('schema')!r}")
    ratios = pol.get("ratios") or {}
    if set(ratios) != {"train", "val", "test"}:
        _err(problems, path, f"ratios keys must be train/val/test, got {sorted(ratios)}")
    else:
        total = sum(float(v) for v in ratios.values())
        if abs(total - 1.0) > 1e-6:
            _err(problems, path, f"ratios sum to {total}, expected 1.0")
    src = pol.get("source_csv_sha256")
    if not (isinstance(src, str) and _HEX64.match(src)):
        _err(problems, path, "source_csv_sha256 is not a 64-char hex digest")
    counts = pol.get("counts") or {}
    if all(k in counts for k in ("train", "val", "test", "eligible")):
        parts = counts["train"] + counts["val"] + counts["test"]
        if parts != counts["eligible"]:
            _err(
                problems,
                path,
                f"train+val+test ({parts}) != eligible ({counts['eligible']})",
            )


def _check_baseline(path, problems):
    with open(path, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    if base.get("schema") != "release-baseline/v1":
        _err(problems, path, f"unexpected schema {base.get('schema')!r}")
    if not base.get("generated_from_run"):
        _err(problems, path, "missing generated_from_run (baselines are derived, not hand-written)")


def main() -> int:
    problems = []
    policies = sorted(glob.glob(_SPLITS_GLOB))
    if not policies:
        problems.append("eval/splits/: no *.policy.json committed")
    for path in policies:
        try:
            _check_split_policy(path, problems)
        except (OSError, ValueError) as e:
            _err(problems, path, f"unreadable/not JSON: {e}")

    baselines = sorted(glob.glob(_BASELINES_GLOB))
    for path in baselines:
        try:
            _check_baseline(path, problems)
        except (OSError, ValueError) as e:
            _err(problems, path, f"unreadable/not JSON: {e}")

    if problems:
        print("EVAL CONFIG: FAIL", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 1

    note = "report-only (no baseline committed)" if not baselines else f"{len(baselines)} baseline(s)"
    print(f"EVAL CONFIG: OK — {len(policies)} split policy, {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
