#!/usr/bin/env bash
# Portable one-shot development launcher. Works from ANY clone path and starts
# the backend and frontend from this same checkout to prevent API/version skew.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_ONLY=0
SETUP_ONLY=0
SKIP_INSTALL=0
BACKEND_PID=""

usage() {
  cat <<'EOF'
Usage: tools/dev_up.sh [options]

  (no option)       Install/check all deps, then start backend + Vite frontend.
  --backend-only    Install/check backend deps and start only server.py.
                    Missing web/node_modules remains irrelevant to API-only use.
  --setup-only      Install/check all deps, then exit without starting servers.
  --skip-install    Start without pip/npm install; dependency checks still run.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only) BACKEND_ONLY=1 ;;
    --setup-only) SETUP_ONLY=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$BACKEND_ONLY" -eq 1 && "$SETUP_ONLY" -eq 1 ]]; then
  echo "ERROR: --backend-only and --setup-only cannot be combined" >&2
  exit 2
fi

cd "$ROOT"
echo "POI Eval — repo root: $ROOT"

if [[ ! -f "$ROOT/server.py" ]]; then
  echo "ERROR: server.py not found under $ROOT" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 (3.9+) is required but is not on PATH" >&2
  exit 1
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  if [[ "$BACKEND_ONLY" -eq 1 ]]; then
    "$ROOT/tools/setup.sh" --backend-only
  else
    "$ROOT/tools/setup.sh"
  fi
else
  echo "→ skipping installs; validating existing dependencies…"
  python3 "$ROOT/tools/check_deps.py"
  if [[ "$BACKEND_ONLY" -eq 0 ]]; then
    if ! command -v npm >/dev/null 2>&1; then
      echo "ERROR: npm is required for the frontend but is not on PATH" >&2
      exit 1
    fi
    if [[ ! -d "$ROOT/web/node_modules" ]]; then
      echo "ERROR: web/node_modules is missing; run tools/setup.sh" >&2
      exit 1
    fi
  fi
fi

if [[ "$SETUP_ONLY" -eq 1 ]]; then
  exit 0
fi

# Free a stale backend listener on the configured port (ignore races/failures).
PORT="${POI_PORT:-8420}"
if command -v lsof >/dev/null 2>&1; then
  OLD_PIDS="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$OLD_PIDS" ]]; then
    echo "→ stopping old process(es) on :$PORT: $OLD_PIDS"
    # shellcheck disable=SC2086
    kill $OLD_PIDS 2>/dev/null || true
    sleep 0.5
  fi
fi

if [[ "$BACKEND_ONLY" -eq 1 ]]; then
  echo "→ starting backend at http://127.0.0.1:${PORT}"
  exec python3 "$ROOT/server.py"
fi

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo
    echo "→ stopping backend (PID $BACKEND_PID)…"
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "→ starting backend at http://127.0.0.1:${PORT}"
python3 "$ROOT/server.py" &
BACKEND_PID=$!

# Catch immediate boot failures before handing the terminal to Vite.
sleep 0.75
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  wait "$BACKEND_PID"
  echo "ERROR: backend exited during startup" >&2
  exit 1
fi

echo "→ starting frontend at http://localhost:5173"
echo "   Press Ctrl-C once to stop both processes."
npm --prefix "$ROOT/web" run dev -- --strictPort
