# Onboarding — running POI Eval in a fresh environment

This is the practical setup guide for standing the tool up on a new machine.
For the project overview and API list, see [`../README.md`](../README.md).

The system is two processes:

- **Backend** — `python3 server.py`, serves `/api/*` on `:8420`. Pure Python
  **standard library** (Python 3.9+). No `pip install` is required to boot.
- **Frontend** — React 18 + Vite (TypeScript) in `web/`, dev server on `:5173`,
  proxies `/api` → `:8420`.

---

## 1. Prerequisites

| Tool | Version tested | Needed for | Required? |
|------|----------------|------------|-----------|
| Python 3 | 3.9.6 | backend (`server.py`, `tools/`) | **yes** |
| Node.js + npm | Node 24 (18+ fine) | frontend (`web/`) | **yes** |
| Pillow (`pip install Pillow`) | 11.3 | photo **thumbnails** | optional — without it, full-size images are served instead |
| Swift + MapKit | Swift 6.3 (macOS) | live "Investigate" MapKit re-query | **macOS only**, optional |

The backend imports only the Python standard library, so it runs on a clean
interpreter. The only third-party Python package the codebase touches is
**Pillow**, and every call site is guarded (`try: from PIL import …`) — missing
Pillow degrades thumbnails gracefully, it does not break the server.

### Platform note — the Swift MapKit probe is macOS-only

`tools/swift/ls_mapkit_probe.swift` (live nearby query used by the Case
inspector "Investigate" / radius-expand flow) needs Apple's MapKit and a signed
network path, so it **only runs on macOS**. On Linux/other:

- The rest of the tool works normally — runs, match-rate, case inspection, and
  the pre-computed candidate lists shipped in the dataset all function.
- Only the *live* re-query button degrades: `mapkit_probe()` returns
  `{"ok": false, "message": "probe script missing" | swift error}` and the UI
  shows the probe as unavailable.

---

## 2. Get the code

```bash
git clone git@github.com:lavaskiller/poi.git
cd poi
```

Remotes: `origin` → `lavaskiller/poi` (primary). A secondary `inseokr` remote
also exists for the upstream mirror.

---

## 3. Get the data (this is the step that trips people up)

Real datasets and run snapshots are **not in git** — they are user data shared
privately (Google Drive), never committed. `.gitignore` excludes `poi-data/`,
`poi-data-seed/`, and `docs/reports/`.

The backend resolves its **data root** (`DIRECTORY`) in this order:

1. `POI_DATA_DIR` environment variable, if set.
2. Repo-local `poi-data/` — used when it contains `eval_set_reconciled.csv`.
3. Otherwise the repo root (legacy layout).

The data root is expected to contain:

```
eval_set_reconciled.csv          the evaluation set (ground-truth rows)
dashboard_config.json            signals / sources / schema-group config
generated/
  runs/                          saved run snapshots (*.json)
  <mapkit/kakao candidate JSONL> pre-computed nearby lists predict() scores against
```

You have **two ways** to populate it:

### Option A — drop in the shared bundle (full data)

Copy the shared `poi-data/` bundle from Google Drive into the repo root (or
point `POI_DATA_DIR` at it):

```bash
export POI_DATA_DIR=/path/to/poi-data     # optional; repo-local poi-data/ is auto-detected
```

### Option B — bootstrap from the seed bundle (minimal, for a first look)

**Seed bundle location — `poi-data-seed/` at the repo root** (sibling of
`server.py`; hardcoded as `SEED_DIR` in `server.py`). It is gitignored, so a
fresh clone does **not** have it — obtain it from Google Drive and drop it there.
Expected contents:

```
poi-data-seed/
  eval_set_reconciled.csv      initial evaluation set
  dashboard_config.json        matching config
  generated/runs/*.json        pre-scored baseline runs
  presets.json                 (optional) manifest for multiple named bundles
```

With the bundle in place, the app self-seeds on first run:

1. Open the UI with an empty data root → the **"No dataset yet"** onboarding
   screen appears.
2. The dropdown is populated from `GET /api/seed/presets`, which **discovers
   what is actually on disk** (each preset shows its row / baseline counts, and
   is greyed out if unavailable). Without a `presets.json` manifest the bundle
   is offered as a single `default` preset.
3. "Load default setup" → `POST /api/seed` copies the selected preset into the
   live data root. Idempotent: a no-op once `eval_set_reconciled.csv` exists.

If the bundle is missing, the onboarding screen says so and tells you the path
(`poi-data-seed/`) to drop it at — it is not a hard error.

> **Where the seed lands:** on a fresh install the data root defaults to the
> gitignored `poi-data/`, so seeding never writes real user data to the tracked
> repo root. `dashboard_config.json` also exists as a **tracked** template at
> the repo root so the server can boot before any dataset is present; config
> **reads** fall back to it, config **writes** target the data-root copy, and the
> seed never overwrites the tracked template.

---

## 4. Run it

```bash
# backend — serves /api on :8420
python3 server.py

# frontend — in a second terminal
npm --prefix web install     # first time only
npm --prefix web run dev     # Vite dev on :5173, proxies /api → :8420
```

Open http://localhost:5173.

### Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `POI_DATA_DIR` | auto (`poi-data/` or repo root) | explicit data-root override |
| `POI_PORT` | `8420` | backend HTTP port |

---

## 5. Verify the setup

1. Backend up: `curl -s localhost:8420/api/overview` returns JSON (not a
   connection error).
2. Frontend up: http://localhost:5173 loads the sidebar shell.
3. Data wired: the Home / Results pages show dataset counts and at least one
   run. If everything is empty, the data root is not populated — revisit step 3.
4. (macOS only) Case inspector → open a case → "Investigate" runs a live MapKit
   probe. First run is slow (~20–30 s: Swift compile + network). On non-macOS
   this button is expected to be unavailable.

---

## 6. Directory map

```
server.py                 HTTP backend — /api/* (runs, matchrate, datasets, case, jobs, seed, ingest)
tools/                    evaluation + enrichment (algorithms, scoring, OCR/EXIF, MapKit probe)
  run_algorithm.py        run submission + scoring; emits candidate_limit / score_k retrieval contract
  match_score.py          match-rate evaluation + candidate loading
  swift/ls_mapkit_probe.swift   macOS-only live MapKit nearby query (radius-configurable)
web/                      React 18 + Vite + TypeScript frontend
  src/pages/              Home, NewRun, Results, CaseInspector, Compare, Datasets, RetrievalDiagnostics
  src/components/         Button, Tag, StatTile, MapPicker (Leaflet), CaseCard, CandidateRow …
  src/lib/api.ts          typed backend client
dashboard_config.json     tracked config template (boot fallback)
poi-data/                 live data root — gitignored, shared privately
poi-data-seed/            minimal seed bundle for first-run bootstrap — gitignored
docs/                     redesign brief, quality audit, this guide
```
