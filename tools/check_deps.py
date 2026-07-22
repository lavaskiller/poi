#!/usr/bin/env python3
"""Runtime dependency gate for POI Eval.

Used by:
  - ``python3 tools/check_deps.py`` (CLI)
  - ``server.py`` boot (refuse to listen if hard deps missing)
  - ``GET /api/deps-status`` (SPA boot gate)

Hard failures block the server and the UI. Soft items are reported as
warnings only (e.g. frontend node_modules when you only run the API).

Escape hatch: ``POI_SKIP_DEPS_CHECK=1``.
"""

from __future__ import annotations

import importlib
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# tools/ → repo root
REPO_DIR = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = REPO_DIR / "requirements.txt"

# pip distribution name → importable top-level module
_DIST_TO_IMPORT = {
    "pillow": "PIL",
    "pil": "PIL",
}

MIN_PYTHON = (3, 9)

# macOS-only toolchain used by MapKit / Vision / EXIF jobs
_SWIFT_SCRIPTS = (
    "ls_mapkit_probe.swift",
    "exif_extract.swift",
    "ocr_all.swift",
    "geocode_reverse.swift",
    "gt_mapkit_classify.swift",
)


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_requirements(path: Path) -> List[str]:
    """Return pip distribution names from a simple requirements.txt."""
    if not path.is_file():
        return []
    names: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip env markers / editable / options
        if line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()
        # "Pillow>=10,<12" → Pillow
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if m:
            names.append(m.group(1))
    return names


def _item(
    key: str,
    label: str,
    *,
    ok: bool,
    required: bool,
    detail: str,
    fix: str = "",
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ok": ok,
        "required": required,
        "detail": detail,
        "fix": fix or None,
    }


def _check_python_version() -> Dict[str, Any]:
    ver = sys.version_info
    ok = (ver.major, ver.minor) >= MIN_PYTHON
    need = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+"
    have = f"{ver.major}.{ver.minor}.{ver.micro}"
    return _item(
        "python",
        f"Python {need}",
        ok=ok,
        required=True,
        detail=f"Found {have}" if ok else f"Found {have}; need {need}",
        fix="Install Python 3.9+ (python.org or Xcode CLT / pyenv).",
    )


def _check_pip_packages() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    dists = _parse_requirements(REQUIREMENTS_PATH)
    if not dists:
        items.append(
            _item(
                "requirements_txt",
                "requirements.txt",
                ok=False,
                required=True,
                detail=f"Missing or empty: {REQUIREMENTS_PATH}",
                fix="Restore requirements.txt from the repo and re-run.",
            )
        )
        return items

    for dist in dists:
        mod_name = _DIST_TO_IMPORT.get(dist.lower(), dist.replace("-", "_"))
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", None) or getattr(mod, "VERSION", None)
            detail = f"import {mod_name}" + (f" ({ver})" if ver else " OK")
            items.append(
                _item(
                    f"py:{dist}",
                    dist,
                    ok=True,
                    required=True,
                    detail=detail,
                )
            )
        except Exception as e:
            items.append(
                _item(
                    f"py:{dist}",
                    dist,
                    ok=False,
                    required=True,
                    detail=f"import {mod_name} failed: {e}",
                    fix="python3 -m pip install -r requirements.txt",
                )
            )
    return items


def _check_swift_toolchain() -> List[Dict[str, Any]]:
    """MapKit / Vision probes are Swift + Apple frameworks — not pip."""
    items: List[Dict[str, Any]] = []
    system = platform.system()
    if system != "Darwin":
        items.append(
            _item(
                "swift",
                "Swift + MapKit",
                ok=True,
                required=False,
                detail=f"{system}: live MapKit probe unavailable (macOS only)",
            )
        )
        return items

    swift = shutil.which("swift")
    if swift:
        items.append(
            _item(
                "swift",
                "Swift toolchain",
                ok=True,
                required=True,
                detail=f"swift at {swift}",
            )
        )
    else:
        items.append(
            _item(
                "swift",
                "Swift toolchain",
                ok=False,
                required=True,
                detail="`swift` not found on PATH",
                fix="Install Xcode or Command Line Tools: xcode-select --install",
            )
        )

    swift_dir = REPO_DIR / "tools" / "swift"
    for name in _SWIFT_SCRIPTS:
        path = swift_dir / name
        ok = path.is_file()
        items.append(
            _item(
                f"swift_script:{name}",
                f"tools/swift/{name}",
                ok=ok,
                required=True,
                detail="present" if ok else "missing from checkout",
                fix="git pull --ff-only  # restore tools/swift scripts",
            )
        )
    return items


def _check_frontend_modules() -> Dict[str, Any]:
    """Warn when web/node_modules is missing (Vite needs npm install)."""
    nm = REPO_DIR / "web" / "node_modules"
    pkg = REPO_DIR / "web" / "package.json"
    if not pkg.is_file():
        return _item(
            "web_package",
            "web/package.json",
            ok=False,
            required=False,
            detail="frontend package.json missing",
            fix="git pull --ff-only",
        )
    if nm.is_dir():
        return _item(
            "web_node_modules",
            "web/node_modules",
            ok=True,
            required=False,
            detail="present",
        )
    return _item(
        "web_node_modules",
        "web/node_modules",
        ok=False,
        required=False,
        detail="missing — frontend dev server will not start",
        fix="npm --prefix web install",
    )


def check_runtime_deps() -> Dict[str, Any]:
    """Return a structured dependency report.

    ``ok`` / ``ready`` is False when any *required* item fails.
    """
    if _truthy_env("POI_SKIP_DEPS_CHECK"):
        return {
            "ok": True,
            "ready": True,
            "skipped": True,
            "platform": platform.system(),
            "message": "Dependency check disabled (POI_SKIP_DEPS_CHECK).",
            "items": [],
            "missing": [],
            "warnings": [],
            "install_commands": [],
        }

    items: List[Dict[str, Any]] = []
    items.append(_check_python_version())
    items.extend(_check_pip_packages())
    items.extend(_check_swift_toolchain())
    items.append(_check_frontend_modules())

    missing = [i for i in items if i["required"] and not i["ok"]]
    warnings = [i for i in items if (not i["required"]) and not i["ok"]]
    ready = len(missing) == 0

    fixes: List[str] = []
    for i in missing + warnings:
        fix = i.get("fix")
        if fix and fix not in fixes:
            fixes.append(fix)

    # Always surface the canonical pip line when any py: package is missing.
    if any(i["key"].startswith("py:") and not i["ok"] for i in items):
        cmd = "python3 -m pip install -r requirements.txt"
        if cmd not in fixes:
            fixes.insert(0, cmd)

    if ready and not warnings:
        message = "All required runtime dependencies are available."
    elif ready:
        message = "Required deps OK; optional items missing (see warnings)."
    else:
        labels = ", ".join(i["label"] for i in missing)
        message = f"Missing required dependencies: {labels}"

    return {
        "ok": ready,
        "ready": ready,
        "skipped": False,
        "platform": platform.system(),
        "message": message,
        "items": items,
        "missing": [
            {"key": i["key"], "label": i["label"], "detail": i["detail"], "fix": i.get("fix")}
            for i in missing
        ],
        "warnings": [
            {"key": i["key"], "label": i["label"], "detail": i["detail"], "fix": i.get("fix")}
            for i in warnings
        ],
        "install_commands": fixes,
        "requirements_file": str(REQUIREMENTS_PATH.relative_to(REPO_DIR)),
    }


def format_report(report: Dict[str, Any]) -> str:
    lines = [report.get("message") or ""]
    for i in report.get("items") or []:
        mark = "OK " if i.get("ok") else ("!! " if i.get("required") else "·· ")
        lines.append(f"  {mark}{i.get('label')}: {i.get('detail')}")
    cmds = report.get("install_commands") or []
    if cmds:
        lines.append("Fix:")
        for c in cmds:
            lines.append(f"  {c}")
    return "\n".join(lines)


def _missing_pip_packages(report: Dict[str, Any]) -> List[str]:
    out = []
    for m in report.get("missing") or []:
        key = m.get("key") or ""
        if key.startswith("py:"):
            out.append(key.split(":", 1)[1])
    return out


def ensure_runtime_deps(*, auto_pip: Optional[bool] = None) -> Dict[str, Any]:
    """Check deps; optionally ``pip install -r requirements.txt`` for missing packages.

    Auto-pip runs when any required *pip* package is missing, unless
    ``POI_NO_AUTO_PIP=1``. Non-pip failures (Swift, Python version) still block.
    """
    report = check_runtime_deps()
    if report.get("ready") or report.get("skipped"):
        return report

    missing_pip = _missing_pip_packages(report)
    if auto_pip is None:
        auto_pip = not _truthy_env("POI_NO_AUTO_PIP")
    if not missing_pip or not auto_pip:
        return report

    req = REQUIREMENTS_PATH
    if not req.is_file():
        return report

    print(
        f"Missing pip packages ({', '.join(missing_pip)}); "
        f"running: {sys.executable} -m pip install -r {req}",
        file=sys.stderr,
    )
    try:
        import subprocess

        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "pip failed").strip()
            print(f"auto pip install failed:\n{err[:800]}", file=sys.stderr)
            report = check_runtime_deps()
            report["auto_pip"] = {
                "attempted": True,
                "ok": False,
                "detail": err[:400],
            }
            return report
    except Exception as e:
        print(f"auto pip install error: {e}", file=sys.stderr)
        report = check_runtime_deps()
        report["auto_pip"] = {"attempted": True, "ok": False, "detail": str(e)}
        return report

    report = check_runtime_deps()
    report["auto_pip"] = {
        "attempted": True,
        "ok": bool(report.get("ready")) or not _missing_pip_packages(report),
        "detail": f"installed from {req.name}",
    }
    if report["auto_pip"]["ok"]:
        print("auto pip install succeeded.", file=sys.stderr)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    # CLI: try auto-pip so `python3 tools/check_deps.py` heals Pillow etc.
    report = ensure_runtime_deps(auto_pip=True)
    print(format_report(report))
    if report.get("auto_pip"):
        print(f"auto_pip: {report['auto_pip']}")
    return 0 if report.get("ready") else 1


if __name__ == "__main__":
    sys.exit(main())
