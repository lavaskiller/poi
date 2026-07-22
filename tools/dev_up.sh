#!/usr/bin/env bash
# Portable one-shot backend launcher. Works from ANY clone path
# (Desktop, ~/src, /opt, another machine) — never hardcodes a location.
#
# Usage (from anywhere):
#   /path/to/poi/tools/dev_up.sh
#   # or
#   cd /path/to/poi && ./tools/dev_up.sh
#
# Starts server.py on :8420 after deps check + optional auto-pip.
# Frontend is separate: npm --prefix web run dev  (same repo root).

set -euo pipefail

# Resolve repo root from this script's location (not $PWD, not Desktop).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "POI Eval — repo root: $ROOT"

if [[ ! -f "$ROOT/server.py" ]]; then
  echo "ERROR: server.py not found under $ROOT" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not on PATH" >&2
  exit 1
fi

echo "→ checking / installing Python deps…"
python3 -m pip install -r requirements.txt -q
python3 tools/check_deps.py

# Free a stale listener on the same port (optional; ignore failures).
PORT="${POI_PORT:-8420}"
if command -v lsof >/dev/null 2>&1; then
  OLD_PIDS="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "${OLD_PIDS}" ]]; then
    echo "→ stopping old process(es) on :$PORT: $OLD_PIDS"
    # shellcheck disable=SC2086
    kill $OLD_PIDS 2>/dev/null || true
    sleep 0.5
  fi
fi

echo "→ starting server.py at http://127.0.0.1:${PORT}"
echo "   (frontend: cd \"$ROOT\" && npm --prefix web install && npm --prefix web run dev)"
exec python3 server.py
