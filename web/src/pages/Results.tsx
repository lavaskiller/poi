import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Button from "../components/Button";
import StatTile from "../components/StatTile";
import CaseCard, { type CaseCardData } from "../components/CaseCard";
import {
  api,
  bestRun,
  formatDuration,
  photoUrl,
  type MatchRate,
  type Run,
  type RunDetail,
} from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./Results.module.css";

type FilterId = "all" | "wrong" | "abstain" | "error" | "related";

interface ResultsData {
  runs: Run[];
  selected: Run;
  detail: RunDetail;
  matchrate: MatchRate;
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
    if (!selected) throw new Error("no scored runs yet");
    const { run } = await api.run(selected.name, selected.version);
    return { runs, selected, detail: run, matchrate };
  }, [nameQ, versionQ]);

  const [filter, setFilter] = useState<FilterId>("all");

  const derived = useMemo(() => {
    if (state.status !== "ready") return null;
    const { detail, matchrate, selected, runs } = state.data;
    const cases = detail.cases ?? [];
    const eligible = cases.length || selected.n_eligible || 0;
    const correct =
      selected.correct ?? cases.filter((c) => c.correct).length;
    const failures = cases.filter((c) => !c.correct);
    const byKind = (kind: string) => failures.filter((c) => c.match_kind === kind);

    const filtered =
      filter === "all"
        ? failures
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

    const gallery = filtered.slice(0, 12).map((c) => ({
      dataset: c.dataset,
      photo: c.photo,
      card: {
        band: c.prediction ? "warning" : "danger",
        filename: c.photo,
        image: photoUrl(c.dataset, c.photo, { thumb: true, w: 360 }),
        title: `${c.dataset}${c.context?.category ? " · " + c.context.category : ""}${c.match_kind ? " · " + c.match_kind : ""}`,
        predicted: `✗ ${c.prediction || "— no prediction"}`,
        predictedTone: "danger" as const,
        groundTruth: `✓ ${c.gt}`,
        groundTruthTone: "success" as const,
        gtSrc: "src · mapkit",
      } satisfies CaseCardData,
    }));

    const scored = runs
      .filter((r) => typeof r.accuracy_pct === "number")
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

    return {
      cases,
      eligible,
      correct,
      failures,
      filtered,
      gallery,
      scored,
      matchrate,
      selected,
      detail,
      wrongN: failures.filter(
        (c) => c.match_kind === "wrong" || (!c.match_kind && !!c.prediction),
      ).length,
      abstainN: byKind("abstain").length,
      errorN: byKind("error").length,
      relatedN: failures.filter((c) =>
        ["related", "related_credit", "alias"].includes(c.match_kind),
      ).length,
    };
  }, [state, filter]);

  if (state.status === "loading") {
    return <main className={styles.main}>Loading run results…</main>;
  }
  if (state.status === "error") {
    return <main className={styles.main}>Couldn’t load results — {state.error.message}</main>;
  }
  if (!derived) return null;

  const {
    selected,
    detail,
    matchrate,
    eligible,
    correct,
    failures,
    filtered,
    gallery,
    scored,
    wrongN,
    abstainN,
    errorN,
    relatedN,
  } = derived;
  const canonical = selected.accuracy_canonical_pct;
  const isBest =
    bestRun(state.data.runs)?.name === selected.name &&
    bestRun(state.data.runs)?.version === selected.version;

  const FILTERS: { id: FilterId; label: string; dot?: string }[] = [
    { id: "all", label: `All failures · ${failures.length}` },
    { id: "wrong", label: `Wrong pick · ${wrongN}`, dot: "var(--warning-fg)" },
    { id: "related", label: `Related / alias · ${relatedN}`, dot: "var(--accent-default)" },
    { id: "abstain", label: `Abstain · ${abstainN}`, dot: "var(--text-tertiary)" },
    { id: "error", label: `Error · ${errorN}`, dot: "var(--danger-fg)" },
  ];

  const onSelectRun = (value: string) => {
    const [name, ver] = value.split("::");
    setParams({ name, version: ver });
  };

  return (
    <main className={styles.main}>
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
            {eligible.toLocaleString()} eligible cases · {detail.mode || selected.mode || "exact"}{" "}
            match · {formatDuration(selected.duration_ms)} runtime · scope{" "}
            {selected.scope || "all"}
          </p>
        </div>
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
                {r.name} · v{r.version} · {r.accuracy_pct}%
              </option>
            ))}
          </select>
        </label>
        <Link
          to={`/compare?b=${encodeURIComponent(selected.name)}&bv=${selected.version}`}
          style={{ textDecoration: "none" }}
          title="Open Compare with this run pre-selected as B"
        >
          <Button kind="secondary">Compare with…</Button>
        </Link>
        <Link to="/retrieval" style={{ textDecoration: "none" }}>
          <Button kind="secondary">Retrieval ceiling</Button>
        </Link>
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
        <span className={styles.sortNote}>
          1–{Math.min(12, filtered.length)} of {filtered.length}
        </span>
      </div>

      <div className={styles.gallery}>
        {gallery.map((g) => (
          <Link
            key={`${g.dataset}/${g.photo}`}
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
