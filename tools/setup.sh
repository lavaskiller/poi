#!/usr/bin/env bash
# Install and validate dependencies for this checkout, regardless of its path.
# By default this prepares both the Python backend and the Vite frontend.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_ONLY=0

usage() {
  cat <<'EOF'
Usage: tools/setup.sh [--backend-only]

  (no option)       Install Python requirements and web/node_modules.
  --backend-only    Install/check only backend dependencies; npm is not needed.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only) BACKEND_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT"
echo "POI Eval setup — repo root: $ROOT"

if [[ ! -f "$ROOT/server.py" || ! -f "$ROOT/requirements.txt" ]]; then
  echo "ERROR: incomplete checkout: server.py or requirements.txt is missing under $ROOT" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 (3.9+) is required but is not on PATH" >&2
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "ERROR: Python 3.9+ is required; found $(python3 --version 2>&1)" >&2
  exit 1
fi

echo "→ installing Python requirements…"
python3 -m pip install -r "$ROOT/requirements.txt"

echo "→ validating backend and system dependencies…"
python3 "$ROOT/tools/check_deps.py"

if [[ "$BACKEND_ONLY" -eq 1 ]]; then
  echo "✓ backend setup complete (frontend setup intentionally skipped)"
  exit 0
fi

if [[ ! -f "$ROOT/web/package.json" || ! -f "$ROOT/web/package-lock.json" ]]; then
  echo "ERROR: web/package.json or web/package-lock.json is missing" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: Node.js 18+ and npm are required for the frontend but are not on PATH.
Install Node.js (which includes npm), then run tools/setup.sh again.
For API-only backend use, run: tools/setup.sh --backend-only
EOF
  exit 1
fi
NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || true)"
if [[ ! "$NODE_MAJOR" =~ ^[0-9]+$ ]] || (( NODE_MAJOR < 18 )); then
  echo "ERROR: Node.js 18+ is required; found $(node --version 2>&1)" >&2
  exit 1
fi

echo "→ installing frontend dependencies into web/node_modules…"
npm --prefix "$ROOT/web" install

echo "✓ setup complete"
echo "  Start both processes with: $ROOT/tools/dev_up.sh"
