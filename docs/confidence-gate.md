# Confidence Gate — signals & scoring

A per-case gate that decides whether to **show the algorithm's POI pick** or
**fall back to a geographic (area) result** — using only *a-priori runtime
signals* (never ground truth), so wrong picks are not surfaced to the user.

The gate is a tunable, retraining-free version of `examples/poi_confidence_policy.py`
(`decide()`) driven by `tools/simulate_confidence_policy.py`. This doc covers
**(1) which signals exist** and which may feed the gate, and **(2) how the
confidence score is defined**.

### Where this sits in the app

| Step | Page | Role |
|---|---|---|
| 1 | Datasets / Reconcile | Cohort + GT |
| 2 | New run → Results / Compare | **Which selector** picks the POI (accuracy) |
| 3 | **Confidence gate** | Given one base pick, **show POI vs Near** (product safety) |

The gate judges a **pick** (show POI vs Near), not which selector to train.

| Base pick | Source | Use |
|---|---|---|
| **Policy** | Live `mapkit_weighted` + `poi_confidence_policy.decide()` | Match product AUTO policy; AUTO ≡ labeled diagnostic |
| **Results run** | Saved run JSON `prediction` per case | Product path: pick a Result, then tune the gate on those picks |

For a Results run, the selector is **not** re-executed. Gate signals (OCR on the
run prediction, spatial vs physical nearest, list margin when the pick is
weighted top, density) are recomputed against MapKit candidates.

### UI modes (Lab / Auto / Learn)

| Mode | Use when | What moves |
|---|---|---|
| **Lab** | Understanding the frontier; matching `decide()` via **faithful** preset | **faithful:** τ only (hard gates + weights locked). **explore:** R, M_ref, D_ref, hard gates, weights |
| **Auto** | One-knob operating point on the **full** cohort | τ only (wrong-budget → max coverage) |
| **Learn** | Searching margin/dist/spatial/VLM/density/scene weights with a **held-out** split | weights (+ fitted τ); Apply → Lab |

**Faithful is not “score alone.”** `decide()` equivalence needs hard gates
(`spatialStrict` + `requireDecisiveEvidence`). The UI locks those under the
faithful preset and shows a live **AUTO ≡ labeled** diagnostic (case-level
agreement with `action === AUTO_PICK` from the policy simulator). Turning hard
gates or weights off switches the preset to **explore**.

Eval toggle **exact** vs **relations** only changes how “correct” is counted
after the fact — never a gate input.

**Saving an operating point.** Lab/Auto expose **＋ Save current**; Learn exposes
**💾 Save best**. A snapshot records the tuned τ / weights / hard gates, the base
(policy or a Results run), the eval mode + budget, the headline KPIs, and the
per-case labeled/Near decisions — so it is both a reproducible operating point
and an offline audit dump. Snapshots persist server-side under
`generated/confidence-snapshots/` (named — re-saving a name updates in place) via
`GET/POST /api/confidence-snapshot[s]`; the saved-points bar lists them and loads
one back into Lab. Nothing is lost on refresh.

**k-fold cross-validation (Learn).** The live search uses one held-out split,
which a lucky partition can flatter. **Cross-validate** runs *k*-fold CV of the
learned weight direction — τ is refit per fold, val is scored per fold — and
reports val coverage / wrong-leak as **mean ± std** plus how many folds were
feasible at the budget. Wide std or `< k` feasible folds means the weights do not
generalize; trust the mean, not the best split. Saving from Learn embeds this CV
summary in the snapshot KPIs.

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
| `scene_agreement` | photo scene (`VNClassifyImageRequest`) ↔ pick category/name agreement, [0,1] | corroboration only, cap `w_cat` (explore 0.3); cannot open the gate alone |
| `caption_ondevice` | on-device OCR text | source of `ocr_name_support` |

**Photo scene (`scene_agreement`).** An on-device Vision classifier
(`tools/swift/scene_classify.swift` → `scene_labels.tsv`) reads top-k scene
labels from the pixels (e.g. `outdoor 0.96 · food 0.8 · structure`). It is
a-priori (no GT), so it is a valid gate input. `tools/scene_agreement.py` maps
the strongest label to the selected pick's MapKit category / name tokens →
continuous `[0,1]`. It corroborates like the VLM term (capped at `w_cat`,
default 0 in faithful) and is a **searched** signal in Learn. On the current
160-case cohort it is the **strongest continuous signal** (AUC ≈ 0.65, above
`margin` 0.61 and `dist` 0.60); when agreement ≥ 0.35 fires (31 cases) precision
rises 0.36 → 0.71. A confident scene that maps to a *different* family than the
pick is exposed as `scene_conflict` (soft diagnostic, not a hard pre-filter).

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
   − w_ρ·density_penalty  −  w_g·generic_penalty  +  w_v·vlm_term(cap)  +  w_cat·scene_term(cap)
   +  w_catprior·category_prior_term

margin_term     = clip(gap_m / M_ref, 0, 1)                  M_ref = 60 m
ocr_term        = full 1.0 / tokens 0.7 / none 0
spatial_term    = agree 1 / else 0        (faithful: hard-filter · explore: soft)
dist_term       = clip(1 − app_poi_dist_m / D_ref, 0, 1)     D_ref = 100 m
density_penalty = clip((n_R − 1) / K, 0, 1)   n_R = #candidates within R   R = 80 m, K = 4
generic_penalty = generic-only name 1 / else 0
vlm_term        = corroborates 1 / else 0,  cap 0.3   (only when FastVLM present)
scene_term      = scene_agreement [0,1],    cap w_cat (faithful 0 · explore 0.3)
category_prior_term = clip(shrunk_rate(pick_category) − global_rate, −1, 1)   (signed; explore only)
```

**Per-category prior (`category_prior_term`).** A *signed* prior learned from
TRAIN GT: below-average categories subtract confidence, above-average add — the
"많이 틀린 카테고리는 나쁘게, 많이 맞춘 카테고리는 좋게" behavior. The pick's
category is a-priori (known at runtime without GT); only the *rates* are a
learned parameter, so this is a train-time prior, **not** a runtime GT input.

- **Empirical-Bayes shrinkage.** Each category's hit-rate is pulled toward the
  global rate with pseudo-count `α`: `shrunk = (hits + α·global)/(n + α)`, so a
  2-sample category can't swing to an extreme. `α` is the `α shrink` slider.
- **Min support.** Categories with fewer than `min support` train cases get **no
  adjustment** (regress fully to global) — a hard df floor on top of shrinkage.
- **Fit discipline.** The Lab table/score fit on the **full cohort** (in-sample,
  optimistic). The honest number is **Cross-validate ×2**: 5-fold CV that refits
  the prior on each fold's train split and scores the held-out fold — no case is
  ever scored against a prior built from itself. It reports prior-off vs
  prior-on val coverage ± std, so a lucky split can't pass for generalization.
- **Scope.** Explore-only (faithful stays pure `decide()`); `w_catprior=0`
  disables it. On the current cohort (global 35.6%) the active categories are
  e.g. `restaurant +0.44`, `store −0.20`, `(none) −0.26`, and the leak-free CV
  delta at a 5% budget is ≈ +11 pt held-out coverage (≈ −1 pt at a tight 2%).

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
- VLM alone (`0.3` cap) → cannot cross `τ` ("VLM never auto-picks alone")

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
