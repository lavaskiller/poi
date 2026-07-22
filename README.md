# POI Eval

Internal tool for evaluating POI (point-of-interest) prediction algorithms.
Monorepo: a React frontend (`web/`) talking to the Python evaluation backend
(`server.py` + `tools/`).

> The previous vanilla-JS UI and full history are preserved on the
> **`legacy-mvp`** branch.

## Layout

```
web/          React 18 + Vite + TypeScript frontend (design-system UI)
server.py     Python HTTP backend — serves /api/* (runs, matchrate, datasets, jobs, …)
tools/        evaluation + enrichment tools (algorithms, OCR/EXIF/MapKit jobs, scoring)
poi-data/     local datasets + run snapshots (gitignored — shared privately, not online)
```

## Develop

Run the backend and the frontend together:

```bash
# backend — serves /api on :8420
python3 server.py

# frontend — Vite dev on :5173, proxies /api → :8420
npm --prefix web install   # first time
npm --prefix web run dev
```

The frontend calls `/api/*` on its own origin; Vite proxies those to the
Python backend (see `web/vite.config.ts`).

Setting this up on a fresh machine (prerequisites, data bundle, env vars,
platform notes)? See [`docs/onboarding.md`](docs/onboarding.md).

## Backend API (server.py)

`/api/overview` · `/api/datasets` · `/api/dataset-template` · `/api/runs` ·
`/api/run` (POST) · `/api/matchrate` · `/api/records` · `/api/poi-case-explorer` ·
`/api/poi-case-photo` · `/api/field-profile` · `/api/jobs` ·
`/api/jobs/status` · `/api/gt/classify` · `/api/ingest` (POST) ·
`/api/validate-upload-package` (POST)

## Frontend structure (`web/src`)

```
styles/tokens.css     Figma Foundations → CSS variables
components/            Button, Tag, StatTile, ProgressBar, Sidebar, CaseCard, CandidateRow
pages/                Home, NewRun, Results, CaseInspector, Compare, Datasets, RetrievalDiagnostics
App.tsx               router + sidebar layout shell
```

## Status

Pages are built to the Figma redesign. Current work: wiring the UI to the real
backend and implementing onboarding (seed dataset + two baseline runs available
from a first-run dropdown). Empty / loading / error / destructive-confirm states
from the design appendix are applied in-place per page.
