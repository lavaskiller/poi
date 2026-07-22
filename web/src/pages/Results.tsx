import { Link } from "react-router-dom";
import Button from "../components/Button";
import StatTile from "../components/StatTile";
import CaseCard, { type CaseCardData } from "../components/CaseCard";
import { api, type MatchRate, type Run, type RunDetail } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./Results.module.css";

interface ResultsData {
  best: Run;
  detail: RunDetail;
  matchrate: MatchRate;
}

export default function Results() {
  const state = useAsync<ResultsData>(async () => {
    const [{ runs }, matchrate] = await Promise.all([api.runs(), api.matchrate()]);
    const scored = runs.filter((r) => typeof r.accuracy_pct === "number");
    const best = scored.reduce<Run | null>(
      (b, r) => (b === null || (r.accuracy_pct ?? 0) > (b.accuracy_pct ?? 0) ? r : b),
      null,
    );
    if (!best) throw new Error("no scored runs yet");
    const { run } = await api.run(best.name, best.version);
    return { best, detail: run, matchrate };
  }, []);

  if (state.status === "loading") {
    return <main className={styles.main}>Loading run results…</main>;
  }
  if (state.status === "error") {
    return <main className={styles.main}>Couldn’t load results — {state.error.message}</main>;
  }

  const { best, detail, matchrate } = state.data;
  const cases = detail.cases ?? [];
  const eligible = cases.length;
  const correct = cases.filter((c) => c.correct).length;
  const failures = cases.filter((c) => !c.correct);
  const canonical = best.accuracy_canonical_pct;

  const gallery = failures.slice(0, 9).map((c) => ({
    dataset: c.dataset,
    photo: c.photo,
    card: {
      band: c.prediction ? "warning" : "danger",
      filename: c.photo,
      image: `/api/poi-case-photo?dataset=${encodeURIComponent(c.dataset)}&photo=${encodeURIComponent(c.photo)}`,
      title: `${c.dataset}${c.context?.category ? " · " + c.context.category : ""}`,
      predicted: `✗ ${c.prediction || "— no candidate matched"}`,
      predictedTone: "danger",
      groundTruth: `✓ ${c.gt}`,
      groundTruthTone: "success",
      gtSrc: "src · mapkit",
    } as CaseCardData,
  }));

  const FILTERS = [
    { label: `All failures · ${failures.length}`, active: true },
    { label: `Selection miss · ${matchrate.selection_failure}`, dot: "var(--warning-fg)" },
    { label: `Retrieval miss · ${matchrate.search_failure}`, dot: "var(--danger-fg)" },
    { label: `Policy / non-POI · ${matchrate.counts.excluded_non_poi ?? 0}`, dot: "var(--policy-fg)" },
    { label: `No GT · ${matchrate.counts.gt_no_gt ?? 0}`, dot: "var(--text-tertiary)" },
  ];

  return (
    <main className={styles.main}>
      {/* header */}
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Run result</p>
          <div className={styles.titleRow}>
            <h1 className={styles.h1}>
              {best.name} · v{best.version}
            </h1>
            <span className={styles.bestPill}>BEST YET</span>
          </div>
          <p className={styles.sub}>
            {eligible.toLocaleString()} eligible cases · {detail.mode || "exact"} match ·{" "}
            {best.runtime || "—"} runtime
          </p>
        </div>
        <Button kind="secondary">Compare with…</Button>
        <Button kind="secondary">Export CSV</Button>
      </header>

      {/* metrics */}
      <div className={styles.metrics}>
        <StatTile
          label="Selection accuracy"
          value={`✓ ${best.accuracy_pct}%`}
          valueTone="success"
          note={`${correct}/${eligible}${canonical != null ? ` · canonical ${canonical}%` : ""}`}
        />
        <StatTile
          label="Selection miss"
          value={String(matchrate.selection_failure)}
          valueTone="warning"
          note="GT in candidates, wrong pick"
        />
        <StatTile
          label="Retrieval miss"
          value={`✗ ${matchrate.search_failure}`}
          valueTone="danger"
          note="GT absent from candidates"
        />
        <StatTile
          label="Canonical score"
          value={canonical != null ? `${canonical}%` : "—"}
          note="accepts similar-name matches"
        />
      </div>

      {/* failure filters */}
      <div className={styles.filters}>
        <span className={`sectionLabel ${styles.filtersLabel}`}>Failures</span>
        {FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            className={`${styles.filter} ${f.active ? styles.filterOn : ""}`}
          >
            {f.dot && <span className={styles.dot} style={{ background: f.dot }} />}
            {f.label}
          </button>
        ))}
        <span className={styles.filtersSpacer} />
        <span className={styles.sortNote}>
          1–{Math.min(9, failures.length)} of {failures.length}
        </span>
      </div>

      {/* gallery */}
      <div className={styles.gallery}>
        {gallery.map((g, i) => (
          <Link
            key={`${g.photo}-${i}`}
            to={`/case?dataset=${encodeURIComponent(g.dataset)}&photo=${encodeURIComponent(g.photo)}`}
            className={styles.cardLink}
          >
            <CaseCard {...g.card} />
          </Link>
        ))}
      </div>
    </main>
  );
}
