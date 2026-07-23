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

**The repo can live anywhere** (`~/src/poi`, `/opt/poi`, a USB path, another
machine). Nothing is hardcoded to Desktop or a username. Paths are resolved
from `server.py` / this checkout (`REPO_DIR = dirname(server.py)`).

What *does* matter: **backend and Vite must be started from the same clone.**
Two copies (e.g. `~/Desktop/poi` and `~/Desktop/test_poi/poi`) with mixed
processes cause API 404 / version skew — not a path-layout requirement.

```bash
cd /wherever/you/cloned/poi      # any path is fine

# one shot: Python + npm setup, backend :8420, and frontend :5173
chmod +x tools/dev_up.sh         # once
./tools/dev_up.sh
```

`dev_up.sh` runs `tools/setup.sh`, including `npm --prefix web install`, then
starts both processes from this checkout. Press Ctrl-C once to stop both.
Useful alternatives:

```bash
./tools/setup.sh                 # install/check Python + frontend, then exit
./tools/dev_up.sh --setup-only   # same one-time setup through the launcher
./tools/dev_up.sh --backend-only # API only; npm/node_modules are not required
./tools/dev_up.sh --skip-install # fast restart using already-installed deps
```

Manual equivalent:

```bash
python3 -m pip install -r requirements.txt
python3 tools/check_deps.py
python3 server.py

# second terminal, when running manually
npm --prefix web install
npm --prefix web run dev
```

**MapKit is not pip-installable.** Live nearby / EXIF / OCR probes on macOS use
system `swift` + Apple frameworks (`tools/swift/*.swift`). `check_deps.py`
requires that toolchain on Darwin; on Linux that check is optional.

The frontend calls `/api/*` on its own origin; Vite proxies those to
`localhost:8420` (see `web/vite.config.ts`) — also path-independent.

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
