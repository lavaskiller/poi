# Agent rules — POI / PWE project

Rules learned from team feedback and past mistakes. Follow these whenever
working in this repo, especially for **Jira**, **Slack**, **git**, and
**shared docs**.

---

## 1. Team communication language = **English**

**Mistake (2026-07-20):** Jira comments on PWE-5 and PWE-12 were first posted in
**Korean**. The user corrected: *“소통 언어는 영어야”* (team language is English).

**Rule:**

| Audience | Language |
|---|---|
| Chat with the local user (this session) | User’s language is fine (often Korean) |
| **Jira** (issues, descriptions, comments, status notes) | **English only** |
| **Slack** / team DMs drafted for the team | **English only** |
| PR titles/bodies, GitHub issues for the shared team | **English only** |
| Code comments in the repo | Prefer English |

Team readers: Yoobin Seo, In Seo, Woohyuk Kang (and anyone on
`linkedspaces.atlassian.net`).

If you already posted a team-facing comment in Korean, **edit it to English**
immediately (do not leave Korean as the visible history for the team).

---

## 2. Jira (project **PWE** — POI wizard evaluator)

### 2.1 Where work lives

| Item | Value |
|---|---|
| Site | https://linkedspaces.atlassian.net |
| Project | **PWE** (“POI wizard evaluator”) |
| Tracking epic | **PWE-5** “EPIC for POI wizard enhancement” (hierarchy: 워크스트림) |
| cloudId | `93b69f57-862b-4ebe-8db6-a84a9692be56` |
| Child issues | Type **스토리** / 작업 / 버그 under parent **PWE-5** |

Stories under PWE-5 (PWE-6…11) were generated from **git commit history** to
track progress (same pattern as KS2-47). Prefer **git-derived** stories for
delivered/in-progress workstreams; re-parent orphan tickets under PWE-5 rather
than leaving them floating.

### 2.2 Comment / ticket content

- Write in **English** (see §1).
- Prefer **facts**: metrics, run names, snapshot IDs, file paths, before/after.
- Distinguish **strict** vs **canonical** accuracy when both exist; never claim
  only the higher number without saying which metric.
- Link artifacts the team can open: GitHub URLs, Jira keys, report paths.
  - Yoobin asked for **clickable GitHub links** on progress updates.
- **@mentions** only when the user explicitly asked to notify someone (e.g.
  “tag Yoobin and In Seo”). Do not mass-mention by default.
- Confirm with the user before bulk-creating issues or mass status changes if
  unsure; once authorized for a specific Jira update, still avoid drive-by
  tickets.

### 2.3 Status honesty

- Do not mark **Done** unless the ticket’s actual acceptance criteria are met.
- Coverage/ceiling issues (e.g. A · empty MapKit) are **not** “selector fixed”;
  say so clearly (PWE-1 lesson).
- If a local HTML/report is intentionally not in git (private photos), say
  **“kept out of git intentionally”** — never “not committed yet” (implies
  pending push).

---

## 3. Privacy / git safety

**Mistakes / near-misses:** diagnostic HTML embeds **real user photos**; daily
logs can include photo filenames + place names.

**Rules:**

1. **Never commit or push** user photos, base64-embedded photo HTML, raw eval
   CSVs under `poi-data/`, or other PII.
2. Respect `.gitignore` for photo-bearing reports (e.g. `poi-case-types.html`,
   `poi-case-types-thumbs/`, and listed analysis audits).
3. Before `git add -A` / push to a **shared** remote (e.g. In Seo’s
   `eval_poi_wizard`), scan staged content for private markers.
4. Do not force-push over someone else’s `main` without explicit approval.
5. In Jira, reference filenames only — do not paste photo binaries or base64.

---

## 4. Evaluation / accuracy claims

- Report **strict** and **canonical** separately when both are used.
- Canonical uses `poi-data/eval_label_relations.v1.jsonl` — do not inflate
  labels with forced related_credit to hit a metric goal (user feedback:
  keep label policy conservative).
- `predict()` must never read GT; only scoring may use labels.

---

## 5. Where longer process docs live

| Doc | Role |
|---|---|
| `docs/reports/daily/2026-07-20.md` §10–§11 | Loop-to-60% / 70% process + scoreboards |
| `docs/reports/daily/2026-07-20-todo.md` | Checklist + end-of-day scoreboard |
| `tools/SELECTORS.md` | Runner name map |
| This file (`AGENTS.md`) | Standing agent rules (language, Jira, privacy) |

---

## 6. Quick checklist before posting a Jira comment

- [ ] English?
- [ ] Mentions only if requested?
- [ ] Strict vs canonical clear?
- [ ] GitHub / artifact links where useful?
- [ ] No private photo content?
- [ ] Status claim matches evidence?
