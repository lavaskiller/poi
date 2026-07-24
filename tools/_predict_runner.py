#!/usr/bin/env python3
"""Subprocess wrapper that runs a submitted Python `predict(case)` over a
stream of cases.

Protocol (kept identical for other languages so the harness is language
agnostic): read one JSON `case` object per stdin line, write one JSON result
object per stdout line, in the same order. A result is normalized to
`{"prediction": <str>, "reason": <str|null>, "error": <str|null>,
  "latency_ms": <float|null>}`.

The submitted script is isolated in its own process; the harness enforces the
timeout. The `case` object never contains the ground-truth place name, so a
script cannot score itself by reading the answer.

Import policy
-------------
* **Allowed:** Python stdlib and installed site-packages (real packages).
* **Allowed:** other ``.py`` files in the *same submission directory* only
  (for a future multi-file package layout).
* **Blocked:** repo-local code such as ``examples/``, ``tools/``, or the
  checkout root — submissions must not depend on sibling modules that are
  not part of the submitted package.

Fail-loud rules
---------------
1. **Import preflight** — every absolute ``import`` / ``from … import`` in the
   submission source must resolve under the isolated path *before* any case
   runs. Soft ``try/except ImportError`` cannot hide a missing package or a
   repo-local sibling: the preflight still fails the process.
2. **Case errors abort the run** — if ``predict(case)`` raises, the runner
   exits non-zero after printing the failed case. The harness must not score
   a partial / empty-prediction leaderboard for dependency failures.

`latency_ms` is host-side wall time for one predict() call on this machine.
It is not a mobile-device measurement.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import time


def _abspath(path: str) -> str:
    return os.path.abspath(path) if path else path


def _isolate_import_path(submission_path: str) -> None:
    """Restrict local source imports to the submission directory.

    Keeps stdlib + site-packages on ``sys.path``. Removes the harness
    ``tools/`` directory (normally ``sys.path[0]`` when this runner is the
    invoked script), the repo root, and ``examples/`` so bare imports like
    ``import selector_list_fit`` or ``import match_score`` cannot resolve to
    checkout files that are not part of the submission.
    """
    submission_dir = _abspath(os.path.dirname(submission_path))
    runner_dir = _abspath(os.path.dirname(__file__))
    repo_root = _abspath(os.path.join(runner_dir, ".."))
    examples_dir = os.path.join(repo_root, "examples")
    blocked = {
        runner_dir,
        repo_root,
        examples_dir,
        _abspath(os.path.join(repo_root, "tools")),
    }

    cleaned = []
    seen = set()
    for entry in [submission_dir, *sys.path]:
        if entry is None:
            continue
        # Empty / '.' means cwd — only keep if it is the submission dir.
        if entry in ("", "."):
            cwd = _abspath(os.getcwd())
            if cwd in blocked or cwd != submission_dir:
                continue
            key = cwd
            path_entry = cwd
        else:
            path_entry = entry
            key = _abspath(entry)
        if key in blocked:
            continue
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(path_entry if path_entry not in ("", ".") else key)
    sys.path[:] = cleaned


def _top_level_module_names(source: str, filename: str) -> list[str]:
    """Return root module names referenced by import statements in *source*."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise SystemExit(f"submission syntax error: {e}") from e

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".", 1)[0]
                if root:
                    names.add(root)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports need a package layout; single-file submissions
            # must use absolute imports or inlined modules.
            if getattr(node, "level", 0):
                raise SystemExit(
                    "import preflight failed: relative imports are not "
                    "supported in harness submissions (inline siblings or use "
                    "an absolute package import)"
                )
            if node.module:
                root = node.module.split(".", 1)[0]
                if root:
                    names.add(root)
    # __future__ is a compiler directive, not a runtime package dependency.
    names.discard("__future__")
    return sorted(names)


def _preflight_imports(script_path: str) -> None:
    """Fail before predict() if any static import cannot resolve.

    This closes the hole where submissions wrap missing deps in
    ``try/except ImportError`` and silently fall back to nearest-neighbour.
    """
    with open(script_path, encoding="utf-8") as fh:
        source = fh.read()
    submission_dir = _abspath(os.path.dirname(script_path))
    for name in _top_level_module_names(source, script_path):
        local_py = os.path.join(submission_dir, f"{name}.py")
        local_pkg = os.path.join(submission_dir, name, "__init__.py")
        if os.path.isfile(local_py) or os.path.isfile(local_pkg):
            continue
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            raise SystemExit(
                f"import preflight failed: no module named {name!r} "
                "(install the package on this host, or include the module in "
                "the submission; repo-local modules outside the submission "
                "directory are blocked)"
            )


def _load_predict(path):
    _isolate_import_path(path)
    _preflight_imports(path)
    spec = importlib.util.spec_from_file_location("submitted_predict", path)
    mod = importlib.util.module_from_spec(spec)
    # Register so inlined bundles / relative helpers resolve consistently.
    sys.modules["submitted_predict"] = mod
    spec.loader.exec_module(mod)
    fn = getattr(mod, "predict", None)
    if not callable(fn):
        raise SystemExit("submitted script defines no callable predict(case)")
    return fn


def _normalize(out):
    if isinstance(out, dict):
        return {"prediction": str(out.get("prediction") or "").strip(),
                "reason": out.get("reason")}
    if out is None:
        return {"prediction": "", "reason": None}
    return {"prediction": str(out).strip(), "reason": None}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: _predict_runner.py <script.py>")
    predict = _load_predict(sys.argv[1])
    case_index = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        t0 = time.perf_counter()
        try:
            res = _normalize(predict(case))
            res["error"] = None
        except Exception as e:
            # Fail the whole submission — do not emit a scored empty prediction
            # that can look like a legitimate low-accuracy run.
            latency = round((time.perf_counter() - t0) * 1000.0, 3)
            photo = ""
            if isinstance(case, dict):
                photo = str(case.get("photo") or case.get("photo_url") or "")
            raise SystemExit(
                f"submission failed on case {case_index}"
                + (f" ({photo})" if photo else "")
                + f": {e!r}"
            ) from e
        res["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        case_index += 1


if __name__ == "__main__":
    main()
