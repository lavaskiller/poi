# POI Evaluation Tool

A local, privacy-conscious tool for evaluating point-of-interest (POI) retrieval and identification algorithms.

It provides a browser dashboard to inspect a dataset, ingest a first dataset from a ZIP package, examine candidate-retrieval coverage, and run a submitted `predict(case)` implementation against held-out ground truth. The repository contains **tooling and templates only**—not raw datasets, photos, generated candidates, or personal data.

> **Local-development software, not a hosted service.** `POST /api/run` executes submitted code in a local subprocess. Do not expose this server to an untrusted network or use it as a multi-tenant sandbox.

## Quick start

Requirements:

- Python 3.9+ (standard library only for the dashboard and core tools)
- macOS and Swift are only required for the optional MapKit/Vision probe tools

```bash
git clone git@github.com:lavaskiller/poi.git
cd poi
python3 server.py
```

Open <http://127.0.0.1:8420/>. A fresh clone with no data is a supported state: the UI reports that it is connected but has no dataset, and guides you to the ingestion flow.

## Add a dataset

1. Prepare a ZIP using [`templates/poi-dataset-upload-template.zip`](templates/poi-dataset-upload-template.zip).
2. In the dashboard, open **Dataset management**, validate the package, then ingest it.
3. The first successful ingestion bootstraps `eval_set_reconciled.csv` and a runtime `dashboard_config.json` in the data directory. The newly added dataset is immediately available without restarting the server.

The empty template deliberately fails validation because it has no manifest rows. Fill `manifest.csv` and include its referenced images before uploading.

You can validate a package from the command line:

```bash
python3 tools/validate_upload_package.py templates/poi-dataset-upload-template.zip --json
```

## Data location and privacy

By default, `server.py` uses `./poi-data/` **when it contains** `eval_set_reconciled.csv`; otherwise it retains compatibility with a legacy repository-root data layout. For a normal setup, keep all runtime data under `poi-data/`:

```text
poi-data/
├── eval_set_reconciled.csv
├── dashboard_config.json       # generated runtime copy
├── generated/                  # candidates, jobs, and saved runs
└── <configured photo folders>/
```

To place data elsewhere, set `POI_DATA_DIR` explicitly:

```bash
POI_DATA_DIR=/absolute/path/to/poi-data python3 server.py
POI_DATA_DIR=/absolute/path/to/poi-data POI_PORT=9000 python3 server.py
```

The UI and templates are always served from this checkout; only configured data files are read from the data root. Raw CSV/TSV files, photos, generated artifacts, local keys, caches, and machine-specific settings are ignored by Git. Review a dataset's permissions and provenance before sharing it.

## Run an algorithm

A Python submission defines `predict(case)` and returns a predicted provider-canonical place name (or `""` to abstain):

```python
def predict(case):
    candidates = case.get("nearby_candidates") or []
    return candidates[0]["name"] if candidates else ""
```

Use **Run algorithm** to select only the signals your algorithm may receive, attach the script, choose a scope, and run it. The harness never exposes ground truth in `case`. The included baseline is available in the UI and at [`examples/baseline_nearest.py`](examples/baseline_nearest.py):

```bash
python3 tools/run_algorithm.py examples/baseline_nearest.py \
  --name baseline --params nearby_candidates
```

Results are written below `<data-root>/generated/runs/` and shown under **Run results**. Select persisted executions there to inspect their configuration, outcome distribution, and failed cases; compare up to four executions, and delete one only after a confirmation. The UI labels runs with the same SHA-256 submitted-code hash, so equal scores from identical code are not mistaken for a display problem. Deleting a run permanently removes only its saved run JSON—not a dataset, photo, or source script.

Identification accuracy (`prediction == GT`) is distinct from candidate-retrieval coverage. Current MVP scoring uses same-provider exact-name matching; Korea/Kakao, `non_poi`, blank provider GT, and provider-resolution sentinels (for example `NON_MAPKIT` and `SIM_MAPKIT`) are held out. A raw `input_place_name` is never substituted for a missing provider-canonical GT. Likewise, a scalar `app_nearby_top1` is not a candidate-list artifact: evaluation refuses an eligible case without stored candidate records rather than synthesizing a rank-one candidate.

### Candidate retrieval scope

The current non-Korea retrieval probe uses `MKLocalPointsOfInterestRequest`: strict 80m and wide 250m searches, then distance-from-photo-coordinate ordering (not MapKit relevance ordering). New probe output retains the full wide result as JSON, including MapKit category, identifier when available, candidate coordinates, and distance; `tools/match_score.py --convert-mapkit-tsv` converts it to flat candidate JSONL. Older local snapshots remain lossy (often top-3 and without metadata), and are accepted with empty metadata for backward compatibility.

To create a non-destructive full-candidate benchmark snapshot, first create and
inspect its immutable manifest, then explicitly permit live MapKit queries:

```bash
python3 tools/rebaseline_mapkit_snapshot.py --snapshot-id mapkit-YYYYMMDD
python3 tools/rebaseline_mapkit_snapshot.py --snapshot-id mapkit-YYYYMMDD --execute
```

The snapshot is written below `<data-root>/generated/candidate-snapshots/` and
does not modify the canonical CSV, legacy candidate JSONL, or legacy rerun TSV.
It is a new live MapKit snapshot—not a reconstruction of historical results.
After validation, select a complete snapshot by writing
`<data-root>/generated/active-mapkit-candidate-snapshot.json` with its
`snapshot_id` and `candidate_artifact` (`mapkit_candidates.jsonl`). Evaluation
and the case explorer then use that immutable artifact. The pointer is checked
against the snapshot metadata and candidate SHA-256; it never falls back to the
legacy JSONL when a selected snapshot is invalid.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers candidate conversion, submission harness metadata, the
weighted MapKit example, and confidence-policy action gates. It does not require
a private dataset.

## Confidence-policy simulator

The MVP 1 policy separates a suggestion action from a fake confidence
probability: `AUTO_PICK`, `SHOW_PICKER`, or `NONE`. It uses the weighted MapKit
resolver, direct-tap context when available, conservative OCR name support, and
optional VLM corroboration. VLM alone (including a nearest fallback) never
causes an automatic selection.

```bash
python3 tools/simulate_confidence_policy.py \
  --output poi-data/generated/confidence-policy-v0.json
```

The simulator reads only eligible provider-canonical cases, writes aggregate
risk/coverage metrics plus case-level reason codes to ignored local data, and
records cohort/snapshot hashes. See the [v0 policy report](docs/reports/confidence-policy-simulator-v0.md) for the decision contract and calibration caveats.
## Repository layout

```text
README.md                 Project entry point and local setup
server.py                 Local HTTP server and API
mvp-eval-ui.html/.js      Current dashboard UI
examples/                 Runnable submission examples
  baseline_nearest.py     Minimal nearest-candidate baseline
  mapkit_weighted.py      Category-aware MapKit selector with single/ambiguous policy
  poi_confidence_policy.py Action-tier policy for auto/picker/none UX
templates/                Public upload-package templates
tools/                    Active evaluation, ingestion, and probe utilities
  swift/                  Reusable Swift probe sources
  run_vlm_topk_rerank.py Optional FastVLM Top-K reranker runner (local model/env)
  simulate_confidence_policy.py Risk-coverage simulator for the action policy
tests/                    Unit tests for the harness and examples
docs/                     Canonical API and functional documentation
  archive/                Superseded dated specifications and reviews
  reports/                Daily activity record and active policy notes
    daily/                One report per calendar day (continuity checked)
archive/web-prototypes/   Historical browser prototypes (not active routes)
experiments/              Historical/offline experiments (not supported entry points)
poi-data/                 Ignored local runtime data (created or supplied locally)
```

## Documentation

- [API contract](docs/API.md)
- [Functional specification](docs/functional-spec.md)
- [Daily reports](docs/reports/daily/README.md)
- [Archived design/history](docs/archive/README.md)
- [Historical experiments](experiments/README.md)
- [Archived web prototypes](archive/web-prototypes/README.md)

## Current limitations

- This is a local, single-user prototype—not an authentication boundary or hardened code-execution environment.
- Candidate coverage and identification quality are intentionally reported as different metrics.
- Provider-canonical GT is required for scoring. Empty provider GT fields and resolution sentinels are held out; raw `input_place_name` is never used as the answer label.
- Direct run comparison requires the same evaluation cohort and scoring mode. Data-snapshot differences are warned but do not rewrite metrics.
- The public repository has no real dataset, so real metric values are not reproducible until you supply a permitted local dataset.
- FastVLM baseline execution needs a local model environment under `poi-data/`; the runner and reports are public, but the model weights and private photos are not.
- Several enrichment backends are represented in the UI/config but are not implemented; the server returns an explicit unavailable status rather than simulating results.
