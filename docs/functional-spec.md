# POI Evaluation Tool — Functional Spec (by page)

> Target UI: `mvp-eval-ui.html` (single page, four tabs).
> Numbers in the UI come from live server APIs (no mock data). Data lives under `poi-data/` or `POI_DATA_DIR`.
> API details: [API.md](API.md). Last structural update: 2026-07-10 (wording English, 2026-07-20).

## 0. Entry and page layout

| Page (tab) | Role |
|---|---|
| **Overview** | Health of the connected evaluation set: provenance, confidence tiers, signal pipeline, column coverage |
| **Run algorithm** | Upload `predict()`, choose inputs/scope, execute, list recent runs |
| **Run results** | Browse/compare/delete saved runs; retrieval diagnostics; failure cases |
| **Dataset management** | Dataset table, rerun extraction steps, validate/add/delete datasets, job progress |

Language: the UI ships with **English** as the default and optional Korean strings for local use. Product documentation in this repository is **English**.

## 1. Overview — `GET /api/overview`

- Shows whether the API is connected and whether any dataset exists.
- Summarizes total rows, rows with GT, rows with photos, countries.
- Renders provenance chips, confidence-tier legend, signal pipeline steps, and the row-structure / coverage table.
- Config gaps (unknown datasets/columns/tiers) appear as warnings.

## 2. Run algorithm — `POST /api/run` · `GET /api/runs`

- User selects datasets (multi), GT inspection scope, and which case signals to pass into `predict(case)`.
- Attaches a script (or loads the nearest-candidate example).
- Chooses run name and save mode (auto-version vs overwrite).
- On success, the scored run is persisted and appears under Run results.
- The harness never injects ground truth into `case`.

## 3. Run results — `GET /api/matchrate` · `GET /api/records` · runs detail

- Library of saved runs with search, sort, compare (up to 4), and delete-with-confirm.
- Metrics: exact identification accuracy, correct/eligible, host latency (desktop host, not mobile).
- Retrieval diagnostics: GT in rank-1 / top-K / miss (provider coverage ceiling).
- Case analysis lists success/failure examples with photo when available.
- Dual metrics when label relations are configured: **strict** exact name vs **canonical** (aliases / related credit).

## 4. Dataset management — validate · ingest · rerun · delete

- List datasets with processing and detection coverage per signal.
- **Rerun extraction** for unprocessed rows (EXIF, OCR, MapKit nearby, GT classify, …).
- **Validate ZIP** then **Add dataset** (async job).
- **Delete dataset** with confirmation (may keep or purge photos depending on mode).
- Only one data job runs at a time.

## Data flow (summary)

```text
ZIP (manifest + photos)
  → validate → ingest job → CSV rows + photo folders + config stub
  → rerun jobs fill EXIF / OCR / MapKit / GT columns
  → Overview reflects coverage
  → Run algorithm → scored run JSON under generated/runs/
  → Run results for inspection and comparison
```

## Out of scope for this tool surface

- Hosting multi-tenant untrusted code on a public network.
- Shipping raw evaluation photos or private `poi-data/` in git.
- Editing intern daily journals (those stay in the working repo, not the published tool snapshot).
