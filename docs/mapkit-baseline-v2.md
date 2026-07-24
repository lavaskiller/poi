# mapkit-baseline v2

**Scope:** the **`mapkit-baseline` version 2** algorithm shipped in the seed and dashboard  
**Entry point:** `predict(case)` in `examples/mapkit_baseline_v2.py`  
**Bundle name:** `ensemble_v2` (`tools/bundle_submission.py`)

This document does **not** cover other experimental runs (e.g. offline `selector-loop70` stitches).  
v2 answers **once** per photo + candidate list, in the order below.

---

## What it does

Given MapKit’s **nearby place candidates** around the photo GPS, pick **one place name** that best matches what was photographed.

| | |
|--|--|
| **Inputs** | `nearby_candidates`, `ocr_text`, `image` (plus case metadata) |
| **Output** | `{ "prediction": "<place name>", "reason": "..." }` — empty string prediction = abstain |
| **Ground truth** | **Not used.** Scoring is done later by the harness |
| **Names outside the list** | Not invented. Even VLM output is mapped only to spellings already on the candidate list |

Compared with v1 (weighted + unique OCR override), v2 has a **stronger OCR/list core** and attaches **FastVLM only on weak cases**.

---

## End-to-end flow

Same order as `predict` in code.

```text
predict(case)
│
├─ no candidates? → prediction "", reason no_candidates
│
├─ [A] deterministic core (_core_pick)
│     run list_fit and access_ocr; keep one
│     (if both fail: weighted → nearest)
│
├─ reason == list_fit ?  → return that name immediately  (no VLM)
│
├─ [B] if access_ocr is “weak”: FastVLM skill @ top-5
│     weak = no access_ocr result, or it equals distance rank-1 (nearest)
│     only short, decisive answers override the core (vlm_skill)
│     UNKNOWN / ambiguous / rambling → keep core
│
└─ [C] structure_refine (list_fit helper)
      if the name changes → reason = structure_refine
```

If `POI_VLM_MODE=live` (default) but FastVLM cannot run, the run **fails entirely** — it does **not** quietly score OCR-only under the ensemble name.  
For an intentional core-only run, set `POI_VLM_MODE=off`.

---

## [A] Deterministic core `_core_pick`

Pick a name from candidates + OCR only (no VLM).

### Two rule engines

| Name | File | Behavior |
|------|------|----------|
| **access_ocr** | `examples/selector_access_ocr.py` | (1) If OCR strongly matches a candidate name, pick it. (2) Else if rank-1 looks like Stop / Gift Shop / Entrance / … and a nearby non-access candidate shares the name core, prefer that **main place**. (3) Else nearest. |
| **list_fit** | `examples/selector_list_fit.py` | Stronger OCR scoring (boost long distinctive tokens; do not flip rank-1 on weak OCR), drop pure generics (restroom, parking, …), demote access labels, plus structure refine. |

**Why run both.**  
If list_fit returns a **different** name from access_ocr, treat list_fit as strong enough to disagree with the cheaper path and **take list_fit**.  
If they agree (or only one fires), keep that side and later decide whether VLM is needed.

### Core selection table (`_core_pick`)

| Condition | prediction | reason |
|-----------|------------|--------|
| list_fit present and **≠** access_ocr | list_fit | `list_fit` |
| else access_ocr present | access_ocr | `access_ocr` |
| else list_fit only | list_fit | `list_fit_only` |
| else weighted succeeds | weighted | `weighted` |
| else | candidates[0] name | `nearest` |

`weighted` is `examples/mapkit_weighted.py` — category-aware effective distance, used as backup.

### What the “main place” access rule means

Maps often place a **bus stop, gift shop, or donation box** pin slightly closer than the destination pin.  
Nearest-only then returns the access label, not the place people mean.

Examples (both names already on the candidate list):

- Rank-1 `Banff Gondola Stop` → pick `Banff Gondola`
- Rank-1 `Goulding's Gift Shop` → pick `Goulding's Lodge` when the name stem matches and the main POI is nearby

The algorithm does **not** invent a new string; it switches to another **listed** candidate.

---

## [B] FastVLM — only when weak

### When it runs (`_should_call_vlm`)

If `reason == list_fit`, **stop** — no VLM.

Otherwise look at the access_ocr result (`pred_acc`):

| pred_acc | Call VLM? |
|----------|-----------|
| empty | yes |
| equals distance rank-1 (**nearest**), after normalize | yes |
| differs from nearest | no (rules already beat pure distance) |

So the photo model runs only when the cheap path is still “stuck on nearest.”  
This is **not** a curated residual photo list — the same rule applies to every case.

### How it is called

| | |
|--|--|
| Module | `examples/mapkit_vlm_live.py` |
| Shortlist | top **5** by distance (`VLM_K = 5`) |
| Style | `skill` (`VLM_STYLE`) |
| Model | FastVLM 0.5B (Apple, MPS) |

Skill prompt (essence): answer with a single candidate number or **UNKNOWN**; no explanation. Prefer signage/logo → distinctive landmark → destination over access labels. Do not pick a shop just because food is visible.

### When the answer is trusted (`_high_confidence_vlm_name`)

Override the core only if the model raw string passes **all** of:

1. Non-empty  
2. No `UNKNOWN`  
3. No hedge phrases (`not clearly`, `however`, `closest match`, `likely`, …)  
4. Length ≤ **16** characters (blocks rambling free-text)  
5. `parse_selection` resolves a candidate index  
6. That name **differs** from the current core prediction  

On success: `reason = vlm_skill`.  
On failure: keep the core name (no forced override).

`POI_VLM_MODE=off` skips VLM and appends `+vlm_mode_off` to `reason` — that is the **allowed** degradation. Missing image / model errors under live mode raise **RuntimeError**.

### Cache

`POI_VLM_CACHE` JSONL is **memoization** of identical live calls (key includes model, prompt, candidates, photo).  
It is **not** a hand-curated answer key for hard cases. Delete the file to re-infer everything.

---

## [C] structure_refine

After the steps above, apply `selector_list_fit._refine_structure` to the final name.  
(If the core already returned via list_fit, list_fit may have refined once already; this can run again.)

| Pattern | Action |
|---------|--------|
| Name is an in-store kiosk (Vigo, Coinstar, …) | Prefer a supermarket/grocery candidate higher in the list |
| Name looks like trail/hike and a proper stem repeats across candidates | Prefer a Point / Museum-style representative |

If the name changes: `reason = structure_refine`.

---

## `reason` values

| reason | Meaning |
|--------|---------|
| `no_candidates` | Empty MapKit list → empty prediction |
| `list_fit` | list_fit ≠ access_ocr; taken. **VLM skipped** |
| `access_ocr` | access_ocr kept (VLM did not override, or case was not weak) |
| `list_fit_only` | access_ocr empty; list_fit only |
| `weighted` / `nearest` | Fallbacks after rules fail |
| `…+vlm_mode_off` | Core + intentional no VLM |
| `vlm_skill` | Short FastVLM answer overrode the core |
| `structure_refine` | Final structural rename |

---

## Modules

The `ensemble_v2` bundle concatenates:

| Module | Role |
|--------|------|
| `mapkit_baseline_v2` | Orchestration (`predict`) |
| `selector_list_fit` | list_fit + structure_refine |
| `selector_access_ocr` | access_ocr |
| `mapkit_weighted` | weighted backup |
| `mapkit_vlm_live` | FastVLM infer, prompts, cache |

The harness does not put `examples/` on `PYTHONPATH`; submissions and seed re-runs must use the bundle.

---

## How to run

```bash
# FastVLM (Apple Silicon) — required for live mode
./tools/setup_fastvlm.sh

export POI_DATA_DIR="$(pwd)/poi-data"
export POI_PREDICT_PYTHON="$POI_DATA_DIR/tools/fastvlm-venv/bin/python"

# Live ensemble (default POI_VLM_MODE=live)
$POI_PREDICT_PYTHON tools/run_algorithm.py \
  --name mapkit-baseline \
  --script <(python3 tools/bundle_submission.py ensemble_v2) \
  --params image,nearby_candidates,ocr_text
```

| Env var | Default | Meaning |
|---------|---------|---------|
| `POI_VLM_MODE` | `live` | `live` · `off` · `cache_first` |
| `POI_VLM_CACHE` | live cache JSONL under data | Call memoization |
| `POI_FASTVLM_REPO` / `POI_FASTVLM_MODEL` | under `poi-data/tools/ml-fastvlm`… | Model paths |
| `POI_PREDICT_PYTHON` | auto-detect fastvlm-venv | Predict subprocess |

Dashboard **New run** with mapkit-baseline v2 / ensemble bundle uses the same code path.

---

## v1 vs v2

| | mapkit-baseline **v1** | mapkit-baseline **v2** |
|--|------------------------|------------------------|
| Core | weighted + unique OCR override | **list_fit vs access_ocr** core |
| Vision | none | **FastVLM skill@5** only when weak; short answers only |
| Failure | n/a | live + missing VLM → **run fails** (no fake ensemble score) |

Seed-archived v2 metrics are historical; live re-runs on another machine can differ.  
Fair comparisons use the **same candidate snapshot + same weights + live re-run**.

---

## Out of scope for this doc

- Offline `selector-loop70` stitching / residual cache composition  
- Product confidence gate / geographic fallback policy  
- Kakao-only pipelines  

Those are outside the v2 `predict` contract.
