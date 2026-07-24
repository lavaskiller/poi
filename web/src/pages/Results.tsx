import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Button from "../components/Button";
import StatTile from "../components/StatTile";
import CaseCard, { type CaseCardData } from "../components/CaseCard";
import {
  api,
  bestRun,
  downloadText,
  formatDuration,
  photoUrl,
  toCsv,
  type MatchRate,
  type Run,
  type RunDetail,
} from "../lib/api";
import { notifyDataChanged, useRefreshOnFocus } from "../lib/dataRefresh";
import { useAsync } from "../lib/useAsync";
import styles from "./Results.module.css";

type FilterId = "all" | "wrong" | "abstain" | "error" | "related";

/** Failure gallery page size — keep cards large; page with Prev/Next. */
const GALLERY_PAGE_SIZE = 12;

interface ResultsData {
  runs: Run[];
  selected: Run | null;
  detail: RunDetail | null;
  matchrate: MatchRate;
}

function runsSignature(runs: Run[]): string {
  return runs
    .map((run) =>
      [
        run.name,
        run.version,
        run.created_at || "",
        run.status || "done",
        run.n_completed ?? run.correct ?? "",
        run.accuracy_pct ?? "",
        run.progress?.done ?? "",
      ].join(":"),
    )
    .sort()
    .join("|");
}

/** Reconcile overrides change ceiling stats without new runs. */
function matchrateSignature(m: MatchRate): string {
  return [
    m.n ?? m.eligible ?? "",
    m.rank1 ?? "",
    m.miss ?? m.search_failure ?? "",
    m.overrides_applied ?? "",
    m.excluded_non_mapkit ?? m.counts?.excluded_non_mapkit ?? "",
  ].join(":");
}

export default function Results() {
  const [params, setParams] = useSearchParams();
  const nameQ = params.get("name") || "";
  const versionQ = params.get("version");

  const state = useAsync<ResultsData>(async () => {
    const [{ runs }, matchrate] = await Promise.all([api.runs(), api.matchrate()]);
    let selected: Run | null = null;
    if (nameQ && versionQ) {
      selected =
        runs.find((r) => r.name === nameQ && r.version === Number(versionQ)) ?? null;
    }
    if (!selected) selected = bestRun(runs);
    if (!selected) return { runs, selected: null, detail: null, matchrate };
    const { run } = await api.run(selected.name, selected.version);
    return { runs, selected, detail: run, matchrate };
  }, [nameQ, versionQ]);
  useRefreshOnFocus(state.softReload);

  const runSig =
    state.status === "ready" ? runsSignature(state.data.runs) : "";
  const mrSig =
    state.status === "ready" ? matchrateSignature(state.data.matchrate) : "";

  const selectedLive =
    state.status === "ready" &&
    (state.data.selected?.status === "running" ||
      state.data.detail?.status === "running");

  // Poll faster while a live run is streaming cases; slower otherwise.
  useEffect(() => {
    if (state.status !== "ready") return;
    const softReload = state.softReload;
    const ms = selectedLive ? 800 : 3000;
    const timer = window.setInterval(() => {
      void Promise.all([api.runs(), api.matchrate()])
        .then(([{ runs }, matchrate]) => {
          const nextRuns = runsSignature(runs);
          const nextMr = matchrateSignature(matchrate);
          if (nextRuns !== runSig || nextMr !== mrSig) softReload();
        })
        .catch(() => {
          // Keep valid displayed data on a transient background polling failure.
        });
    }, ms);
    return () => window.clearInterval(timer);
  }, [state.status, runSig, mrSig, state.softReload, selectedLive]);

  const [filter, setFilter] = useState<FilterId>("all");
  const [page, setPage] = useState(0);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const galleryRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  // Filter / run change invalidates the current page window.
  useEffect(() => {
    setPage(0);
  }, [filter, nameQ, versionQ]);

  // After the new page paints, snap the scrollport so the first cards are
  // visible. Native lazy-load + mid-grid scroll made Prev/Next look broken.
  const pageScrollSkip = useRef(true);
  useEffect(() => {
    if (pageScrollSkip.current) {
      pageScrollSkip.current = false;
      return;
    }
    const main = mainRef.current;
    const gallery = galleryRef.current;
    if (!main || !gallery) return;
    // Walk offsetParents so we get gallery Y inside the scrolling main pane.
    let y = 0;
    let el: HTMLElement | null = gallery;
    while (el && el !== main) {
      y += el.offsetTop;
      el = el.offsetParent as HTMLElement | null;
    }
    main.scrollTo({ top: Math.max(0, y - 8), behavior: "auto" });
  }, [page, filter]);

  const derived = useMemo(() => {
    if (state.status !== "ready") return null;
    const { detail, matchrate, selected, runs } = state.data;
    if (!detail || !selected) return null;
    const cases = detail.cases ?? [];
    const isLive = (selected.status || detail.status) === "running";
    const isFailed = (selected.status || detail.status) === "failed";
    const eligible =
      selected.n_eligible ||
      detail.progress?.total ||
      cases.length ||
      0;
    const completed =
      selected.n_completed ??
      detail.progress?.done ??
      cases.length;
    const correct =
      selected.correct ?? cases.filter((c) => c.correct).length;
    const failures = cases.filter((c) => !c.correct);
    const byKind = (kind: string) => failures.filter((c) => c.match_kind === kind);

    // While streaming, "all" shows every finished case (correct + wrong) so the
    // gallery grows in real time; after done, keep the failure-focused default.
    const filtered =
      filter === "all"
        ? isLive || isFailed
          ? [...cases].reverse()
          : failures
        : filter === "wrong"
          ? failures.filter((c) =>
              ["wrong", "related", "related_credit", "alias"].includes(c.match_kind) ||
              (!c.match_kind && !!c.prediction),
            )
          : filter === "related"
            ? failures.filter((c) =>
                ["related", "related_credit", "alias"].includes(c.match_kind),
              )
            : byKind(filter);

    const pageCount = Math.max(1, Math.ceil(filtered.length / GALLERY_PAGE_SIZE));
    const safePage = Math.min(page, pageCount - 1);
    const start = safePage * GALLERY_PAGE_SIZE;
    const end = Math.min(start + GALLERY_PAGE_SIZE, filtered.length);

    const gallery = filtered.slice(start, end).map((c, i) => {
      const ok = !!c.correct;
      return {
        dataset: c.dataset,
        photo: c.photo,
        // Unique even when the run JSON lists the same photo twice.
        key: `${safePage}:${start + i}:${c.dataset}/${c.photo}:${c.correct}`,
        index: start + i + 1,
        card: {
          band: ok ? "success" : c.prediction ? "warning" : "danger",
          filename: c.photo,
          // Long-edge 720: sharp on retina cards (~350–500 CSS px) without full-res weight.
          image: photoUrl(c.dataset, c.photo, { thumb: true, w: 720 }),
          imageLoading: "eager" as const,
          title: `#${start + i + 1} · ${c.dataset}${c.context?.category ? " · " + c.context.category : ""}${c.match_kind ? " · " + c.match_kind : ""}`,
          predicted: ok
            ? `✓ ${c.prediction || "—"}`
            : `✗ ${c.prediction || "— no prediction"}`,
          predictedTone: ok ? ("success" as const) : ("danger" as const),
          groundTruth: `✓ ${c.gt}`,
          groundTruthTone: "success" as const,
          gtSrc: "src · mapkit",
        } satisfies CaseCardData,
      };
    });

    const scored = runs
      .filter((r) => typeof r.accuracy_pct === "number" || r.status === "running")
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

    return {
      cases,
      eligible,
      completed,
      correct,
      failures,
      filtered,
      gallery,
      pageCount,
      safePage,
      rangeStart: filtered.length === 0 ? 0 : start + 1,
      rangeEnd: end,
      scored,
      matchrate,
      selected,
      detail,
      isLive,
      isFailed,
      wrongN: failures.filter(
        (c) => c.match_kind === "wrong" || (!c.match_kind && !!c.prediction),
      ).length,
      abstainN: byKind("abstain").length,
      errorN: byKind("error").length,
      relatedN: failures.filter((c) =>
        ["related", "related_credit", "alias"].includes(c.match_kind),
      ).length,
    };
  }, [state, filter, page]);

  if (state.status === "loading") {
    return <main className={styles.main}>Loading run results…</main>;
  }
  if (state.status === "error") {
    return <main className={styles.main}>Couldn’t load results — {state.error.message}</main>;
  }
  if (!state.data.selected || !state.data.detail) {
    return (
      <main className={styles.main}>
        <p className={`sectionLabel ${styles.kicker}`}>Run results</p>
        <h1 className={styles.h1}>No scored runs yet</h1>
        <p className={styles.sub}>
          Create your first runnable evaluation. This page will update automatically when it finishes.
        </p>
        <Link to="/new-run" style={{ textDecoration: "none" }}>
          <Button>Create a run</Button>
        </Link>
      </main>
    );
  }
  if (!derived) return null;

  const {
    selected,
    detail,
    matchrate,
    eligible,
    completed,
    correct,
    cases,
    failures,
    filtered,
    gallery,
    pageCount,
    safePage,
    rangeStart,
    rangeEnd,
    scored,
    isLive,
    isFailed,
    wrongN,
    abstainN,
    errorN,
    relatedN,
  } = derived;
  const canonical = selected.accuracy_canonical_pct;
  const isBest =
    !isLive &&
    !isFailed &&
    bestRun(state.data.runs)?.name === selected.name &&
    bestRun(state.data.runs)?.version === selected.version;

  const FILTERS: { id: FilterId; label: string; dot?: string }[] = [
    {
      id: "all",
      label: isLive || isFailed
        ? `All finished · ${cases.length}`
        : `All failures · ${failures.length}`,
    },
    { id: "wrong", label: `Wrong pick · ${wrongN}`, dot: "var(--warning-fg)" },
    { id: "related", label: `Related / alias · ${relatedN}`, dot: "var(--accent-default)" },
    { id: "abstain", label: `Abstain · ${abstainN}`, dot: "var(--text-tertiary)" },
    { id: "error", label: `Error · ${errorN}`, dot: "var(--danger-fg)" },
  ];

  const onSelectRun = (value: string) => {
    const [name, ver] = value.split("::");
    setParams({ name, version: ver });
  };

  const onDeleteRun = async () => {
    if (!selected) return;
    if (
      !window.confirm(
        `Delete run ${selected.name} v${selected.version}? This cannot be undone.`,
      )
    ) {
      return;
    }
    setDeleteBusy(true);
    try {
      await api.deleteRun(selected.name, selected.version);
      notifyDataChanged("run");
      setParams({});
      state.reload();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleteBusy(false);
    }
  };

  const exportCsv = (mode: "all" | "failures" = "all") => {
    const source = mode === "failures" ? failures : cases;
    const headers = [
      "dataset",
      "photo",
      "gt",
      "prediction",
      "correct",
      "correct_canonical",
      "match_kind",
      "reason",
      "run_name",
      "run_version",
    ];
    const rows = source.map((c) => ({
      dataset: c.dataset,
      photo: c.photo,
      gt: c.gt,
      prediction: c.prediction,
      correct: c.correct ? "1" : "0",
      correct_canonical: c.correct_canonical ? "1" : "0",
      match_kind: c.match_kind || "",
      reason: c.reason || "",
      run_name: selected.name,
      run_version: selected.version,
    }));
    const body = toCsv(headers, rows);
    const slug = `${selected.name}__v${selected.version}${mode === "failures" ? "_failures" : ""}`;
    downloadText(`${slug}.csv`, body);
  };

  return (
    <main className={styles.main} ref={mainRef}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Run result</p>
          <div className={styles.titleRow}>
            <h1 className={styles.h1}>
              {selected.name} · v{selected.version}
            </h1>
            {isBest && <span className={styles.bestPill}>BEST YET</span>}
          </div>
          <p className={styles.sub}>
            {isLive
              ? `${completed.toLocaleString()} / ${eligible.toLocaleString()} cases scored live`
              : `${eligible.toLocaleString()} eligible cases`}{" "}
            · {detail.mode || selected.mode || "exact"} match ·{" "}
            {formatDuration(selected.duration_ms)} runtime · scope{" "}
            {selected.scope || "all"}
          </p>
          {isLive && (
            <p className={styles.sub} style={{ color: "var(--accent-default)" }}>
              Running… {completed}/{eligible}
              {selected.progress?.last_photo
                ? ` · last ${selected.progress.last_dataset || ""}/${selected.progress.last_photo}`
                : ""}
              {selected.accuracy_pct != null
                ? ` · ${selected.accuracy_pct}% so far`
                : ""}
            </p>
          )}
          {isFailed && (
            <p className={styles.sub} style={{ color: "var(--danger-fg)" }}>
              Failed after {completed}/{eligible} cases
              {selected.error || detail.error
                ? ` — ${selected.error || detail.error}`
                : ""}
            </p>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
          <span className={styles.sortNote}>Switch run</span>
          <select
            value={`${selected.name}::${selected.version}`}
            onChange={(e) => onSelectRun(e.target.value)}
            style={{
              padding: "6px 10px",
              borderRadius: 8,
              border: "1px solid var(--border-default)",
              background: "var(--bg-panel)",
              color: "var(--text-primary)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              maxWidth: 280,
            }}
          >
            {scored.map((r) => (
              <option key={`${r.name}-${r.version}`} value={`${r.name}::${r.version}`}>
                {r.name} · v{r.version}
                {r.status === "running"
                  ? ` · running ${r.progress?.done ?? r.n_completed ?? 0}/${r.n_eligible ?? "?"}`
                  : r.status === "failed"
                    ? " · failed"
                    : ` · ${r.accuracy_pct}%`}
              </option>
            ))}
          </select>
        </label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" }}>
        <Button
          kind="secondary"
          onClick={() => exportCsv("all")}
          title={`Export all ${cases.length} scored cases as CSV`}
        >
          Export CSV
        </Button>
        <Link
          to={`/compare?b=${encodeURIComponent(selected.name)}&bv=${selected.version}`}
          style={{ textDecoration: "none" }}
          title="Open Compare with this run pre-selected as B"
        >
          <Button kind="secondary" disabled={isLive}>
            Compare with…
          </Button>
        </Link>
        <Link to="/retrieval" style={{ textDecoration: "none" }}>
          <Button kind="secondary">Retrieval ceiling</Button>
        </Link>
        <Link
          to={`/new-run?from=${encodeURIComponent(selected.name)}&version=${selected.version}`}
          style={{ textDecoration: "none" }}
          title={
            selected.has_script === false
              ? "This run has no stored predict() script"
              : "Prefill New run with this script, params, k, and scope"
          }
          aria-disabled={selected.has_script === false}
          onClick={(e) => {
            if (selected.has_script === false) e.preventDefault();
          }}
        >
          <Button kind="secondary" disabled={selected.has_script === false || isLive}>
            Re-run →
          </Button>
        </Link>
        <Button
          kind="secondary"
          disabled={deleteBusy || isLive}
          onClick={() => void onDeleteRun()}
          title={isLive ? "Wait for the run to finish before deleting" : "Delete this run"}
        >
          {deleteBusy ? "Deleting…" : "Delete"}
        </Button>
        </div>
        </div>
      </header>

      <div className={styles.metrics}>
        <StatTile
          label="Selection accuracy"
          value={`✓ ${selected.accuracy_pct}%`}
          valueTone="success"
          note={`${correct}/${eligible}${canonical != null ? ` · canonical ${canonical}%` : ""}`}
        />
        <StatTile
          label="Failures (this run)"
          value={String(failures.length)}
          valueTone="warning"
          note="wrong + abstain + error on this run's cases"
        />
        <StatTile
          label="Retrieval miss (MapKit)"
          value={`✗ ${matchrate.search_failure ?? matchrate.miss ?? "—"}`}
          valueTone="danger"
          note={`Provider ceiling · ${matchrate.n ?? matchrate.eligible} eligible (not run-specific)`}
        />
        <StatTile
          label="Canonical score"
          value={canonical != null ? `${canonical}%` : "—"}
          note="accepts similar-name matches"
        />
      </div>

      <p className={styles.sortNote} style={{ marginTop: -4 }}>
        Retrieval miss above is the global MapKit match-rate diagnostic — not this algorithm&apos;s
        pick errors. Use{" "}
        <Link to="/retrieval">Retrieval diagnostics</Link> for top-N coverage.
      </p>

      <div className={styles.filters}>
        <span className={`sectionLabel ${styles.filtersLabel}`}>Failures</span>
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`${styles.filter} ${filter === f.id ? styles.filterOn : ""}`}
            onClick={() => setFilter(f.id)}
          >
            {f.dot && <span className={styles.dot} style={{ background: f.dot }} />}
            {f.label}
          </button>
        ))}
        <span className={styles.filtersSpacer} />
        <button
          type="button"
          className={styles.filter}
          onClick={() => exportCsv("failures")}
          title="Download currently filtered failures as CSV"
          disabled={filtered.length === 0}
        >
          Export failures
        </button>
        <div className={styles.pager}>
          <button
            type="button"
            className={styles.filter}
            onClick={() => setPage(Math.max(0, safePage - 1))}
            disabled={safePage <= 0 || filtered.length === 0}
            title="Previous 12 failures"
            aria-label="Previous page of failures"
          >
            ← Prev
          </button>
          <span className={styles.sortNote} aria-live="polite">
            {filtered.length === 0
              ? `0 of 0`
              : `${rangeStart}–${rangeEnd} of ${filtered.length}`}
            {pageCount > 1 ? ` · p${safePage + 1}/${pageCount}` : ""}
          </span>
          <button
            type="button"
            className={styles.filter}
            onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))}
            disabled={safePage >= pageCount - 1 || filtered.length === 0}
            title="Next 12 failures"
            aria-label="Next page of failures"
          >
            Next →
          </button>
        </div>
      </div>

      <div className={styles.gallery} ref={galleryRef} key={`gallery-p${safePage}-${filter}`}>
        {gallery.map((g) => (
          <Link
            key={g.key}
            to={`/case?dataset=${encodeURIComponent(g.dataset)}&photo=${encodeURIComponent(g.photo)}&run_name=${encodeURIComponent(selected.name)}&version=${selected.version}`}
            className={styles.cardLink}
          >
            <CaseCard {...g.card} />
          </Link>
        ))}
        {gallery.length === 0 && (
          <p className={styles.sub}>No failures in this filter.</p>
        )}
      </div>
    </main>
  );
}
