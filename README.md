# POI Evaluation Tool

Local POI evaluation dashboard/prototype for measuring place retrieval and selection quality.

This repo currently contains the shareable implementation/spec layer only:

- product/system specs and implementation plan
- local dashboard/server prototype
- upload package template and validator
- probe/scoring script sources

Raw user datasets, photos, generated TSV/CSV outputs, FastVLM checkout/venv, and other heavy/private artifacts are intentionally excluded from this public split.

## Current status

The current prototype can show dataset overview and records when local data files are present, but the final metrics path is not complete yet. In particular:

- normalized matching / match scoring engine is still TODO
- `/api/matchrate` is still TODO
- some `mvp-eval-ui.html` evaluation panels are still mock/static until the metrics API is wired

See:

- `REVIEW.md`
- `IMPLEMENTATION-PLAN.md`
- `PRD-SRD-dataset-dashboard.md`

## Upload package validation

```bash
python3 tools/validate_upload_package.py templates/poi-dataset-upload-template.zip --json
```

The empty template ZIP is expected to fail as an upload package because it has no manifest data rows; users should fill `photos/` and `manifest.csv` before uploading.
