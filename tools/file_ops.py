#!/usr/bin/env python3
"""Cross-process file locking and atomic writes for shared eval artifacts.

Used by run versioning, CSV/TSV mutations, and other multi-writer paths so CLI
and the dashboard server do not clobber each other.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover — non-Unix
    fcntl = None  # type: ignore


@contextmanager
def file_lock(path: str, *, shared: bool = False) -> Iterator[None]:
    """Advisory exclusive (default) or shared lock keyed by ``path + '.lock'``."""
    lock_path = path + ".lock"
    parent = os.path.dirname(lock_path) or "."
    os.makedirs(parent, exist_ok=True)
    # Open (or create) the lock file; content is unused.
    fd = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(fd.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()


def atomic_write_text(path: str, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` via temp file + ``os.replace`` (atomic on POSIX)."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, obj: Any, *, indent: int = 2) -> None:
    """Serialize ``obj`` as UTF-8 JSON and write atomically."""
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    if not text.endswith("\n"):
        text += "\n"
    atomic_write_text(path, text)


def atomic_write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
