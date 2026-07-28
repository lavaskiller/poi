# Reproducible runtime

A run is only as trustworthy as the environment that produced it. This repo
splits the runtime into three deliberately separate tiers and pins each one so a
result can be reproduced and a regression can be attributed to *code*, not to a
silently-drifted dependency. The pins are recorded — by SHA-256 — in every run
manifest via `tools/run_manifest.py`, so provenance is attached to the run, not
kept in someone's head.

## The three tiers

| Tier | What runs there | Pin | In git? |
|------|-----------------|-----|---------|
| **Eval backend** | `server.py` + stdlib `tools/` | `requirements.lock` (Pillow only) | yes |
| **FastVLM selector** | `run_selector_*_vlm*.py`, `run_fastvlm_baseline.py` | `tools/fastvlm.lock.json` (commit + torch + checkpoint SHA-256) | yes (the pin; the venv is host-local) |
| **Swift / MapKit** | macOS geocode / nearby helpers | system Xcode toolchain (`tools/check_deps.py`) | n/a (host OS) |

Keeping these apart is a feature, not an accident:

- The backend imports **without torch, transformers, numpy, or even Pillow at
  module load** — verified by `tools/check_import_isolation.py` and enforced in
  CI. That is what lets the backend run in a tiny deterministic container and
  lets the 142-test suite run with zero third-party wheels.
- FastVLM is heavy, platform-specific (Apple Silicon / MPS), and evolves on its
  own cadence. It lives in a separate venv under `poi-data/tools/` and is
  invoked as a subprocess, so a torch upgrade can never perturb a rules-only
  run.

## Backend: `requirements.lock`

`requirements.txt` states intent (`Pillow>=10.0.0,<12`); `requirements.lock`
states the exact resolved build the container installs and the manifest hashes:

```bash
# Regenerate after changing requirements.txt:
python3 -m pip install pip-tools
pip-compile --output-file=requirements.lock requirements.txt
# Hard supply-chain pin (recommended for release images):
pip-compile --generate-hashes --output-file=requirements.lock requirements.txt
```

CI (`tests/test_reproducible_runtime.py`) asserts every top-level package named
in `requirements.txt` is pinned with `==` in the lock, so the two can't drift
apart unnoticed.

## FastVLM: `tools/fastvlm.lock.json`

```json
{
  "_schema": "fastvlm-pin/v1",
  "fastvlm_commit": null,
  "torch": null,
  "checkpoint": null,
  "checkpoint_sha256": null
}
```

Fill these from the provisioned venv (see `tools/setup_fastvlm.sh`). `null`
values are recorded verbatim and never fail a run — the pin degrades to
"unpinned, and honestly labelled so" rather than blocking. When
`POI_FASTVLM_CHECKPOINT` points at a checkpoint on disk,
`run_manifest.model_provenance` hashes it and records
`checkpoint_sha256_actual`; if the pin's `checkpoint_sha256` is set and differs,
the mismatch is visible in the manifest — a swapped model can't hide.

## Container

`Dockerfile` builds the **backend tier only**:

```bash
docker build -t poi-eval .
docker run --rm -p 8420:8420 \
    -e POI_API_TOKEN="$(openssl rand -hex 16)" \
    -e POI_BIND=0.0.0.0 \
    -v "$PWD/poi-data:/app/poi-data" \
    poi-eval
```

Notes:

- The base image is tag-pinned (`python:3.11.9-slim-bookworm`); swap in the
  `@sha256:` digest for a hardened release build.
- Datasets and run snapshots are **mounted, never baked in** (`.dockerignore`
  excludes `poi-data`), so the image carries no private user data.
- Binding `0.0.0.0` is treated as non-local by `server.py`, which therefore
  **requires `POI_API_TOKEN`** and fails loud without it.

## What the manifest captures

`tools/run_manifest.py` records, per run: `requirements_lock_sha256`,
`requirements_txt_sha256`, the FastVLM `model_provenance` block, the interpreter
version, and the input/evaluation-set digests. To reproduce a historical run,
check out the recorded code hash, restore the pinned deps, and the environment
half of the run is accounted for.
