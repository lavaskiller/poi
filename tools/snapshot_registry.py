#!/usr/bin/env python3
"""Content-addressed registry + audited promotion for candidate snapshots.

The repo already stores immutable candidate snapshots under
``<data_root>/generated/candidate-snapshots/<id>/`` (each with a
``metadata.json`` carrying ``candidate_artifact_sha256``) and selects one via
the ``active-mapkit-candidate-snapshot.json`` pointer that ``match_score``
verifies fail-loud. What is missing for lineage/rollback is:

  * a **registry index** listing every known snapshot + its content hash,
  * **atomic, verified promotion** of the active pointer, and
  * an **append-only audit log** of who switched the active snapshot, when, from
    what, and why — so a bad promotion can be traced and rolled back.

This tool adds exactly those, writing the *same* pointer format
``match_score.active_mapkit_candidate_file`` already consumes, and refusing to
promote a snapshot whose artifact hash does not match its metadata. It never
mutates snapshot contents.

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _TOOLS_DIR)
import match_score as ms  # noqa: E402
from file_ops import atomic_write_json, file_lock  # noqa: E402

REGISTRY_INDEX = "snapshot-registry.json"
AUDIT_LOG = "snapshot-registry.audit.jsonl"
SNAPSHOT_SUBDIR = "candidate-snapshots"
ARTIFACT_NAME = "mapkit_candidates.jsonl"
SCHEMA_VERSION = "snapshot-registry/v1"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def generated_dir(data_root: Optional[str] = None) -> str:
    return os.path.join(data_root or ms.resolve_data_root(), "generated")


def _sha256(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _snapshot_dir(gen: str, snapshot_id: str) -> str:
    return os.path.join(gen, SNAPSHOT_SUBDIR, snapshot_id)


def inspect(gen: str, snapshot_id: str) -> Dict[str, Any]:
    """Validate a snapshot on disk: metadata present, complete, hash matches."""
    sdir = _snapshot_dir(gen, snapshot_id)
    meta = _read_json(os.path.join(sdir, "metadata.json"))
    if not isinstance(meta, dict):
        return {"snapshot_id": snapshot_id, "valid": False,
                "reason": "missing or unreadable metadata.json"}
    artifact = meta.get("candidate_artifact") or ARTIFACT_NAME
    expected = meta.get("candidate_artifact_sha256")
    actual = _sha256(os.path.join(sdir, artifact))
    problems = []
    if meta.get("snapshot_id") != snapshot_id:
        problems.append("metadata snapshot_id mismatch")
    if meta.get("status") != "complete":
        problems.append(f"status={meta.get('status')!r} (need 'complete')")
    if not (isinstance(expected, str) and len(expected) == 64):
        problems.append("metadata lacks a valid candidate_artifact_sha256")
    elif actual != expected:
        problems.append("artifact SHA-256 does not match metadata")
    return {
        "snapshot_id": snapshot_id,
        "artifact": artifact,
        "artifact_sha256": actual,
        "kind": meta.get("kind"),
        "candidate_records": meta.get("candidate_records"),
        "valid": not problems,
        "reason": "; ".join(problems) if problems else None,
    }


def load_index(gen: str) -> Dict[str, Any]:
    idx = _read_json(os.path.join(gen, REGISTRY_INDEX))
    if not isinstance(idx, dict):
        return {"schema": SCHEMA_VERSION, "snapshots": {}}
    idx.setdefault("snapshots", {})
    return idx


def scan(gen: str) -> List[str]:
    root = os.path.join(gen, SNAPSHOT_SUBDIR)
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root)
                  if os.path.isfile(os.path.join(root, d, "metadata.json")))


def _register_into(idx: Dict[str, Any], gen: str, ids: List[str]) -> Dict[str, Any]:
    """Update ``idx`` in place from ``ids``. Caller owns the lock and the write."""
    registered, skipped = [], []
    for sid in ids:
        info = inspect(gen, sid)
        if not info["valid"]:
            skipped.append({"snapshot_id": sid, "reason": info["reason"]})
            continue
        idx["snapshots"][sid] = {
            "artifact": info["artifact"],
            "content_sha256": info["artifact_sha256"],
            "kind": info["kind"],
            "candidate_records": info["candidate_records"],
            "registered_at": idx["snapshots"].get(sid, {}).get("registered_at") or _now(),
        }
        registered.append(sid)
    idx["updated_at"] = _now()
    return {"registered": registered, "skipped": skipped,
            "total": len(idx["snapshots"])}


def register(gen: str, snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    """Add snapshot(s) to the registry index (idempotent). Refuses invalid ones."""
    ids = [snapshot_id] if snapshot_id else scan(gen)
    with file_lock(os.path.join(gen, ".snapshot-registry")):
        idx = load_index(gen)
        res = _register_into(idx, gen, ids)
        os.makedirs(gen, exist_ok=True)
        atomic_write_json(os.path.join(gen, REGISTRY_INDEX), idx)
    return res


def current(gen: str) -> Dict[str, Any]:
    ptr = _read_json(os.path.join(gen, ms.ACTIVE_MAPKIT_SNAPSHOT_POINTER))
    if not isinstance(ptr, dict):
        return {"active": None}
    return {"active": ptr.get("snapshot_id"),
            "candidate_artifact": ptr.get("candidate_artifact"),
            "selected_at": ptr.get("selected_at"),
            "selection_reason": ptr.get("selection_reason")}


def _append_audit(gen: str, entry: Dict[str, Any]) -> None:
    os.makedirs(gen, exist_ok=True)
    with open(os.path.join(gen, AUDIT_LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def promote(gen: str, snapshot_id: str, reason: str,
            actor: Optional[str] = None) -> Dict[str, Any]:
    """Atomically point the active snapshot at ``snapshot_id`` after verifying it.

    Writes the pointer format ``match_score`` consumes and appends an audit
    record (previous → new) so the switch is traceable and reversible.
    """
    info = inspect(gen, snapshot_id)
    if not info["valid"]:
        raise ValueError(f"refusing to promote {snapshot_id}: {info['reason']}")
    if info["artifact"] != ARTIFACT_NAME:
        raise ValueError(
            f"refusing to promote {snapshot_id}: artifact is {info['artifact']!r}, "
            f"but the active pointer requires {ARTIFACT_NAME!r}")
    with file_lock(os.path.join(gen, ".snapshot-registry")):
        prev = current(gen).get("active")
        pointer = {
            "snapshot_id": snapshot_id,
            "candidate_artifact": ARTIFACT_NAME,
            "selected_at": _now(),
            "selection_reason": reason,
        }
        atomic_write_json(os.path.join(gen, ms.ACTIVE_MAPKIT_SNAPSHOT_POINTER), pointer)
        _append_audit(gen, {
            "ts": pointer["selected_at"],
            "action": "promote",
            "snapshot_id": snapshot_id,
            "previous_snapshot_id": prev,
            "content_sha256": info["artifact_sha256"],
            "reason": reason,
            "actor": actor or os.environ.get("USER") or "unknown",
        })
        # keep the index current too (already holding the lock — no re-lock)
        idx = load_index(gen)
        _register_into(idx, gen, [snapshot_id])
        atomic_write_json(os.path.join(gen, REGISTRY_INDEX), idx)
    return {"active": snapshot_id, "previous": prev,
            "content_sha256": info["artifact_sha256"]}


def history(gen: str) -> List[Dict[str, Any]]:
    path = os.path.join(gen, AUDIT_LOG)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def rollback(gen: str, reason: str, actor: Optional[str] = None) -> Dict[str, Any]:
    """Promote the previously-active snapshot from the audit log."""
    hist = [h for h in history(gen) if h.get("action") == "promote"]
    if not hist:
        raise ValueError("no promotion history to roll back to")
    prev = hist[-1].get("previous_snapshot_id")
    if not prev:
        raise ValueError("last promotion has no previous snapshot to restore")
    return promote(gen, prev, f"rollback: {reason}", actor=actor)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None,
                    help="override data root (default: match_score.resolve_data_root)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="list snapshot ids present on disk")
    p_reg = sub.add_parser("register", help="add snapshot(s) to the registry index")
    p_reg.add_argument("--snapshot-id", default=None)
    sub.add_parser("list", help="print the registry index")
    sub.add_parser("current", help="print the active snapshot pointer")
    p_ins = sub.add_parser("inspect", help="validate one snapshot on disk")
    p_ins.add_argument("snapshot_id")
    p_pro = sub.add_parser("promote", help="atomically switch the active snapshot")
    p_pro.add_argument("snapshot_id")
    p_pro.add_argument("--reason", required=True)
    p_pro.add_argument("--actor", default=None)
    sub.add_parser("history", help="print the promotion audit log")
    p_rb = sub.add_parser("rollback", help="restore the previously-active snapshot")
    p_rb.add_argument("--reason", required=True)
    p_rb.add_argument("--actor", default=None)

    args = ap.parse_args(argv)
    gen = generated_dir(args.data_root)

    if args.cmd == "scan":
        print(json.dumps(scan(gen), indent=2))
    elif args.cmd == "register":
        print(json.dumps(register(gen, args.snapshot_id), indent=2, ensure_ascii=False))
    elif args.cmd == "list":
        print(json.dumps(load_index(gen), indent=2, ensure_ascii=False))
    elif args.cmd == "current":
        print(json.dumps(current(gen), indent=2, ensure_ascii=False))
    elif args.cmd == "inspect":
        print(json.dumps(inspect(gen, args.snapshot_id), indent=2, ensure_ascii=False))
    elif args.cmd == "promote":
        print(json.dumps(promote(gen, args.snapshot_id, args.reason, args.actor),
                         indent=2, ensure_ascii=False))
    elif args.cmd == "history":
        print(json.dumps(history(gen), indent=2, ensure_ascii=False))
    elif args.cmd == "rollback":
        print(json.dumps(rollback(gen, args.reason, args.actor),
                         indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
