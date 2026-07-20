# POI Evaluation Tool — API Reference

> Server: `server.py` (Python standard-library `http.server`, single local user).
> The UI is served from this repository; dataset files are read from `POI_DATA_DIR`.
> Page behavior is documented in [functional-spec.md](functional-spec.md). Response shapes below match live responses as of 2026-07-10 (updated fields may appear in newer builds).

## Running the server

```bash
# Default port 8420. Base URL = http://127.0.0.1:<PORT>
python3 server.py
POI_PORT=9000 python3 server.py
POI_DATA_DIR=/absolute/path/to/poi-data python3 server.py
```

## Conventions

- JSON request/response bodies use UTF-8.
- Errors return a JSON object with at least `ok: false` and a short `error` string (and sometimes `message`).
- Ground truth is never included in the `case` object passed to a submitted `predict()` implementation.
- Identification scoring uses provider-exact place names (MapKit / Kakao holdouts apply).

## Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | `302 → /mvp-eval-ui.html` |
| GET | `/api/overview` | Dataset structure and aggregates (Overview tab) |
| GET | `/api/records` | Case records for case analysis |
| GET | `/api/matchrate` | Candidate-retrieval coverage metrics |
| GET | `/api/datasets` | Datasets and per-signal fill status |
| GET | `/api/runs` | List saved algorithm runs, or one run detail |
| DELETE | `/api/runs` | Permanently delete a saved run by name + version |
| GET | `/api/jobs` · `/api/jobs/status?job_id=…` | Async jobs and status |
| POST | `/api/run` | Submit and score an algorithm |
| POST | `/api/validate-upload-package` | Validate a dataset ZIP |
| POST | `/api/ingest` | Queue async ZIP ingestion |
| GET | static | `mvp-eval-ui.html/.js`, `/examples/*`, `/templates/*` from the repo; configured photo folders from the data root |

## GET `/api/overview`

Returns dataset provenance, confidence-tier rollups, signal pipeline status, schema/coverage by column, and config warnings.

Typical top-level keys: `sources`, `confidence_tiers`, `signals`, `schema`, `coverage_by_dataset`, `totals`, `config_warnings`.

## GET `/api/records`

Query parameters filter the evaluation rows used in case analysis (dataset, outcome class, provider, etc.). Each record includes identifiers (`dataset`, `photo`), GT fields when present, baseline fields, and display helpers for the UI.

## GET `/api/matchrate`

Returns retrieval coverage for the active MapKit (or configured) candidate provider: fractions of eligible rows where the GT appears at rank 1, in top-K, or is missing from the candidate list. This is a **coverage ceiling**, not algorithm accuracy.

## GET `/api/runs`

- Without `name`/`version`: list of saved runs with metrics summary (accuracy, eligible count, host latency, params, hashes).
- With `name` and `version`: full run JSON including per-case predictions and scores.

## DELETE `/api/runs?name=<name>&version=<positive integer>`

Deletes one persisted run file. Does not delete datasets, photos, or scripts.

## POST `/api/run`

JSON body (fields may grow):

| Field | Meaning |
|---|---|
| `name` | Run name (versioned) |
| `scope` | Dataset scope (`all` or a dataset id) |
| `mode` | Scoring mode (`exact` default) |
| `params` | List of signal keys allowed into `case` |
| `candidate_limit` | Optional top-K for nearby candidates |
| `script_text` | Source of the submission |
| `lang` | Language hint (`python`, …) |
| `save_mode` | Versioning: auto next version or overwrite |

Response includes run metrics and the path/version of the saved run under `<data-root>/generated/runs/`.

## POST `/api/validate-upload-package`

Multipart upload of a dataset ZIP. Returns validation success/failure, row/image counts, and error messages. Does not ingest.

## POST `/api/ingest`

Multipart upload of a validated (or to-be-validated) ZIP. Starts an async job that materializes CSV rows, photos, and config stubs. Derived signals (EXIF, OCR, MapKit, GT classify) are filled by later rerun jobs.

## GET `/api/datasets` · jobs

`/api/datasets` reports per-dataset row counts and signal processing/detection coverage.  
`/api/jobs` lists background jobs; `/api/jobs/status?job_id=…` polls one job (progress, logs, result).

## Static routes

- UI and examples: repository root.
- Photo assets: only under configured `photo_dir` folders in the data root.
