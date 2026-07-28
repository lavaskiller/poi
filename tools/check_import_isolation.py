#!/usr/bin/env python3
"""Assert the eval backend imports without the heavy ML/native stack.

The rules-first backend (``server.py`` + stdlib ``tools/``) must import cleanly
with only the standard library (Pillow is imported lazily, not at load). FastVLM
/ torch live in a separate venv and are invoked as *subprocesses*; if a refactor
ever makes ``import server`` pull in torch, transformers, or numpy, the tiny
deterministic container and the third-party-free test suite both quietly break.

This is that trip-wire. It imports the backend surface in a fresh interpreter
view and fails loud if any denied module got loaded. Standard library only, so
it runs in CI with zero installed wheels.

Exit code 0 = isolated; 1 = a denied module leaked in or an import failed.
"""

from __future__ import annotations

import importlib
import os
import sys

# Backend modules that must import without the heavy stack.
BACKEND_MODULES = ("server", "match_score", "run_algorithm", "run_manifest")

# Modules that must NOT be loaded as a side effect of importing the backend.
DENIED = ("torch", "torchvision", "transformers", "numpy", "cv2", "sklearn")


def main() -> int:
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(tools_dir, ".."))
    for p in (tools_dir, repo_root):
        if p not in sys.path:
            sys.path.insert(0, p)

    failures = []
    for mod in BACKEND_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as e:  # pragma: no cover - reported, not raised
            failures.append(f"import {mod} failed: {e!r}")

    leaked = sorted(m for m in DENIED if m in sys.modules)
    if leaked:
        failures.append("heavy modules loaded at import: " + ", ".join(leaked))

    if failures:
        print("IMPORT ISOLATION: FAIL", file=sys.stderr)
        for f in failures:
            print("  - " + f, file=sys.stderr)
        return 1

    print(
        "IMPORT ISOLATION: OK — "
        f"{len(BACKEND_MODULES)} backend modules import, none of "
        f"{{{', '.join(DENIED)}}} loaded"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
