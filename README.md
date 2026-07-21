# POI Eval — UI

React + Vite frontend for the POI evaluation tool, built from the Figma
"POI Eval — Redesign". This branch (`main`) is **frontend-only**.

> The previous vanilla-JS UI and the full Python backend (`server.py`, `tools/`,
> `tests/`, `poi-data/`) live on the **`legacy-mvp`** branch, preserved as-is.

## Stack

- React 18 + TypeScript
- Vite 5
- React Router
- Plain CSS Modules + design tokens (CSS variables mirrored from Figma Foundations)

## Develop

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build
```

## Structure

```
src/
  styles/tokens.css     # Figma Foundations → CSS variables (colors, radius, type)
  styles/global.css     # reset + base type
  components/           # Button, Tag, StatTile, ProgressBar, Sidebar (+ NavItem)
  pages/                # Home (built), Placeholder (stub for the rest)
  App.tsx               # router + sidebar layout shell
```

## Redesign build-out status

- [x] Foundations tokens + core components
- [x] 01 · Home
- [ ] 02 · New run · 03 · Run results · 04 · Case inspector
- [ ] 05 · Compare · 06 · Datasets · 07 · Retrieval diagnostics
- [ ] 08 · States & appendix · dark mode

See `docs/redesign-brief.md` for the design brief.
