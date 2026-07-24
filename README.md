# POI Eval

Internal tool for **evaluating POI (point-of-interest) prediction algorithms**.

- **Backend:** `server.py` + `tools/` → HTTP API on port **8420**
- **Frontend:** `web/` (React + Vite) → UI on port **5173** (proxies `/api` → backend)

This README is the **onboarding path** for a new machine. Deeper notes:
[`docs/onboarding.md`](docs/onboarding.md) · algorithm details: [`tools/SELECTORS.md`](tools/SELECTORS.md).

---

## What you get after setup

| Capability | After git + setup + seed | + FastVLM (optional) |
|------------|--------------------------|----------------------|
| Open dashboard, browse cases, frozen baseline scores | ✅ | ✅ |
| New Run / re-run **nearest**, OCR core, `POI_VLM_MODE=off` | ✅ | ✅ |
| Re-run **mapkit-baseline v2 live** (FastVLM ensemble) | ❌ fails loud if missing | ✅ |
| Live MapKit / Vision OCR *enrichment jobs* | macOS + Xcode CLT | same |

**Git does not include evaluation photos, run JSON, or FastVLM weights.** Those are private data + optional ML assets.

---

## Quick start (new Mac)

### 0. Prerequisites

| Need | Notes |
|------|--------|
| **Python 3.9+** | `python3 --version` |
| **Node.js 18+** and npm | frontend |
| **macOS + Xcode CLT** (recommended) | MapKit / Vision probes: `xcode-select --install` |
| **Git** | clone |

### 1. Clone and install dashboard deps

```bash
git clone git@github.com:lavaskiller/poi.git
cd poi

chmod +x tools/dev_up.sh tools/setup.sh tools/setup_fastvlm.sh
./tools/setup.sh                 # pip + check_deps + npm install
```

Or one launcher later: `./tools/dev_up.sh` (runs setup then starts both servers).

**Clone path is free** (`~/src/poi`, USB, …). Always start backend and Vite from the **same** checkout (mixing two clones causes API 404).

### 2. Load evaluation data (required)

Data lives under **`poi-data/`** (gitignored). Ways to get it:

**A. Seed zip (recommended for a clean laptop)**

1. Get `poi-seed-unique149-*.zip` (internal share / Desktop seed).
2. Start the app (`./tools/dev_up.sh`), open **Onboarding** in the UI, upload the zip  
   **or** unpack so that `poi-data/eval_set_reconciled.csv` exists:

```bash
mkdir -p poi-data
unzip -o /path/to/poi-seed-unique149-*.zip -d poi-data
# expect: poi-data/eval_set_reconciled.csv, photos/, generated/, …
```

**B. Full private `poi-data/` tree** from Drive (same layout, more history).

Optional:

```bash
export POI_DATA_DIR=/absolute/path/to/poi-data   # if data is not ./poi-data
```

Seed includes three frozen baselines (unique-149 cohort): `baseline-nearest`, `mapkit-baseline` v1/v2.  
v1/v2 **scripts are self-contained** (re-run without repo `examples/` on `PYTHONPATH`).

### 3. Start the app

```bash
./tools/dev_up.sh
```

- UI: http://127.0.0.1:5173  
- API: http://127.0.0.1:8420  

Ctrl-C stops both. Useful flags: `--backend-only`, `--skip-install`, `--setup-only`.

### 4. Optional — live FastVLM (mapkit-baseline v2 ensemble)

Default re-run mode is **`POI_VLM_MODE=live`**: if FastVLM is missing, the run **fails** (no silent OCR-only “ensemble” score).

**Install FastVLM assets (Apple Silicon macOS, network, multi‑GB):**

```bash
./tools/setup_fastvlm.sh
# clones apple/ml-fastvlm, downloads 0.5B stage3, creates poi-data/tools/fastvlm-venv

export POI_DATA_DIR="$(pwd)/poi-data"
export POI_PREDICT_PYTHON="$POI_DATA_DIR/tools/fastvlm-venv/bin/python"
# then restart: ./tools/dev_up.sh --skip-install
```

**Skip VLM; deterministic core only** (honest OCR / access / weighted path):

```bash
export POI_VLM_MODE=off
```

Details: [`tools/SELECTORS.md`](tools/SELECTORS.md) · script: [`tools/setup_fastvlm.sh`](tools/setup_fastvlm.sh).

---

## Day-to-day commands

```bash
./tools/dev_up.sh                 # setup (if needed) + backend + frontend
./tools/dev_up.sh --skip-install  # fast restart
./tools/setup.sh --backend-only   # API machine without Node
./tools/setup_fastvlm.sh          # optional FastVLM provisioning
python3 -m unittest discover -s tests -v
```

Manual two-terminal mode:

```bash
python3 -m pip install -r requirements.txt
python3 tools/check_deps.py
python3 server.py
# other terminal:
npm --prefix web install && npm --prefix web run dev
```

---

## Layout

```
web/              React UI
server.py         HTTP API
tools/            setup, scoring, jobs, setup_fastvlm.sh, SELECTORS.md
examples/         algorithm sources (bundle for UI submit: tools/bundle_submission.py)
tests/
poi-data/         data root (gitignored) — CSV, photos, runs, optional tools/fastvlm-*
poi-data-seed/    optional local seed tree (gitignored)
docs/onboarding.md
```

---

## Environment variables (common)

| Variable | Default | Purpose |
|----------|---------|---------|
| `POI_DATA_DIR` | `./poi-data` if present | Evaluation data root |
| `POI_BIND` / `POI_PORT` | `127.0.0.1` / `8420` | Server listen |
| `POI_PREDICT_PYTHON` | auto: `fastvlm-venv` if present | Interpreter for `predict()` |
| `POI_VLM_MODE` | `live` | `live` (fail if no FastVLM) · `off` (deterministic core) · `cache_first` |
| `POI_VLM_CACHE` | under `generated/` | Live VLM memo cache path |
| `POI_FASTVLM_REPO` / `POI_FASTVLM_MODEL` | under `$POI_DATA_DIR/tools/…` | Override FastVLM paths |
| `POI_API_TOKEN` | empty | If set, mutating API needs `X-POI-Token` |
| `POI_SKIP_DEPS_CHECK` | empty | `1` skips boot dep gate (not recommended) |
| `POI_SKIP_GIT_SYNC_CHECK` | empty | `1` skips “behind origin” UI block |

UI boot: `/api/deps-status` then `/api/git-status`. Hard dep failures block the app; FastVLM gaps are **warnings** (live v2 still fails at run time until provisioned or `POI_VLM_MODE=off`).

---

## Algorithm baselines (seed)

| Name | What it is | Re-run needs |
|------|------------|--------------|
| `baseline-nearest` | MapKit distance rank-1 | seed data only |
| `mapkit-baseline` v1 | weighted + unique OCR override | seed data + OCR column |
| `mapkit-baseline` v2 | list_fit + live FastVLM on weak cases | **FastVLM** or `POI_VLM_MODE=off` |

Bundle for UI paste/submit:

```bash
python3 tools/bundle_submission.py ensemble_v2 -o /tmp/mapkit_v2.py
python3 tools/bundle_submission.py ocr_override -o /tmp/mapkit_v1.py
```

Frozen seed **metrics** are archived predictions in run JSON; a live re-run may score differently.

---

## Backend API (short)

`/api/health` · `/api/deps-status` · `/api/git-status` · `/api/overview` · `/api/datasets` ·  
`/api/runs` · `/api/run` (POST, async live Results) · `/api/matchrate` · `/api/jobs` ·  
`/api/ingest` · `/api/validate-upload-package` · `/api/gt/reconcile` · `/api/mapkit/probe` · …

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## Status

Design-system UI wired to the real backend. Seed onboarding, live case-by-case
runs, fail-loud import/VLM policies, and optional FastVLM setup are in tree.
Legacy vanilla UI: branch **`legacy-mvp`**.
