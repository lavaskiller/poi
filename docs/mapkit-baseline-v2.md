# mapkit-baseline v2

**Scope:** the **`mapkit-baseline` version 2** algorithm shipped in the seed and dashboard  
**Entry point:** `predict(case)` in `examples/mapkit_baseline_v2.py`  
**Bundle name:** `ensemble_v2` (`tools/bundle_submission.py`)

This document does **not** cover other experimental runs (e.g. offline `selector-loop70` stitches).  
v2 answers **once** per photo + candidate list, in the order below.

---

## What problem is this solving?

MapKit gives a **list of nearby place names** sorted mostly by GPS distance.

That list is often **wrong as a photo label**:

| What GPS thinks is closest | What the photo actually is |
|----------------------------|----------------------------|
| `Banff Gondola Stop` (bus stop pin) | `Banff Gondola` (the attraction) |
| `Restroom` / `Parking` | The park or shop next door |
| A random café 8 m away | A landmark whose name is on a sign in the photo |

So v2 is **not** “always pick the closest pin.”  
It is: **use cheap rules first (OCR + name patterns); only if those rules had nothing better than “closest pin,” look at the photo with a vision model (FastVLM).**

| | |
|--|--|
| **Inputs** | `nearby_candidates`, `ocr_text`, `image` (plus case metadata) |
| **Output** | `{ "prediction": "<place name>", "reason": "..." }` — empty prediction = abstain |
| **Ground truth** | **Not used** at predict time. Scoring is done later by the harness |
| **Invented names** | **No.** Every answer must already appear on the MapKit candidate list |

Compared with v1 (weighted + unique OCR override), v2 has a **stronger rule core** and runs **FastVLM only on weak cases**.

---

## Big picture (read this first)

```text
1. MapKit candidates around the photo GPS
2. Two cheap rule engines each pick a name (no photo model yet)
3. Combine those two picks into one "core" answer
4. If the core is still basically "just the nearest pin" → ask FastVLM
   If the core already left nearest (OCR / access demote / list_fit fight) → skip VLM
5. Optional tiny structure cleanup (kiosk → supermarket, etc.)
```

**Why “cheap first”?**  
Rules are free and deterministic. FastVLM is slow, needs a GPU Mac + model weights, and can ramble or invent. So we only pay for VLM when the rules did not already find a reason to leave pure distance.

---

## End-to-end flow (same order as code)

```text
predict(case)
│
├─ no candidates? → "" / no_candidates
│
├─ [A] Core pick (rules only — no VLM)
│     access_ocr  ──┐
│     list_fit    ──┼─→ one core name + reason
│     (else weighted → nearest)
│
├─ If reason is list_fit  → done (skip VLM)
│     list_fit disagreed with access_ocr = "strong enough" signal
│
├─ [B] Else if core is WEAK → FastVLM on top-5
│     WEAK means: access_ocr empty, OR access_ocr == nearest pin
│     Strong short answer can override → reason vlm_skill
│     UNKNOWN / hedged / long text → keep core
│
└─ [C] structure_refine (list_fit helper on final name)
```

If `POI_VLM_MODE=live` (default) but FastVLM cannot run, the **whole run fails** — it does **not** quietly score as a full ensemble.  
For rules-only: `POI_VLM_MODE=off`.

---

## [A] Two rule engines (why both?)

Both engines look at the **same** candidate list + OCR.  
Neither looks at the photo image. Neither uses ground truth.

They are **two different personalities**, not two unrelated systems:

| | **access_ocr** (conservative) | **list_fit** (aggressive) |
|--|-------------------------------|---------------------------|
| **File** | `examples/selector_access_ocr.py` | `examples/selector_list_fit.py` |
| **Goal** | Cheap wins that rarely break a correct nearest | Catch harder cases in top‑10–20 |
| **OCR** | Simple: full-name / multi-token match | Stronger: long distinctive tokens, typo tolerance; **refuses** to flip rank‑1 on weak OCR |
| **Access pins** | Stop / Gift Shop / Entrance → prefer “main” place with same name core | Same idea, plus drop pure generics (restroom, parking, …) |
| **Extra** | — | Structure refine patterns (kiosk, trail stem, …) |
| **If nothing fires** | Falls back to **nearest** (rank‑1 by distance) | Falls back to nearest among remaining non-generics |

### Why not one big script?

If you only keep the aggressive rules, you **regress** easy cases (weak OCR flips a correct nearest).  
If you only keep the conservative rules, you **miss** hard cases (generic restroom wins, weak long-token OCR ignored).

Running **both** and comparing answers gives a free signal:

> “Did the aggressive engine feel the need to pick a **different** name?”

### How the two answers are merged (`_core_pick`)

| What happened | Keep | `reason` | Intuition |
|---------------|------|----------|-----------|
| list_fit and access_ocr both return names, and they **differ** | **list_fit** | `list_fit` | Aggressive path had a real reason to disagree → trust it; **do not call VLM later** |
| access_ocr has a name (and list_fit agrees, or list_fit empty) | access_ocr | `access_ocr` | Conservative path is fine; maybe call VLM if still “nearest” |
| only list_fit has a name | list_fit | `list_fit_only` | |
| both empty | weighted, else nearest | `weighted` / `nearest` | last resorts |

`weighted` = `examples/mapkit_weighted.py` (category-aware distance), used only as backup.

### Worked example — why “disagree → list_fit”

Candidates (distance order):

1. `Capilano Rd Stop`  
2. `Dog Bar`  
3. `Capilano Suspension Bridge Park`

- OCR text on the photo includes something like `CAPILANO` / `SUSPENSION`.
- **access_ocr** might still end near nearest (weak / shared road tokens).
- **list_fit** boosts the long distinctive token and picks **Capilano Suspension Bridge Park**.

→ Names **disagree** → core = list_fit, reason `list_fit` → **VLM skipped**.  
We treat that disagreement as “list_fit already did the hard work.”

### Worked example — access demote (“main place”)

Candidates:

1. `Banff Gondola Stop` (12 m)  
2. `Banff Gondola` (45 m)

Nearest-only would label the photo “Stop.”  
access_ocr / list_fit see rank‑1 as an **access label** and a nearby candidate that is the **name core** → pick `Banff Gondola`.

The algorithm **switches to another listed candidate**; it does not invent a new string.

---

## What “weak” means (the important bit)

**Nearest** = the first candidate after MapKit distance ranking = “the pin closest to the GPS.”  
Call that name `nearest`.

After the core step, look at what **access_ocr** returned (`pred_acc` in code):

| Situation | In plain English | Call FastVLM? |
|-----------|------------------|---------------|
| Core reason is already `list_fit` | Aggressive rules already overrode the cheap path | **No** |
| `pred_acc` is empty | Rules found nothing | **Yes** |
| `pred_acc` **equals** `nearest` (same name after normalize) | Rules did **not** improve on pure distance — “stuck on closest pin” | **Yes** |
| `pred_acc` **differs** from `nearest` | Rules already left nearest (OCR hit or access demote) | **No** |

So when docs say:

> “If we’re still at ‘just the nearest place,’ call the expensive model”

they mean exactly:

```text
access_ocr's answer  ==  candidates[0].name
```

**Not** “the user is near something.”  
**Not** “confidence is low” in a ML-probability sense.  
It is a **hard, deterministic check**: did the cheap rules still output pure distance rank‑1?

### Why that is a good VLM trigger

- If rules already used **OCR** or **Stop→main place**, we have a non-distance reason. Second-guessing with VLM often hurts.
- If the answer is still **only** “closest pin,” the photo is the remaining evidence that could tell Gondola vs Stop vs café — so we pay for VLM.

This check is applied to **every** case the same way. There is **no** hand-picked “hard photo list.”

---

## [B] FastVLM — only when weak

### How it is called

| | |
|--|--|
| Module | `examples/mapkit_vlm_live.py` |
| Shortlist | top **5** by distance (`VLM_K = 5`) |
| Style | `skill` (`VLM_STYLE`) |
| Model | FastVLM 0.5B (Apple Silicon / MPS) |
| Question (essence) | Which candidate number matches the photo? Or **UNKNOWN**. Prefer signs/logos and real destinations over access labels. |

### When the VLM answer is trusted (`_high_confidence_vlm_name`)

Override the core only if **all** hold:

1. Non-empty  
2. No `UNKNOWN`  
3. No hedge phrases (`not clearly`, `however`, `closest match`, `likely`, …)  
4. Length ≤ **16** characters (blocks rambling free-text)  
5. Parses to a candidate index  
6. That name **differs** from the current core prediction  

| Result | What we do |
|--------|------------|
| Passes all checks | prediction = that name, `reason = vlm_skill` |
| Fails any check | **keep core** (no forced override) |

`POI_VLM_MODE=off` skips VLM and tags `reason` with `+vlm_mode_off` (allowed).  
Missing model/image under `live` → **RuntimeError** (fail loud).

### Cache

`POI_VLM_CACHE` JSONL memoizes identical live calls.  
It is **not** a curated answer key. Delete the file to re-infer everything.

---

## [C] structure_refine

After core (+ optional VLM), run `selector_list_fit._refine_structure` on the final name.

| Pattern | Action |
|---------|--------|
| Name is an in-store kiosk (Vigo, Coinstar, …) | Prefer a supermarket/grocery candidate higher in the list |
| Name looks like trail/hike and a proper stem repeats across candidates | Prefer a Point / Museum-style representative |

If the name changes: `reason = structure_refine`.

---

## Decision cheat-sheet

```text
                    ┌─ list_fit ≠ access_ocr ──→ use list_fit ──→ STOP (no VLM)
                    │
  both engines ─────┤
                    │
                    └─ else use access_ocr (or list_fit_only / weighted / nearest)
                              │
                              ├─ that answer ≠ nearest ──→ keep it ──→ no VLM
                              │
                              └─ that answer == nearest (or empty)
                                        │
                                        └─→ FastVLM top-5
                                              ├─ short confident pick → vlm_skill
                                              └─ else keep core
```

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
