# POI Evaluation Tool

Local POI evaluation dashboard/prototype for measuring POI candidate retrieval coverage and, later, algorithm selection accuracy.

This repository is the **public/shareable evaluation-tool layer** split from the private `poi-test-data` workspace. It intentionally contains code, specs, templates, and reports, but not raw user data.

## Quick start

The code is portable — no paths to edit. Clone, drop the dataset in, run:

```bash
git clone git@github.com:lavaskiller/poi.git
cd poi

# The dataset is delivered separately as a ZIP. Unzip it INTO the repo folder.
# Its files (all git-ignored) land next to server.py:
#   eval_set_reconciled.csv
#   dashboard_config.json           (optional; repo already ships one)
#   generated/mapkit_candidates.jsonl
#   linkedspaces-photos/  photos/  union-city-trip/   (images)
#   *.tsv                           (probe outputs)
unzip poi-dataset.zip -d .

python3 server.py           # no args, stdlib only
# → open http://127.0.0.1:8420/   (redirects to /mvp-eval-ui.html)
```

`server.py` boots even with **no dataset**: the UI loads and the data views stay
empty (the client tolerates the missing-CSV API error) until you add the ZIP. So
you can clone and run first, then drop the dataset in.

### Keeping data outside the repo (optional)

By default the server reads the dataset from its own folder. To keep data in a
separate workspace instead of unzipping into the repo, point it there:

```bash
POI_DATA_DIR=/path/to/poi-test-data python3 server.py   # data root
POI_PORT=9000 python3 server.py                          # override port (default 8420)
```

The UI is always served from this repo; only dataset files (photos, CSV,
`generated/`) are read from `POI_DATA_DIR`, so you never get a stale UI.

## Submitting an algorithm (② 평가 실행 → ③ 식별 정확도)

The dashboard runs a submitted algorithm over the whole eval set and scores it.
A submission is a Python file defining one function:

```python
def predict(case) -> str:      # return the predicted place name, or "" to abstain
    # `case` exposes only the input signals you tick in the UI, e.g.:
    #   case["nearby_candidates"] -> [{"name","rank","distance_m"}, ...]  (nearest first)
    #   case["ocr_text"], case["lat"], case["lon"], case["geocode"], case["category_hint"], ...
    # `case` never contains the ground-truth answer.
    cands = case.get("nearby_candidates") or []
    return cands[0]["name"] if cands else ""
```

- Attach it in **② 평가 실행**, pick a scope, and press ▶ 실행.
- The harness scores `prediction == GT` with the same provider-exact policy as
  candidate retrieval (**identification accuracy**, distinct from retrieval
  coverage). Korea rows / non_poi / no-GT rows are held out automatically.
- Results persist to `generated/runs/<name>__v<k>.json` (name-based
  auto-versioning) and appear as a real bar in **③ 식별 정확도 — 알고리즘별**.
- A worked example ships in [`examples/baseline_nearest.py`](examples/baseline_nearest.py)
  (predict the nearest candidate — the floor every real algorithm should beat).

CLI equivalent, no server needed:

```bash
python3 tools/run_algorithm.py examples/baseline_nearest.py --name baseline --params nearby_candidates
```

Excluded from this public split:

- raw CSV/TSV datasets
- user photos
- generated candidate JSONL/TSV outputs
- FastVLM checkouts, virtualenvs, caches, and other heavy artifacts
- local SSH/deploy keys or private machine state

## Current status

Implemented MVP pieces:

- `tools/match_score.py`
  - stdlib-only provider-aware candidate-retrieval evaluator
  - CLI: `python3 tools/match_score.py --json`
  - default policy: same-provider exact string equality between canonical GT name and candidate name
  - optional candidate JSONL loading
  - legacy MapKit `app_poi_rank` support for the current private reconciled CSV
  - `ls_nearby_results.tsv` → candidate JSONL converter for local generated artifacts
- `server.py` (stdlib http.server, portable — data root via `POI_DATA_DIR`)
  - `GET /api/overview` · `GET /api/records` — live dataset structure/cases
  - `GET /api/matchrate?dataset=all&mode=exact|normalized` — candidate retrieval
  - `POST /api/run` · `GET /api/runs` — submit/score/list algorithm runs
  - `POST /api/validate-upload-package` — validate a dataset ZIP
- `tools/run_algorithm.py`
  - runs a submitted `predict(case)` over the eval set in an isolated subprocess
  - scores identification accuracy (prediction == GT, provider-exact); Korea /
    non_poi / no-GT held out; persists versioned runs to `generated/runs/`
- `mvp-eval-ui.html` / `mvp-eval-ui.js`
  - every number reads a server API — overview/retrieval/cases and the algorithm
    submission → identification-accuracy chart are all live, no mock values
- `tools/validate_upload_package.py`
  - validates user-filled dataset ZIP packages before ingest

## MVP scoring policy

- Korea rows are currently **held out** until Kakao Local canonical/candidate data is populated.
- Non-Korea candidate retrieval is currently measured against MapKit; Korea is held out until Kakao Local data exists.
- These MapKit/Kakao numbers are **candidate coverage/rank metrics**, not visual/user-intent identification accuracy.
- MVP retrieval matching is exact string equality within the same provider.
- `provider_place_id` is nullable/optional and is not required for MVP scoring.
- The public MVP UI reports the provider-specific exact-name candidate retrieval metric only; normalized/string-relaxed checks are not used as the displayed scoring policy.

With the current private local dataset snapshot, the Korea holdout candidate-retrieval result is:

```text
all:          n=228 rank1=38 top3=59 top5=68 miss=143 KR-held-out=28 no-provider-data=10
linkedspaces: n=190 rank1=30 top3=45 top5=53 miss=122 KR-held-out=28 no-provider-data=10
union-city:   n=27  rank1=3  top3=4  top5=4  miss=21  KR-held-out=0
vancouver:    n=11  rank1=5  top3=10 top5=11 miss=0   KR-held-out=0
```

These numbers require the private CSV/candidate artifacts and are not reproducible from the public repo alone.

## Why the repo still looks messy

This repo was split from an active prototype workspace, not built as a greenfield package. The public split first removed private/raw/generated artifacts and then wired the MVP metrics path. Structural cleanup is intentionally incremental.

Known sources of messiness:

- `mvp-eval-ui.html` is still a single-file prototype containing HTML and CSS together (JS is split into `mvp-eval-ui.js`).
- `server.py` is a local single-user dashboard server; `POST /api/run` executes the submitted script in a subprocess (fine for local use, not a hardened multi-tenant sandbox).
- Specs/reviews/plans were written across iterations, so some older docs may describe pre-MVP gaps unless noted by newer reports.
- Generated/private data is excluded, so some commands only work in the private workspace unless equivalent local data is supplied.

Cleanup direction:

- keep public repo free of raw/private/generated artifacts
- add dated work logs under `report/`
- refresh README/status as implementation changes
- later split UI/server modules once MVP behavior is stable

## Upload package validation

```bash
python3 tools/validate_upload_package.py templates/poi-dataset-upload-template.zip --json
```

The empty template ZIP is expected to fail as an upload package because it has no manifest data rows; users should fill `photos/` and `manifest.csv` before uploading.

## Related docs

- `PRD-SRD-dataset-dashboard.md`
- `IMPLEMENTATION-PLAN.md`
- `REVIEW.md`
- `report/`
