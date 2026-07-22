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
# Python deps (Pillow, …) — once per environment
python3 -m pip install -r requirements.txt
python3 tools/check_deps.py          # must exit 0 before server will start

# backend — serves /api on :8420 (loopback by default); refuses to boot if deps fail
python3 server.py

# frontend — Vite dev on :5173, proxies /api → :8420
npm --prefix web install   # first time
npm --prefix web run dev
```

**MapKit is not pip-installable.** Live nearby / EXIF / OCR probes on macOS use
system `swift` + Apple frameworks (`tools/swift/*.swift`). `check_deps.py`
requires that toolchain on Darwin.

The frontend calls `/api/*` on its own origin; Vite proxies those to the
Python backend (see `web/vite.config.ts`).

### Tests

```bash
python3 -m unittest discover -s tests -v
```

### Optional security env vars

| Variable | Default | Purpose |
|---|---|---|
| `POI_BIND` | `127.0.0.1` | Listen address (set `0.0.0.0` only intentionally) |
| `POI_PORT` | `8420` | HTTP port |
| `POI_API_TOKEN` | *(empty)* | When set, mutating requests need `X-POI-Token` or `Authorization: Bearer` |
| `POI_ALLOWED_ORIGINS` | local Vite + server | Comma-separated Origin allowlist; empty string disables check |
| `POI_RUN_TIMEOUT_S` | *(none)* | Optional wall-clock timeout for algorithm subprocesses |
| `POI_SKIP_GIT_SYNC_CHECK` | *(empty)* | Set `1` to skip the boot-time “behind origin?” gate |
| `POI_SKIP_DEPS_CHECK` | *(empty)* | Set `1` to skip requirements / Swift gate (not recommended) |
| `POI_GIT_STATUS_TTL_S` | `30` | Cache TTL (seconds) for `/api/git-status` |
| `POI_GIT_FETCH_TIMEOUT_S` | `20` | Timeout for `git fetch` during the sync check |
| `VITE_POI_API_TOKEN` | *(empty)* | Frontend token mirror when backend auth is enabled |

Setting this up on a fresh machine (prerequisites, data bundle, env vars,
platform notes)? See [`docs/onboarding.md`](docs/onboarding.md).

## Backend API (server.py)

`/api/health` · `/api/deps-status` · `/api/git-status` · `/api/overview` · `/api/datasets` · `/api/dataset-template` · `/api/runs` ·
`/api/run` (POST) · `/api/matchrate` · `/api/records` · `/api/poi-case-explorer` ·
`/api/poi-case-photo` · `/api/field-profile` · `/api/jobs` ·
`/api/jobs/status` · `/api/gt/classify` · `/api/ingest` (POST) ·
`/api/validate-upload-package` (POST) · `/api/gt/reconcile` · `/api/mapkit/probe`

On load the UI calls `/api/deps-status` then `/api/git-status`. Missing hard
deps (from `requirements.txt`, or Swift/MapKit scripts on macOS) show
“Dependencies missing” and block the app; a checkout **behind** origin shows
“Update required”. `server.py` itself also exits on boot if hard deps fail.

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
