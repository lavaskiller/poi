# POI Evaluation Tool

Local POI evaluation dashboard/prototype for measuring POI candidate retrieval coverage and, later, algorithm selection accuracy.

This repository is the **public/shareable evaluation-tool layer** split from the private `poi-test-data` workspace. It intentionally contains code, specs, templates, and reports, but not raw user data.

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
- `server.py`
  - `GET /api/matchrate?dataset=all&mode=exact`
  - `GET /api/matchrate?dataset=linkedspaces&mode=exact`
  - `GET /api/matchrate?dataset=all&mode=normalized`
- `mvp-eval-ui.html`
  - evaluation cards now read `/api/matchrate` instead of static mock values
  - normalized mode is shown only as fallback/evidence, not as the primary provider policy
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

- `mvp-eval-ui.html` is still a single-file prototype containing HTML, CSS, and JavaScript together.
- `server.py` is a local dashboard server and still assumes local data files exist outside the public repo.
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
