#!/usr/bin/env python3
"""Frozen, group-aware train/validation/test split for the POI eval cohort.

Why a policy instead of a checked-in id list
--------------------------------------------
The eval rows carry private photo filenames and capture GPS; committing a
per-photo split table would leak them into git (the whole ``poi-data/`` tree is
deliberately gitignored for exactly this reason).  Instead we freeze a *policy*:
a salt, the split ratios, the group definition, the eligibility rule, and the
SHA-256 of the source CSV.  Split membership is a **pure deterministic function**
of ``(csv, policy)`` — so pinning the policy + CSV hash freezes the split
exactly, and it can be re-materialized anywhere without exposing ids.

Leak-free by construction
-------------------------
Rows are assigned by *group*, not individually.  The group key clusters photos
that share a place/session/source (``dataset | username | geocell``), and an
entire group is hashed to a single split.  A place shot repeatedly, or a burst
of consecutive photos, can therefore never straddle train and test — the main
source of leaderboard-overfitting in this dataset.

Only *eligible* rows (canonical GT, MapKit provider, non-Korea, not non-POI)
enter the split, matching the runner's own ``row_ineligibility`` policy.

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _TOOLS_DIR)
import match_score as ms  # noqa: E402
import run_algorithm as ra  # noqa: E402
from file_ops import atomic_write_json  # noqa: E402

SCHEMA_VERSION = "eval-split/v1"
# Frozen salt: changing it reshuffles every group into a different split, so it
# is part of the committed policy and must not be edited casually.
DEFAULT_SALT = "poi-eval-split-v1"
DEFAULT_RATIOS = {"train": 0.6, "val": 0.2, "test": 0.2}
# ~1e-3 deg ≈ 110 m: coarse enough to pool a place/session, fine enough not to
# merge unrelated locations across a city.
GEOCELL_DECIMALS = 3
_REPO_ROOT = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
DEFAULT_POLICY_PATH = os.path.join(_REPO_ROOT, "eval", "splits", "split.v1.policy.json")


def geocell(lat: str, lon: str) -> Optional[str]:
    try:
        return f"{round(float(lat), GEOCELL_DECIMALS)},{round(float(lon), GEOCELL_DECIMALS)}"
    except (TypeError, ValueError):
        return None


def group_key(row: Dict[str, str]) -> str:
    """Cluster photos of the same place/session/source into one group.

    Falls back to a per-photo group when GPS is absent: a lone row is its own
    group, which is still leak-free (it cannot span splits).
    """
    ds = (row.get("dataset") or "").strip()
    user = (row.get("username") or "").strip()
    cell = geocell(row.get("capture_lat"), row.get("capture_lon"))
    if cell is None:
        return f"{ds}|{user}|photo:{(row.get('photo') or '').strip()}"
    return f"{ds}|{user}|{cell}"


def assign_split(group: str, salt: str, ratios: Dict[str, float]) -> str:
    """Map a group deterministically to one split via a hashed bucket in [0,1000)."""
    h = hashlib.sha256(f"{salt}\0{group}".encode("utf-8")).hexdigest()
    bucket = int(h, 16) % 1000
    test_hi = int(round(ratios["test"] * 1000))
    val_hi = test_hi + int(round(ratios["val"] * 1000))
    if bucket < test_hi:
        return "test"
    if bucket < val_hi:
        return "val"
    return "train"


def iter_eligible(rows: List[Dict[str, str]], cfg: Dict[str, Any]):
    """Yield rows that pass the runner's eligibility policy."""
    for row in rows:
        if ra.row_ineligibility(row, cfg) is None:
            yield row


def membership(rows: List[Dict[str, str]], cfg: Dict[str, Any],
               salt: str = DEFAULT_SALT,
               ratios: Dict[str, float] = DEFAULT_RATIOS,
               ) -> Dict[Tuple[str, str], str]:
    """Return ``{(dataset, photo): split}`` for every eligible row."""
    out: Dict[Tuple[str, str], str] = {}
    for row in iter_eligible(rows, cfg):
        g = group_key(row)
        split = assign_split(g, salt, ratios)
        key = ((row.get("dataset") or "").strip(), (row.get("photo") or "").strip())
        out[key] = split
    return out


def _csv_sha256(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_policy(csv_path: Optional[str] = None, config_path: Optional[str] = None,
                 salt: str = DEFAULT_SALT, ratios: Dict[str, float] = DEFAULT_RATIOS,
                 ) -> Dict[str, Any]:
    """Compute the frozen policy (counts + CSV identity), no per-photo ids."""
    csv_path = csv_path or ms.CSV_PATH
    cfg = ms.load_config(config_path or ms.CONFIG_PATH)
    rows = ms.read_rows(csv_path)
    rows, _n = ms.overlay_gt_mapkit_overrides(rows)
    mem = membership(rows, cfg, salt, ratios)
    groups = {group_key(r) for r in iter_eligible(rows, cfg)}
    counts = {"train": 0, "val": 0, "test": 0}
    for split in mem.values():
        counts[split] += 1
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "salt": salt,
        "ratios": ratios,
        "group_definition": f"dataset|username|geocell@{GEOCELL_DECIMALS}dp(lat,lon)",
        "eligibility": ("canonical GT, MapKit provider, non-Korea, not non_poi "
                        "(run_algorithm.row_ineligibility)"),
        "source_csv_sha256": _csv_sha256(csv_path),
        "counts": {**counts, "eligible": sum(counts.values()), "groups": len(groups)},
    }


def materialize(csv_path: Optional[str] = None, config_path: Optional[str] = None,
                salt: str = DEFAULT_SALT, ratios: Dict[str, float] = DEFAULT_RATIOS,
                ) -> List[Dict[str, str]]:
    """Full id→split assignment (for inspection; keep under the gitignored root)."""
    csv_path = csv_path or ms.CSV_PATH
    cfg = ms.load_config(config_path or ms.CONFIG_PATH)
    rows = ms.read_rows(csv_path)
    rows, _n = ms.overlay_gt_mapkit_overrides(rows)
    mem = membership(rows, cfg, salt, ratios)
    return [
        {"dataset": ds, "photo": ph, "split": split}
        for (ds, ph), split in sorted(mem.items())
    ]


def verify(policy: Dict[str, Any], csv_path: Optional[str] = None,
           config_path: Optional[str] = None) -> Dict[str, Any]:
    """Re-derive the split and check the committed policy still holds.

    Checks: (1) no group spans splits, (2) counts match the committed policy,
    (3) the source CSV SHA-256 matches (else the split drifted vs the data).
    """
    salt = policy.get("salt", DEFAULT_SALT)
    ratios = policy.get("ratios", DEFAULT_RATIOS)
    csv_path = csv_path or ms.CSV_PATH
    cfg = ms.load_config(config_path or ms.CONFIG_PATH)
    rows = ms.read_rows(csv_path)
    rows, _n = ms.overlay_gt_mapkit_overrides(rows)

    # (1) group atomicity — a group must never map to two splits. This is true
    # by construction (split = f(group)); we still assert it defensively.
    group_split: Dict[str, str] = {}
    straddlers = set()
    for row in iter_eligible(rows, cfg):
        g = group_key(row)
        split = assign_split(g, salt, ratios)
        if g in group_split and group_split[g] != split:
            straddlers.add(g)
        group_split[g] = split

    # Counts use the same unique-case basis as build_policy (dedupe repeated
    # (dataset, photo) rows), so verify and freeze always agree.
    mem = membership(rows, cfg, salt, ratios)
    counts = {"train": 0, "val": 0, "test": 0}
    for split in mem.values():
        counts[split] += 1

    committed_counts = policy.get("counts", {})
    csv_sha = _csv_sha256(csv_path)
    problems = []
    if straddlers:
        problems.append(f"{len(straddlers)} group(s) span multiple splits")
    for k in ("train", "val", "test"):
        if committed_counts.get(k) != counts[k]:
            problems.append(
                f"count drift {k}: committed={committed_counts.get(k)} actual={counts[k]}")
    csv_drift = policy.get("source_csv_sha256") not in (None, csv_sha)
    if csv_drift:
        problems.append("source CSV SHA-256 changed since the policy was frozen")
    return {
        "ok": not problems,
        "problems": problems,
        "actual_counts": counts,
        "csv_sha256": csv_sha,
        "csv_drift": csv_drift,
    }


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_freeze = sub.add_parser("freeze", help="compute + write the tracked policy file")
    p_freeze.add_argument("--out", default=DEFAULT_POLICY_PATH)
    p_freeze.add_argument("--csv", default=None)

    p_mat = sub.add_parser("materialize", help="write full id→split table (keep gitignored)")
    p_mat.add_argument("--out", required=True)
    p_mat.add_argument("--csv", default=None)

    p_ver = sub.add_parser("verify", help="re-derive and check the committed policy")
    p_ver.add_argument("--policy", default=DEFAULT_POLICY_PATH)
    p_ver.add_argument("--csv", default=None)

    args = ap.parse_args(argv)

    if args.cmd == "freeze":
        policy = build_policy(csv_path=args.csv)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        atomic_write_json(args.out, policy)
        print(json.dumps(policy, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "materialize":
        table = materialize(csv_path=args.csv)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        atomic_write_json(args.out, {"schema": SCHEMA_VERSION, "assignments": table})
        print(f"wrote {len(table)} assignments to {args.out}")
        return 0

    if args.cmd == "verify":
        policy = _load_json(args.policy)
        result = verify(policy, csv_path=args.csv)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
