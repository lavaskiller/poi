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
2. In the dashboard, open **④ 데이터셋 추가**, validate the package, then ingest it.
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

Use **② 평가 실행** to select only the signals your algorithm may receive, attach the script, choose a scope, and run it. The harness never exposes ground truth in `case`. The included baseline is available in the UI and at [`examples/baseline_nearest.py`](examples/baseline_nearest.py):

```bash
python3 tools/run_algorithm.py examples/baseline_nearest.py \
  --name baseline --params nearby_candidates
```

Results are written below `<data-root>/generated/runs/` and shown in **③ 평가 결과**. Identification accuracy (`prediction == GT`) is distinct from candidate-retrieval coverage. Current MVP scoring uses same-provider exact-name matching; Korea, `non_poi`, and rows without GT are held out until the required provider data is available.

## Repository layout

```text
README.md                 Project entry point and local setup
server.py                 Local HTTP server and API
mvp-eval-ui.html/.js      Current dashboard UI
examples/                 Runnable submission examples
templates/                Public upload-package templates
tools/                    Active evaluation, ingestion, and probe utilities
  swift/                  Reusable Swift probe sources
docs/                     Canonical API and functional documentation
  archive/                Superseded dated specifications and reviews
  reports/                Dated project reports
archive/web-prototypes/   Historical browser prototypes (not active routes)
experiments/              Historical/offline experiments (not supported entry points)
poi-data/                 Ignored local runtime data (created or supplied locally)
```

## Documentation

- [API contract](docs/API.md)
- [Functional specification](docs/functional-spec.md)
- [Archived design/history](docs/archive/README.md)
- [Historical experiments](experiments/README.md)
- [Archived web prototypes](archive/web-prototypes/README.md)

## Current limitations

- This is a local, single-user prototype—not an authentication boundary or hardened code-execution environment.
- Candidate coverage and identification quality are intentionally reported as different metrics.
- The public repository has no real dataset, so real metric values are not reproducible until you supply a permitted local dataset.
- Several enrichment backends are represented in the UI/config but are not implemented; the server returns an explicit unavailable status rather than simulating results.
