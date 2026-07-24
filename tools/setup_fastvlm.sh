#!/usr/bin/env bash
# Automate FastVLM assets under the data root for mapkit-baseline v2 *live* runs.
#
# Git ships our glue code only. This script provisions (or verifies):
#   $POI_DATA_DIR/tools/ml-fastvlm/          # Apple FastVLM checkout
#   $POI_DATA_DIR/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3/
#   $POI_DATA_DIR/tools/fastvlm-venv/        # torch + MPS venv
#
# Requirements: macOS (Apple Silicon recommended), python3, git, curl/unzip,
# network access to GitHub + ml-site.cdn-apple.com.
#
# Usage:
#   ./tools/setup_fastvlm.sh
#   POI_DATA_DIR=/path/to/poi-data ./tools/setup_fastvlm.sh
#   ./tools/setup_fastvlm.sh --skip-model    # repo + venv only
#   ./tools/setup_fastvlm.sh --force-venv    # recreate venv
#
# After success, start the server with:
#   export POI_PREDICT_PYTHON="$POI_DATA_DIR/tools/fastvlm-venv/bin/python"
# Or omit FastVLM and use deterministic core only:
#   export POI_VLM_MODE=off

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_MODEL=0
FORCE_VENV=0
MODEL_ZIP_URL="${POI_FASTVLM_MODEL_URL:-https://ml-site.cdn-apple.com/datasets/fastvlm/llava-fastvithd_0.5b_stage3.zip}"
ML_FASTVLM_GIT="${POI_FASTVLM_GIT:-https://github.com/apple/ml-fastvlm.git}"

usage() {
  cat <<'EOF'
Usage: tools/setup_fastvlm.sh [options]

  (default)       Clone/update ml-fastvlm, download 0.5B stage3 checkpoint,
                  create fastvlm-venv, install torch + llava, smoke-check MPS.
  --skip-model    Skip checkpoint download (repo + venv only).
  --force-venv    Delete and recreate fastvlm-venv.
  -h, --help      Show this help.

Env:
  POI_DATA_DIR          Data root (default: <repo>/poi-data)
  POI_FASTVLM_GIT       ml-fastvlm git URL
  POI_FASTVLM_MODEL_URL Checkpoint zip URL (default: Apple CDN 0.5B stage3)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-model) SKIP_MODEL=1 ;;
    --force-venv) FORCE_VENV=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  cat >&2 <<'EOF'
ERROR: FastVLM live inference in this project expects macOS + MPS.
On Linux/other hosts use:
  export POI_VLM_MODE=off
for the deterministic OCR/access core only.
EOF
  exit 1
fi

# Prefer a newer CPython for the venv when present (Homebrew), else system python3.
PYTHON_BIN=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$c")"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  cat >&2 <<'EOF'
ERROR: no python3 found on PATH.
Install Python 3.9+ (python.org or Homebrew: brew install python@3.11), then re-run.
EOF
  exit 1
fi
echo "→ using $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "ERROR: need Python 3.9+ for the FastVLM venv" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required to clone ml-fastvlm" >&2
  exit 1
fi

DATA_ROOT="${POI_DATA_DIR:-$ROOT/poi-data}"
DATA_ROOT="$(cd "$DATA_ROOT" 2>/dev/null && pwd || true)"
if [[ -z "${DATA_ROOT}" || ! -d "${POI_DATA_DIR:-$ROOT/poi-data}" ]]; then
  # Create default data root if missing (seed not yet applied).
  mkdir -p "${POI_DATA_DIR:-$ROOT/poi-data}"
  DATA_ROOT="$(cd "${POI_DATA_DIR:-$ROOT/poi-data}" && pwd)"
fi

TOOLS="$DATA_ROOT/tools"
REPO_DIR="$TOOLS/ml-fastvlm"
VENV_DIR="$TOOLS/fastvlm-venv"
CKPT_DIR="$REPO_DIR/checkpoints/llava-fastvithd_0.5b_stage3"
PY="$VENV_DIR/bin/python"

echo "POI FastVLM setup"
echo "  repo checkout : $ROOT"
echo "  data root     : $DATA_ROOT"
echo "  ml-fastvlm    : $REPO_DIR"
echo "  venv          : $VENV_DIR"
echo "  checkpoint    : $CKPT_DIR"
echo

mkdir -p "$TOOLS"

# --- ml-fastvlm checkout ---
if [[ -d "$REPO_DIR/.git" ]]; then
  echo "→ ml-fastvlm already present; fetch (non-fatal if offline)…"
  git -C "$REPO_DIR" fetch --depth 1 origin 2>/dev/null || true
elif [[ -d "$REPO_DIR" && -d "$REPO_DIR/llava" ]]; then
  echo "→ ml-fastvlm tree present (no .git); leaving as-is"
else
  if [[ -d "$REPO_DIR" ]]; then
    echo "→ removing incomplete $REPO_DIR"
    rm -rf "$REPO_DIR"
  fi
  echo "→ cloning $ML_FASTVLM_GIT …"
  git clone --depth 1 "$ML_FASTVLM_GIT" "$REPO_DIR"
fi

if [[ ! -d "$REPO_DIR/llava" ]]; then
  echo "ERROR: $REPO_DIR/llava missing after clone" >&2
  exit 1
fi

# --- checkpoint (0.5B stage3 only by default) ---
if [[ "$SKIP_MODEL" -eq 1 ]]; then
  echo "→ --skip-model: not downloading checkpoint"
elif [[ -d "$CKPT_DIR" && -f "$CKPT_DIR/config.json" ]]; then
  echo "→ checkpoint already present: $CKPT_DIR"
else
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    echo "ERROR: curl or wget required to download the checkpoint" >&2
    exit 1
  fi
  if ! command -v unzip >/dev/null 2>&1; then
    echo "ERROR: unzip is required to extract the checkpoint" >&2
    exit 1
  fi
  mkdir -p "$REPO_DIR/checkpoints"
  ZIP="$REPO_DIR/checkpoints/llava-fastvithd_0.5b_stage3.zip"
  echo "→ downloading 0.5B stage3 checkpoint (large; may take a while)…"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --progress-bar -o "$ZIP" "$MODEL_ZIP_URL"
  else
    wget -O "$ZIP" "$MODEL_ZIP_URL"
  fi
  echo "→ unzipping…"
  unzip -qq -o "$ZIP" -d "$REPO_DIR/checkpoints"
  rm -f "$ZIP"
  # Apple zips sometimes nest an extra folder; normalize if needed.
  if [[ ! -d "$CKPT_DIR" ]]; then
    found="$(find "$REPO_DIR/checkpoints" -maxdepth 2 -type d -name 'llava-fastvithd_0.5b_stage3' | head -1 || true)"
    if [[ -n "$found" && "$found" != "$CKPT_DIR" ]]; then
      mkdir -p "$(dirname "$CKPT_DIR")"
      mv "$found" "$CKPT_DIR"
    fi
  fi
  if [[ ! -d "$CKPT_DIR" ]]; then
    echo "ERROR: checkpoint dir missing after unzip: $CKPT_DIR" >&2
    echo "       contents of checkpoints/:" >&2
    ls -la "$REPO_DIR/checkpoints" >&2 || true
    exit 1
  fi
  echo "→ checkpoint ready: $CKPT_DIR"
fi

# --- venv + packages ---
if [[ "$FORCE_VENV" -eq 1 && -d "$VENV_DIR" ]]; then
  echo "→ --force-venv: removing $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "$PY" ]]; then
  echo "→ creating venv at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "→ upgrading pip…"
"$PY" -m pip install -U pip setuptools wheel

echo "→ installing PyTorch (macOS / MPS wheel index)…"
# Official CPU/MPS wheels for Mac; pin roughly to FastVLM's torch 2.6 line when available.
"$PY" -m pip install \
  "torch==2.6.0" "torchvision==0.21.0" \
  --index-url https://download.pytorch.org/whl/cpu \
  2>/dev/null || \
"$PY" -m pip install "torch" "torchvision"

echo "→ installing FastVLM (llava) package editable from checkout…"
# Install project deps from pyproject; may take several minutes.
"$PY" -m pip install -e "$REPO_DIR"

echo "→ installing Pillow (image load for predict)…"
"$PY" -m pip install "Pillow>=10,<12"

echo "→ smoke check (torch + MPS)…"
if ! "$PY" - <<'PY'
import sys
try:
    import torch
except ImportError as e:
    print("FAIL: torch import:", e, file=sys.stderr)
    raise SystemExit(1)
print("torch", torch.__version__)
mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
print("mps_available", mps)
if not mps:
    print(
        "WARN: MPS not available. Live FastVLM on this machine may fail. "
        "Apple Silicon + recent macOS required for mapkit-baseline v2 live.",
        file=sys.stderr,
    )
    # Still exit 0 so Intel Macs can at least finish install; runtime will fail-loud.
try:
    import PIL  # noqa: F401
    print("Pillow OK")
except ImportError as e:
    print("FAIL: Pillow:", e, file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  echo "ERROR: smoke check failed" >&2
  exit 1
fi

if [[ -d "$CKPT_DIR" ]]; then
  echo "→ checkpoint path OK: $CKPT_DIR"
else
  echo "WARN: checkpoint not present ($CKPT_DIR). Re-run without --skip-model."
fi

cat <<EOF

✓ FastVLM setup finished.

Use with the POI server / New Run:

  export POI_DATA_DIR="$DATA_ROOT"
  export POI_PREDICT_PYTHON="$PY"
  export POI_FASTVLM_REPO="$REPO_DIR"
  export POI_FASTVLM_MODEL="$CKPT_DIR"

  # then start dashboard from the git checkout:
  #   $ROOT/tools/dev_up.sh

Deterministic core only (no VLM assets needed at run time):

  export POI_VLM_MODE=off

If live still fails, read the RuntimeError from the run — it names the missing piece.
EOF
