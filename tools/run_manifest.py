#!/usr/bin/env python3
"""Full-lineage manifest for POI evaluation runs.

The run record already pins the *submission* (script SHA-256), the *cohort*
(evaluation_set_sha256), and the *input files* (data_snapshot_sha256). That is
enough to compare two runs, but not enough to *reproduce* one: the same run id
can hide a different code checkout, a different FastVLM checkpoint, a re-pointed
candidate snapshot, or a warm VLM cache.

``build()`` gathers the rest of what determines a result into one manifest that
is embedded in the run JSON and can be re-emitted for an audit:

  * ``code``     — git SHA, dirty flag, branch, describe
  * ``runtime``  — python / platform / machine, container image digest (env)
  * ``model``    — FastVLM commit + checkpoint SHA-256 from the pin file
  * ``prompt``   — prompt/template version (env or file digest)
  * ``inputs``   — per-artifact SHA-256 for candidate / OCR / scene / index
  * ``cache``    — VLM cache schema + key-space digest (env)
  * ``deps``     — requirements lock digest

Every collector is defensive: a missing tool, file, or env var degrades to
``None``/``"<missing>"`` and never raises, so attaching a manifest can never
fail a run. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "run-manifest/v1"

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
FASTVLM_LOCK = os.path.join(_TOOLS_DIR, "fastvlm.lock.json")
REQUIREMENTS_LOCK = os.path.join(_REPO_ROOT, "requirements.lock")
REQUIREMENTS_TXT = os.path.join(_REPO_ROOT, "requirements.txt")


def sha256_file(path: str, *, max_bytes: Optional[int] = None) -> Optional[str]:
    """Chunked SHA-256 of a file, or ``None`` if it is missing/unreadable.

    ``max_bytes`` caps the read for very large artifacts (e.g. a multi-GB
    checkpoint) where a prefix digest is enough to detect a swap; when capped
    the returned digest is tagged so it is never confused with a full hash.
    """
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                if max_bytes is not None and read + len(block) > max_bytes:
                    digest.update(block[: max_bytes - read])
                    return "prefix:" + digest.hexdigest()
                digest.update(block)
                read += len(block)
    except OSError:
        return None
    return digest.hexdigest()


def _git(args: List[str], repo_root: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def git_provenance(repo_root: str = _REPO_ROOT) -> Dict[str, Any]:
    """Code identity: commit SHA, working-tree cleanliness, branch, describe."""
    sha = _git(["rev-parse", "HEAD"], repo_root)
    status = _git(["status", "--porcelain"], repo_root)
    return {
        "sha": sha,
        # ``status`` is "" (clean) or a non-empty listing; None means git failed.
        "dirty": bool(status) if status is not None else None,
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root),
        "describe": _git(["describe", "--tags", "--always", "--dirty"], repo_root),
    }


def runtime_info() -> Dict[str, Any]:
    """Execution environment, including a container image digest if injected.

    ``POI_IMAGE_DIGEST`` is set by the reproducible-runtime entrypoint (the
    OCI image the eval runs inside); absent for bare-metal local runs.
    """
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "system": platform.system(),
        "image_digest": os.environ.get("POI_IMAGE_DIGEST") or None,
    }


def model_provenance(lock_path: str = FASTVLM_LOCK) -> Dict[str, Any]:
    """FastVLM identity from the pin file, optionally verified against disk.

    The pin file (``tools/fastvlm.lock.json``) records the expected commit,
    torch version, and checkpoint SHA-256 — computed once, not per run.  When
    ``POI_FASTVLM_CHECKPOINT`` points at a local checkpoint we compare its
    digest to the pin so a silently swapped weight file is caught.
    """
    info: Dict[str, Any] = {"pinned": None, "checkpoint_verified": None}
    pin = _read_json(lock_path)
    if isinstance(pin, dict):
        info["pinned"] = {
            "fastvlm_commit": pin.get("fastvlm_commit"),
            "torch": pin.get("torch"),
            "checkpoint": pin.get("checkpoint"),
            "checkpoint_sha256": pin.get("checkpoint_sha256"),
        }
        ckpt = os.environ.get("POI_FASTVLM_CHECKPOINT")
        expected = pin.get("checkpoint_sha256")
        if ckpt and isinstance(expected, str):
            actual = sha256_file(ckpt)
            info["checkpoint_verified"] = (actual == expected)
            info["checkpoint_sha256_actual"] = actual
    return info


def prompt_provenance() -> Dict[str, Any]:
    """Prompt/template version: an explicit tag and/or the digest of a file."""
    version = os.environ.get("POI_PROMPT_VERSION")
    prompt_file = os.environ.get("POI_PROMPT_FILE")
    return {
        "version": version or None,
        "file": prompt_file or None,
        "file_sha256": sha256_file(prompt_file) if prompt_file else None,
    }


def cache_identity() -> Dict[str, Any]:
    """VLM cache identity so a warm/stale cache is part of the run's lineage."""
    return {
        "schema": os.environ.get("POI_VLM_CACHE_SCHEMA") or None,
        "key_digest": os.environ.get("POI_VLM_CACHE_KEY_DIGEST") or None,
        "enabled": _env_bool("POI_VLM_CACHE_ENABLED"),
    }


def deps_digest() -> Dict[str, Any]:
    """Dependency lineage: prefer the pinned lock, fall back to requirements."""
    lock = sha256_file(REQUIREMENTS_LOCK)
    return {
        "requirements_lock_sha256": lock,
        "requirements_txt_sha256": sha256_file(REQUIREMENTS_TXT),
        "locked": lock is not None,
    }


def input_digests(labeled_paths: Dict[str, str]) -> Dict[str, Optional[str]]:
    """Per-artifact SHA-256 for the named inputs (candidate/OCR/scene/index).

    Missing files are recorded as ``"<missing>"`` rather than dropped, so the
    absence itself is part of the manifest identity.
    """
    out: Dict[str, Optional[str]] = {}
    for label, path in labeled_paths.items():
        out[label] = sha256_file(path) if (path and os.path.isfile(path)) else "<missing>"
    return out


def build(
    *,
    input_paths: Optional[Dict[str, str]] = None,
    repo_root: str = _REPO_ROOT,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the full run manifest. Never raises."""
    try:
        manifest: Dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "code": git_provenance(repo_root),
            "runtime": runtime_info(),
            "model": model_provenance(),
            "prompt": prompt_provenance(),
            "cache": cache_identity(),
            "deps": deps_digest(),
            "inputs": input_digests(input_paths or {}),
        }
        if extra:
            manifest["extra"] = extra
        return manifest
    except Exception as e:  # never let lineage capture break a run
        return {"schema": SCHEMA_VERSION, "error": f"{type(e).__name__}: {e}"}


def _read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _env_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
