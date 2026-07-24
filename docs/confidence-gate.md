# Confidence Gate — signals & scoring

A per-case gate that decides whether to **show the algorithm's POI pick** or
**fall back to a geographic (area) result** — using only *a-priori runtime
signals* (never ground truth), so wrong picks are not surfaced to the user.

The gate is a tunable, retraining-free version of `examples/poi_confidence_policy.py`
(`decide()`) driven by `tools/simulate_confidence_policy.py`. This doc covers
**(1) which signals exist** and which may feed the gate, and **(2) how the
confidence score is defined**. The Lab/Auto simulator UI is specified separately.

Outcome is a 3-bucket partition of the cohort, scored post-hoc with GT:

- **Labeled → correct** — showed a POI and it matched GT *(maximize)*
- **Labeled → wrong** — showed a POI but it was wrong *(minimize — worst case)*
- **Near** — gate blocked the POI, showed the geographic result instead

The single operating knob (`τ`) trades these off: tighten → fewer wrong labels
**and** fewer correct labels (more Near); loosen → more coverage **and** more
leaked wrong. There is no free lunch — it is a frontier, and "optimal" needs an
explicit objective (see Auto mode).

---

## 1. Signal inventory

The one rule that defines this page's integrity: **a signal may feed the gate
only if it can be computed at runtime without knowing the answer (GT).**

### A. Gate inputs — a-priori (no GT leakage)

**Core (confidence backbone):**

| signal | meaning | type |
|---|---|---|
| `gap_m` (margin) | distance/score gap between the #1 and #2 candidate | continuous |
| `ocr_name_support` | selected candidate name ↔ on-device OCR text match strength | full / tokens / none |
| `spatial_agreement` | weighted-selected candidate == physical-nearest candidate | bool |
| candidate density | number of candidates within radius `R` (from candidate `distance_m`) | count |
| `app_poi_dist_m` | distance to the nearest (top-1) candidate | continuous |

*(`resolution.decision` = `single`/`ambiguous` is just `gap_m` thresholded; the
score uses the continuous `gap_m` directly. `app_nearby_n_wide` (fixed 250 m
count) is the fallback when per-candidate distances are unavailable.)*

**Secondary (optional / Lab):**

| signal | meaning | note |
|---|---|---|
| generic-name flag | selected name is only a generic category word (cafe, park…) | penalty |
| `category` / normalized | selected candidate category (landmark, restaurant…) | **Lab-only, default off** |
| `app_nearby_top1` | nearest candidate name | display / context only |
| VLM `prediction` + `decision` | FastVLM prediction + `vlm_override` / `vlm_agrees_nearest` | corroboration only; conditional on FastVLM |
| `caption_ondevice` | on-device OCR text | source of `ocr_name_support` |

### B. Eval-only — never a gate input (GT-derived)

Used **only** to label each case correct/wrong when computing the 3 buckets:

`gt_mapkit` · `gt_kakao` · `gt_confidence` · `poi_list_match` · `poi_match_keyword` · `app_poi_rank`

> Note on the two `app_poi_*` columns: **`app_poi_rank` is GT-derived** — it is
> the rank at which the labeled target appears in the nearby list (`MISS` if
> absent), so it encodes the answer and must not gate. **`app_poi_dist_m` is
> a-priori** — it is the nearest-candidate distance (populated even on `MISS`),
> so it is a valid gate input.

### C. Meta / identifiers & the Near payload (not gate signals)

`dataset` · `photo` · `photo_url` · `username` · `notes` · `timestamp` · `*_processed`.
**Reverse-geocode (`city` / `country` / `address`)** is the geographic result
shown when the gate blocks — the Near payload, not a gate input.

### Deferred / disabled

- **Region-reliability prior** ("areas that frequently get wrong") — *not
  implemented, small sample.* Legitimate only as a frozen held-out prior; at the
  current cohort size per-region rates are too noisy. Region error is an
  **output** of this page (reason breakdown / gallery), not a gate input.
- **`category_adj`** — Lab-only, default weight 0.

---

## 2. Confidence score

Interpretable, additive, **no learning and no GT fitting**. A specific weight
preset reproduces the current `decide()` behavior.

### Hard pre-filters (force Near, unscored)

```
· 0 candidates                 → Near   (NO_USABLE_CANDIDATES)
· spatial_agreement == false   → Near   (WEIGHTED_NEAREST_CONFLICT)   [strict toggle]
· 1 candidate & no OCR support → Near   (SINGLE_CANDIDATE_UNCORROBORATED)
```

### Score

```
s =  w_m·margin_term  +  w_o·ocr_term  +  w_s·spatial_term  +  w_d·dist_term
   − w_ρ·density_penalty  −  w_g·generic_penalty  +  w_v·vlm_term(cap)

margin_term     = clip(gap_m / M_ref, 0, 1)                  M_ref = 60 m
ocr_term        = full 1.0 / tokens 0.7 / none 0
spatial_term    = agree 1 / else 0        (faithful: hard-filter · explore: soft)
dist_term       = clip(1 − app_poi_dist_m / D_ref, 0, 1)     D_ref = 100 m
density_penalty = clip((n_R − 1) / K, 0, 1)   n_R = #candidates within R   R = 80 m, K = 4
generic_penalty = generic-only name 1 / else 0
vlm_term        = corroborates 1 / else 0,  cap 0.3   (only when FastVLM present)
```

Single-candidate cases have no `gap_m` → `margin_term = 0`; they rely on OCR/VLM.

### Gate

```
s ≥ τ  → show POI (labeled)        s < τ  → Near
slider = τ   (default 1.0)   ends: permissive/coverage ↔ strict/block
```

### Presets

| preset | weights | use |
|---|---|---|
| **faithful** (default) | `w_m=1.0, w_o=1.0, spatial=hard-filter, w_d=0, w_ρ=0, w_g=0.5, w_v=0.3 cap, τ=1.0` | reproduce current `decide()` (faithful test) |
| **explore** | + `w_d>0`, `w_ρ=0.5` (+ `R` slider), … | fold in density/distance to search a better gate |

Faithful preset reproduces `decide()`:

- `gap ≥ 60` → `margin_term=1` → POI (`LARGE_MARGIN`)
- full-name OCR → `ocr_term=1` → POI (`OCR_NAME_SUPPORT`)
- `gap 20`, no OCR → `s=0.33 < τ` → Near (`AMBIGUOUS_MARGIN` + `NO_STRONG_OCR`)
- spatial conflict → hard Near (`WEIGHTED_NEAREST_CONFLICT`)
- VLM alone (`0.15`) → cannot cross `τ` ("VLM never auto-picks alone")

### Worked example

```
gap_m=45, OCR=tokens(0.7), spatial=true, generic=no, VLM=override
s = 1.0·(45/60=0.75) + 1.0·0.7 + min(0.3·1, 0.3) = 1.75 ≥ τ(1.0) → POI
contribution → margin 0.75 / ocr 0.70 / vlm 0.30   (drives the reason panel)
```

### What the score gives the UI

- **`τ` slider** — the single "block wrong ↔ keep correct" operating point.
- **Reason contribution** — since `s` is additive, each case decomposes into
  which term crossed (or missed) `τ`; Near cases show what was lacking.
- **Lab** exposes `τ`, `R`, `M_ref`, `D_ref`, per-term weights, strict toggle
  (preset = faithful). **Auto** sweeps `τ` to the point meeting
  "wrong-labeled ≤ X%, maximize correct-labeled." Auto's `τ` is fit to the
  cohort's GT — treat as an estimate; validate on a held-out split.
