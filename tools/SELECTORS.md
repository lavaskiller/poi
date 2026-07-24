# Selector runners — naming map

Role-based names (preferred). Old exploratory names remain only in historical
run JSON under `poi-data/generated/runs/`.

**mapkit-baseline v2 algorithm (predict pipeline):**
[`docs/mapkit-baseline-v2.md`](../docs/mapkit-baseline-v2.md).

## Seed baselines (default `pack_seed_bundle.py`)

Frozen run JSON under `poi-data-seed/generated/runs/`. Metrics below match the
**unique-149** seed cohort currently packed in that bundle (exact / canonical).

| Run | Role | Seed archive (149 eligible) | Code |
|---|---|---|---|
| `baseline-nearest` v1 | MapKit distance rank-1 | **33%** exact (49/149) · **50%** canonical (74/149) | `examples/baseline_nearest.py` |
| `mapkit-baseline` v1 | Weighted + unique OCR override | **34%** exact (50/149) · **50%** canonical (74/149) | `examples/mapkit_ocr_override.py` (+ weighted/policy) |
| `mapkit-baseline` v2 | Live list_fit + FastVLM skill on weak cases | **44%** exact (66/149) · **65%** canonical (97/149) | `examples/mapkit_baseline_v2.py` + `mapkit_vlm_live.py` (bundle: `ensemble_v2`) |

Rebuild: `python3 tools/pack_seed_bundle.py --clean` (curates these three automatically).

A larger private eval (e.g. 166 eligible) can score differently; do not mix those
percentages with the seed table. Live v2 re-runs on another machine may also
differ from the archived seed JSON — the archive is not a live measurement.

## Full selector map

Paths under `tools/` are abbreviated; full path is `tools/<file>` unless noted.

| File | Role | Default run name |
|---|---|---|
| `examples/baseline_nearest.py` | Distance rank-1 | `baseline-nearest` |
| `examples/mapkit_weighted.py` | Category-weighted distance | (UI / weighted) |
| `examples/mapkit_ocr_override.py` | Weighted + unique OCR name override | `mapkit-baseline` v1 |
| `examples/mapkit_baseline_v2.py` | Live ensemble: list_fit vs access_ocr; FastVLM skill@5 when weak | `mapkit-baseline` v2 |
| `examples/mapkit_vlm_live.py` | Bundleable FastVLM runtime (skill / place_match) | used by v2 |
| `examples/selector_access_ocr.py` | Access-point demote + strong OCR | `selector-access-ocr` |
| `examples/selector_list_fit.py` | Stronger OCR + generic demote + structure refine (K=10–20) | `selector-list-fit` / `selector-list-fit-k20` |
| `examples/poi_confidence_policy.py` | AUTO_PICK / SHOW_PICKER / NONE tiers (not a scorer) | used by `simulate_confidence_policy.py` |
| `tools/stitch_loop70_ensemble.py` | Historical offline stitch (cache residual) | `selector-loop70` provenance only |
| `tools/run_selector_ocr_override.py` | Weighted + unique OCR name override | `selector-ocr-override` |
| `tools/run_vlm_topk_rerank.py` | FastVLM Top-K image rerank | `vlm-topk-{style}-k{K}` |
| `tools/run_selector_photo_match.py` | access_ocr + photo–place VLM cascade | `selector-photo-match` |
| `tools/stitch_loop60_ensemble.py` | Stitch list_fit + cascade (no VLM re-run) | `selector-loop60-pass` |
| `tools/run_selector_bloggo_vlm_verify.py` | Weighted default; VLM only when ambiguous | `selector-bloggo-vlm-verify` |
| `tools/run_selector_bloggo_vlm_conditioned.py` | Weighted + conditioned VLM | `selector-bloggo-vlm-conditioned` |
| `tools/run_selector_bloggo_vlm_gate.py` | Weighted + semantic gate | `selector-bloggo-vlm-gate` |
| `tools/run_selector_ocr_vlm_specialty.py` | OCR then VLM specialty verify | `selector-ocr-vlm-specialty` |
| `tools/run_selector_ocr_vlm_specialty_loose.py` | Same, looser YES parser | `selector-ocr-vlm-specialty-loose` |
| `tools/simulate_confidence_policy.py` | Offline confidence-policy simulation on a labeled cohort | report JSON only |

## `run_vlm_topk_rerank.py` prompt styles

| Style | Behavior |
|---|---|
| `baseline` | Short choose-or-UNKNOWN (legacy) |
| `skill` | Priority skill guide; UNKNOWN still allowed → nearest fallback |
| `skill_force` | Always pick 1..K (PWE-13 experiments only) |
| `place_match` | Photo–place fit, not distance (PWE-13 framing) |

```bash
# Active snapshot, skill prompt, top-5
python3 tools/run_vlm_topk_rerank.py --prompt-style skill --candidate-limit 5

# Force choice on top-5 (no UNKNOWN)
python3 tools/run_vlm_topk_rerank.py --prompt-style skill_force --candidate-limit 5

# Live mapkit-baseline v2 (UI harness or CLI) — uses FastVLM venv automatically
poi-data/tools/fastvlm-venv/bin/python tools/run_algorithm.py \
  --name mapkit-baseline --script <(python3 tools/bundle_submission.py ensemble_v2) \
  --params image,nearby_candidates,ocr_text

# Deterministic core only (no VLM; below published seed)
POI_VLM_MODE=off python3 tools/run_algorithm.py …
```

### Live v2 environment

| Variable | Default | Role |
|---|---|---|
| `POI_PREDICT_PYTHON` | auto: `poi-data/tools/fastvlm-venv/bin/python` if present | Interpreter for `predict()` subprocess |
| `POI_VLM_MODE` | `live` | `live` \| `off` \| `cache_first` |
| `POI_VLM_CACHE` | `…/mapkit_baseline_v2_live_cache.jsonl` | Memo of live calls (delete to re-infer) |
| `POI_FASTVLM_REPO` / `POI_FASTVLM_MODEL` | under `poi-data/tools/ml-fastvlm/…` | Model paths |
| `POI_DATA_DIR` | auto | Photo + model root (harness injects if unset) |

**Reproducibility contract (v2):** every eligible case uses the same rule —
list_fit if it disagrees with access_ocr, else live FastVLM skill@K5 when
access≈nearest. Override only on short, non-hedged, unambiguous answers
(long free-text / “however closest is…” refused). No curated residual photo
list and no published prediction JSONL in the decision path. Write-through
cache is memoization only. Seed JSON **44% / 65%** (unique-149) is a historical
archive; live re-run scores are measured separately. See
[`docs/mapkit-baseline-v2.md`](../docs/mapkit-baseline-v2.md).

**Fail-loud (default `POI_VLM_MODE=live`):** if FastVLM is not provisioned
(venv / torch+MPS / ml-fastvlm / checkpoint), the run **aborts** instead of
quietly scoring OCR-only under the ensemble name. Only
`POI_VLM_MODE=off` is allowed to run the deterministic core without VLM.

### FastVLM on another Mac (automated setup)

Git has our glue code only. **Live** mapkit-baseline v2 also needs Apple’s
FastVLM checkout, a 0.5B checkpoint, and a torch/MPS venv under the data root.

**One-shot (recommended on Apple Silicon macOS):**

```bash
# After git clone + seed/data under poi-data/ (or POI_DATA_DIR):
./tools/setup_fastvlm.sh

export POI_DATA_DIR="$(pwd)/poi-data"   # if not already set
export POI_PREDICT_PYTHON="$POI_DATA_DIR/tools/fastvlm-venv/bin/python"
# optional: POI_FASTVLM_REPO / POI_FASTVLM_MODEL (script prints defaults)

./tools/dev_up.sh
```

What the script does:

1. `git clone` [apple/ml-fastvlm](https://github.com/apple/ml-fastvlm) → `poi-data/tools/ml-fastvlm`
2. Download **0.5B stage3** from Apple CDN → `…/checkpoints/llava-fastvithd_0.5b_stage3/`
3. Create `poi-data/tools/fastvlm-venv` and `pip install` torch + editable llava
4. Smoke-check `import torch` / MPS

Flags: `--skip-model` (no download), `--force-venv` (recreate venv).  
Not a 10-second install (network + multi‑GB). Linux: use `POI_VLM_MODE=off` instead.

**Manual copy** (if you already have an internal bundle): place the same three
paths under `$POI_DATA_DIR/tools/` and set `POI_PREDICT_PYTHON` as above.

**Deterministic core only** (no VLM assets):

```bash
export POI_VLM_MODE=off
```

`GET /api/deps-status` reports FastVLM venv/repo/checkpoint as **warnings**
(server still boots). Live ensemble runs fail-loud inside `mapkit_baseline_v2`
if the env is missing.

## Historical name map

Old paths (no longer in tree) → current paths:

| Old file | New file |
|---|---|
| `tools/run_fastvlm_baseline.py` | `tools/run_vlm_topk_rerank.py` |
| `tools/run_bloggo_ocr_reranker.py` | `tools/run_selector_ocr_override.py` |
| `tools/run_fastvlm_bloggo_hybrid.py` | `tools/run_selector_bloggo_vlm_verify.py` |
| `tools/run_fastvlm_bloggo_conditioned_v2.py` | `tools/run_selector_bloggo_vlm_conditioned.py` |
| `tools/run_fastvlm_bloggo_semantic_gate_v3.py` | `tools/run_selector_bloggo_vlm_gate.py` |
| `tools/run_bloggo_ocr_fastvlm_semantic_v4.py` | `tools/run_selector_ocr_vlm_specialty.py` |
| `tools/run_bloggo_ocr_fastvlm_semantic_v5_permissive.py` | `tools/run_selector_ocr_vlm_specialty_loose.py` |
| `examples/pwe13_access_ocr_selector.py` | `examples/selector_access_ocr.py` |
