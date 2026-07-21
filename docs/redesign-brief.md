# POI Eval — Redesign Brief (v2)

> Handover package for the UI/UX redesign of the internal POI-evaluation tool.
> Figma concept: https://www.figma.com/design/L9SVYaGbdHRowtiwEQtFUv
> Companion visual reference: `docs/reports/poi-case-types.html` (the "north star" report style)

## 1. Purpose — one sentence

Help an eval engineer/PM **run the improvement loop faster**: run an algorithm → get one
trustworthy accuracy number → understand *why* it missed → ship a better version.
Everything on screen either advances that loop or gets out of the way.

Audience: a small technical team. Clarity and speed over polish; no marketing surface.

## 2. The journey (IA backbone)

The old UI was 4 flat tabs. The redesign expresses the natural order as a persistent
sidebar with two groups:

| Group | Page | Job it serves |
|---|---|---|
| Workflow | **Home** | "Where am I? Is data OK? What's next?" — headline accuracy, data health, next-step cards |
| Workflow | **New run** | Guided 3-step flow: ① Algorithm ② Inputs ③ Scope & run |
| Workflow | **Results** | Run detail: metric tiles + failure-taxonomy filters + **case-card gallery** (the centerpiece) |
| Workflow | **Compare** | v-A vs v-B duel, delta table, **flipped cases** (fixed / broken) |
| Data | **Datasets** | Per-dataset signal coverage, calm background-jobs panel, validated ZIP ingest |
| Data | **Jobs** | (folded into Datasets in the concept; may split if job volume grows) |

Case inspector is a drill-in from Results: photo ↔ signals ↔ ranked candidates
(GT / PICK badges) ↔ prediction-vs-GT verdict ↔ the algorithm's own `reason`.

## 3. Core flows (unchanged backbone, now mapped to pages)

1. "Is my data OK?" → Home health strip → Datasets coverage bars
2. "Run my algorithm, get a number" → New run (3 steps) → lands on Results
3. "Why did it miss?" → Results gallery → Case inspector
4. "Did B beat A?" → Compare (delta table + flips — flips are the insight, not just the delta)
5. "Add a batch" → Datasets → validate → ingest → enrichment jobs

## 4. How the old pain points were addressed

| Pain | Design answer |
|---|---|
| Dev-centric run flow (IDE feel) | Numbered 1-2-3 sections; dropzone + example; contract shown as one friendly mono line; code preview demoted to "View code →". Script power path fully kept. |
| Dense long-scroll pages | One headline metric per page; section eyebrows; everything else one level down |
| No sense of place/progress | Sidebar journey groups; stepper in New run; "What's next" cards on Home |
| Failure inspection under-designed | Case cards with photo, semantic left band, PREDICTED vs GROUND TRUTH rows; inspector with ranked candidates & map |
| Jobs feel unreliable | Single active-job card with %, count, ETA, and a calming line ("keep working — rows appear as they finish") |

## 5. Visual system (implemented as Figma tokens)

- Light-first, full dark mode via variable modes (`POI Eval Tokens`, Light/Dark).
- Semantic roles from the case-types report: **green = correct/healthy, amber =
  selection-miss/warning, red = retrieval-miss/problem, purple = policy/non-POI.**
- Type: Inter (UI) + JetBrains Mono (ids, metrics, code). Tabular numerals for metrics.
- Radii 8/12/16, hairline borders, soft two-layer shadow, uppercase letter-spaced
  section labels — same language as the report hero/stat tiles/card galleries.
- Components: Button, Tag, StatTile, NavItem, Sidebar, ProgressBar, CandidateRow
  (Default/GT/Picked), CaseCard — all bound to tokens.

## 6. Data available per screen (API map)

`overview` (health, provenance, tiers, row structure) · `matchrate` · `run/runs`
(submit, list, versions) · `records`/`field` (per-case, per-field) · `gt` ·
`datasets` · `validate`/`ingest` · `jobs` (EXIF/OCR/MapKit-nearby/GT-classify).
Every number shown in the concept exists in one of these endpoints.

## 7. Constraints & non-goals

- Internal tool; small technical audience; desktop-first (1440).
- Must keep the upload-a-script power path and multi-language contract (.py/.js/.rs/.c/.sh).
- Strict vs canonical scoring must both be visible, strict as the default headline.
- Light/dark both required (tokens already carry it).
- Non-goals: onboarding, mobile, multi-tenant, permissions.

## 8. Success criteria

- A first-time teammate can go from "open tool" to "saw why case X failed" without help.
- One glance at Home answers: current best accuracy, data health, what to do next.
- Comparing two versions surfaces *which cases flipped*, not just the aggregate delta.

## 9. Open questions for design

- Should retrieval diagnostics (provider top-N coverage) live in Results or Datasets?
- Case inspector: side-panel overlay vs full page (concept uses full page)?
- Do we need per-country slicing as a first-class filter or a query param?

## 10. Design review — gaps vs current web

Checked the concept (as described in this brief) against what `mvp-eval-ui.html/js`
already ships. Items below are current-web capabilities that the concept drops,
weakens, or leaves unplaced. Confirm each against the Figma; if already covered,
mark done.

### P0 — feature regressions (current web does this today)

1. **Retrieval diagnostics has no home.** The live tool ships rank-1 / top-3/5/10/20/50 /
   miss tiles, a **provider top-N coverage curve**, per-algorithm selection-accuracy
   bars, and a case-analysis explorer (`mvp-eval-ui.html:414–464`). The concept only
   references this as open question #9. This is what separates a *retrieval miss* from a
   *selection miss* — it must land somewhere (Results or Datasets), curve included.
2. **Compare downgraded 4-way → 2-way.** Current web compares up to 4 runs with a
   same-cohort/same-scoring guard (`:389`, `:412`). Keep flipped-cases, but keep the
   N-way table + the "incomparable runs" warning too.
3. **Job history + logs collapsed to one active card.** Current web has a job list with
   elapsed/result and an expandable log (`:489–495`). Keep a "past jobs / logs" affordance
   for debugging failed jobs.
4. **Per-step rerun-extraction control.** Step (EXIF/OCR/MapKit/GT-classify) × dataset ×
   "unprocessed only" (`:477–487`) must survive in Datasets.
5. **Run versioning / save mode.** Auto-versioning, overwrite mode, "latest version only"
   filter, version grouping — place these in the New-run stepper.

### P1 — states & metrics not shown in the concept

6. **Metric tiles**: confirm strict-vs-canonical (strict = headline) *and* host-latency
   and correct/eligible counts all appear in Results, not just accuracy.
7. **Empty / loading / error states.** Current web has explicit "no dataset yet", API-error
   + Retry, and loading placeholders (`:282`, `:299`). First-run quality *is* success
   criterion #1 — Home/Datasets/Results need these states drawn.
8. **Overview asset migration.** provenance chips, confidence-tier legend, signal-pipeline
   steps, country bars, row-structure coverage table — verify each finds a home in
   Home/Datasets (easy to drop the tier legend & pipeline).
9. **Config-gap warnings.** Unknown dataset/column/tier warnings and the "sparse signals
   lower the ceiling" warning should feed Home's data-health.
10. **Bilingual layout.** UI is fully KO/EN (`data-i18n`); check sidebar width and tile
    labels don't break with longer Korean strings.

### Kept well (no action)
Home + sidebar journey, 3-step New-run stepper, case-card gallery + inspector (photo ↔
signals ↔ ranked candidates ↔ verdict ↔ reason ↔ map), Compare flipped-cases.

## 11. Resolution log (2026-07-21) — review items applied to the Figma

| # | Item | Status | Where in Figma |
|---|---|---|---|
| P0-1 | Retrieval diagnostics | ✅ new screen | **07 · Retrieval diagnostics** — rank-1/top-3/5/10/50/miss tiles, provider top-N coverage curve, per-algorithm accuracy bars, "ceiling not accuracy" note. Entry point: Results (open q. #9 resolved → Results drill-in) |
| P0-2 | 4-way compare + cohort guard | ✅ edited | **05 · Compare** — "Comparing 2/4" tray with run chips + "＋ Add run"; excluded-run chip with amber guard banner (different cohort). N-way table stays 2-col in the mock; columns extend per selected run |
| P0-3 | Job history + logs | ✅ edited | **06 · Datasets** — history rows now carry `log →` links; active job keeps %, counts, ETA |
| P0-4 | Per-step rerun | ✅ edited | **06 · Datasets** — RERUN control row: step ▾ × dataset ▾ × "unprocessed only" ✓ × ▶ Rerun |
| P0-5 | Save mode / versioning | ✅ edited | **02 · New run** step 3 — "Save mode: Auto — next version (v8) ▾ / or overwrite". Latest-only filter & version grouping belong to Home recent-runs (noted, not drawn) |
| P1-6 | Metric tile completeness | ✅ already covered | **03 · Results** — strict headline + canonical tile + correct/eligible counts + host runtime in subheader |
| P1-7 | Empty / error / loading | ✅ new screen | **08 · States & appendix** — first-run empty state, API-error banner + Retry, skeleton loading pattern |
| P1-8 | Overview asset migration | ✅ appendix | **08** — row-structure coverage table (→ Dataset-detail drill-in, to be drawn), provenance + GT-tier stacked bars. Countries → Home tile; signal pipeline → per-dataset coverage bars |
| P1-9 | Config-gap warnings | ✅ appendix | **08** — three warning patterns (unknown column, excluded tier rows, sparse-signal ceiling); surfaced on Home data-health + inline at point of choice |
| P1-10 | Bilingual (KO/EN) | ✅ verified, no change | KO labels are shorter than EN (홈/새 실행/결과/비교/데이터셋); 240px sidebar and tile labels safe. Keep `data-i18n` keys 1:1 |

Still open: Dataset-detail drill-in (full 11-field row structure + per-field profile) and
an N≥3 compare table column layout — both noted in the frames, not yet drawn.

## 12. Component review round (2026-07-21) — feedback applied

**Interaction definitions**
- **"Rerun extraction →" (dataset row)**: prefills the RERUN control row (step ▾ ×
  dataset ▾ × unprocessed-only) and focuses it; `▶ Rerun` enqueues a background job that
  appears as the active-job card (%, counts, ETA). One job at a time (server constraint) —
  button disables with the reason while another job runs. No confirm modal: non-destructive
  and idempotent (unprocessed-only default).
- **Deletion (was missing — now specified)**: row-level `⋯` overflow → Delete.
  Runs: simple confirm. Datasets: **type-to-confirm modal** (removes rows, photos, derived
  signals, and run references); Delete stays disabled until the typed name matches.
  Pattern drawn in **08 · States & appendix**; `⋯` added to dataset rows.

**Component changes**
| Feedback | Applied |
|---|---|
| Button needs loading + hover/focus/disabled | Button set is now **kind (3) × state (5)**: Default / Hover / Focus (accent ring) / Disabled (45%) / Loading (spinner + "Running…"). |
| CandidateRow missing PICK==GT | New **state=Hit** variant — green fill + heavier border + `✓ PICK = GT` badge. |
| CaseCard: correct variant + color-only risk | CaseCard is now a variant set **verdict=Miss / verdict=Correct**; ✓/✗ icons pair with color everywhere (swept all existing instances + metric tiles). |
| HEIC won't render in browsers | Engineering task: **ingest generates JPEG/WebP thumbnails**; UI shows thumb, links original HEIC. (Filenames in mocks stay HEIC as source-of-truth name.) |
| Tag POLICY ambiguous | Renamed **tone=NonPOI**, documented as *category, not severity* (Foundations sheet note). |
| WARNING amber contrast | Light-mode `warning/fg` darkened `#a86d0f → #8a590b` (≥4.5:1 on `warning/bg`). |
| Foundations sheet missing | New **Foundations** section: all 19 color tokens with light/dark swatches + hex, 13-style type ramp, radius/spacing scale, semantic-role legend. |
| Dark mode | Already shipped — see "01 · Home — Dark mode" frame (token-mode switch only). |
| File named "Untitled" | Plugin API cannot rename documents — rename manually to "POI Eval — Redesign". |

**Product-view suggestions applied**
- **GT source badge**: CaseCard GT row and Case-inspector GT row now carry
  `src · kakao` / `src · mapkit` chips, annotated *"name-classified, not resolved"* —
  gt_mapkit/gt_kakao classify names, they don't resolve the answer.
- **Score exposure**: CandidateRow shows matchrate `score` next to distance;
  inspector candidates carry per-row scores. Results headline tile is annotated
  **"ranked by legacy app_poi_rank"** so the score provenance is never mistaken.

## 13. Review round 3 (2026-07-21) — matrix closure

| Feedback | Applied |
|---|---|
| PICK≠GT (miss) state missing | CandidateRow matrix closed: **Default / GT / Picked / Hit / Miss / NonPOI**. Miss = red border+tint, `✗ PICK ≠ GT` badge. Picked = picked but GT unknown/absent (retrieval-miss context); Miss = GT present elsewhere in list. Inspector rank-1 row switched to Miss accordingly. |
| Score hierarchy too weak | Score now `text/primary` (was tertiary grey) + **mini heat-bar** (26×4, semantic tone per state) before the number. Distance stays tertiary. |
| NON-POI at row/card level | New **CandidateRow state=NonPOI** (purple tint + NON-POI badge) and **CaseCard verdict=NonPOI** (purple band, `◌ deferred` prediction, `src · gt-classify`). Results gallery #0102 now uses the real variant instead of ad-hoc overrides. |
| CaseCard correct variant "still missing" | It exists since round 2 — **verdict=Correct** (green band, `✓` values). Results gallery shows only failures by design (it's the failure view); Correct appears in the component sheet and would appear in an "all cases" filter. |
| Button matrix lacks captions | Set re-laid as a fixed **kind × state grid** with row captions (PRIMARY/SECONDARY/GHOST) and column captions (DEFAULT/HOVER/FOCUS/DISABLED/LOADING). All component sets now carry name labels on the sheet. |
| "Foundations/dark mode still missing" | Stale observation — both shipped in round 2: **Foundations** section (tokens/type/spacing) and **01 · Home — Dark mode** frame. Only the file rename remains manual (API limitation). |
