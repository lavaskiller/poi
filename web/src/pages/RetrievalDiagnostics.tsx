import { useMemo, useState } from "react";
import StatTile from "../components/StatTile";
import {
  api,
  bestRun,
  type MatchRate,
  type OverviewSource,
  type Run,
} from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./RetrievalDiagnostics.module.css";

function pct1(rate: number | undefined, n: number | undefined, d: number | undefined): string {
  if (rate != null && Number.isFinite(rate)) return `${(rate * 100).toFixed(1)}%`;
  if (n != null && d != null && d > 0) return `${((100 * n) / d).toFixed(1)}%`;
  return "—";
}

function pctNum(rate: number | undefined, n: number | undefined, d: number | undefined): number {
  if (rate != null && Number.isFinite(rate)) return rate * 100;
  if (n != null && d != null && d > 0) return (100 * n) / d;
  return 0;
}

/** Chart N grid — only exact candidate_limit == N runs can fill model bars. */
const TOP_NS = [1, 3, 5, 10, 20, 50] as const;

// chart geometry: line = retrieval ceiling; bars = best model @ exact k
const W = 580;
const H = 260;
const X0 = 40;
const X1 = 540;
const Y_TOP = 44; // room for coverage % + model labels above the line
const Y_BOT = 210;

interface TopNPoint {
  n: number;
  label: string;
  /** MapKit retrieval ceiling (always drawn on the line). */
  coverage: number;
  /** Best model when candidate_limit === n only; null → no bar. */
  modelName: string | null;
  modelVer: number | null;
  accuracy: number | null;
}

function shortModelName(name: string, max = 13): string {
  if (name.length <= max) return name;
  return `${name.slice(0, max - 1)}…`;
}

/**
 * Line = MapKit GT-in-top-N ceiling (matchrate).
 * Bars = best selection accuracy among runs with candidate_limit === N only.
 * Missing exact-k runs → no bar / no model label at that N.
 */
function CoverageAndModelChart({
  points,
  yMin,
}: {
  points: TopNPoint[];
  yMin: number;
}) {
  const yFor = (v: number) => Y_BOT - ((v - yMin) / (100 - yMin)) * (Y_BOT - Y_TOP);
  const xFor = (i: number) =>
    points.length <= 1 ? (X0 + X1) / 2 : X0 + (i * (X1 - X0)) / (points.length - 1);
  const slot = points.length > 0 ? (X1 - X0) / Math.max(1, points.length - 1) : 40;
  const barW = Math.min(36, slot * 0.42);
  const line = points.map((p, i) => `${xFor(i)},${yFor(p.coverage)}`).join(" ");
  const grid = [yMin, ...[60, 70, 80, 90, 100].filter((g) => g > yMin)];

  return (
    <svg
      className={styles.chart}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="MapKit top-N coverage line and best model bars at exact k"
    >
      {grid.map((g) => (
        <g key={g}>
          <line x1={X0} x2={X1} y1={yFor(g)} y2={yFor(g)} stroke="var(--bg-subtle)" strokeWidth={1} />
          <text x={14} y={yFor(g) + 3} className={styles.axisText}>
            {g}
          </text>
        </g>
      ))}

      {/* model accuracy bars (only where candidate_limit === N) */}
      {points.map((p, i) => {
        if (p.accuracy == null) return null;
        const cx = xFor(i);
        const yAcc = yFor(p.accuracy);
        const h = Math.max(0, Y_BOT - yAcc);
        const modelLabel = p.modelName
          ? `${shortModelName(p.modelName)}${p.modelVer != null ? ` v${p.modelVer}` : ""}`
          : "";
        return (
          <g key={`bar-${p.label}`}>
            <rect
              x={cx - barW / 2}
              y={yAcc}
              width={barW}
              height={h}
              rx={3}
              fill="var(--accent-default)"
              opacity={0.28}
            />
            {/* model name on top of the bar */}
            {modelLabel && (
              <text x={cx} y={yAcc - 5} textAnchor="middle" className={styles.barModel}>
                {modelLabel}
              </text>
            )}
          </g>
        );
      })}

      {/* coverage line (always) */}
      {points.length > 0 && (
        <polyline points={line} fill="none" stroke="var(--accent-default)" strokeWidth={2.25} />
      )}
      {points.map((p, i) => {
        const cx = xFor(i);
        const cy = yFor(p.coverage);
        return (
          <g key={`pt-${p.label}`}>
            <circle cx={cx} cy={cy} r={4} fill="var(--accent-default)" />
            {/* coverage % sits on the line */}
            <text x={cx} y={cy - 8} textAnchor="middle" className={styles.linePct}>
              {Number.isFinite(p.coverage) ? `${Math.round(p.coverage)}%` : "—"}
            </text>
            <text x={cx} y={H - 12} textAnchor="middle" className={styles.axisText}>
              {p.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

interface DatasetSummary {
  key: string;
  label: string;
  count: number;
  matchrate: MatchRate;
}

interface Data {
  sources: OverviewSource[];
  /** matchrate for the active filter */
  matchrate: MatchRate;
  /** per-dataset matchrates (for the breakdown strip when viewing All) */
  byDataset: DatasetSummary[];
  runs: Run[];
}

function accuracyForDataset(run: Run, dataset: string): number | null {
  if (dataset === "all") {
    return typeof run.accuracy_pct === "number" ? run.accuracy_pct : null;
  }
  const bd = run.metrics?.by_dataset?.[dataset];
  if (bd) {
    if (typeof bd.accuracy_pct === "number") return bd.accuracy_pct;
    if (typeof bd.accuracy === "number") return Math.round(bd.accuracy * 100);
  }
  // scope-limited runs that only cover this dataset
  if (run.scope === dataset && typeof run.accuracy_pct === "number") return run.accuracy_pct;
  return null;
}

function latestRunsByName(runs: Run[]): Run[] {
  const latestByName = new Map<string, Run>();
  for (const r of runs) {
    if (typeof r.accuracy_pct !== "number") continue;
    const prev = latestByName.get(r.name);
    if (!prev || r.version > prev.version) latestByName.set(r.name, r);
  }
  return [...latestByName.values()];
}

/**
 * Best model for chart N: **exact** ``candidate_limit === n`` only.
 * No ≥ N, no null fallback — missing k → no bar.
 *
 * Storage contract: accuracy_pct is the selection score measured when nearby
 * was truncated to that k (see run metrics score_k / accuracy_at_k).
 */
function bestModelAtExactN(
  latest: Run[],
  dataset: string,
  n: number,
): { run: Run; pct: number } | null {
  let best: { run: Run; pct: number } | null = null;
  for (const r of latest) {
    if (r.candidate_limit !== n) continue;
    const pct = accuracyForDataset(r, dataset);
    if (pct == null) continue;
    if (!best || pct > best.pct) best = { run: r, pct };
  }
  return best;
}

export default function RetrievalDiagnostics() {
  const [dataset, setDataset] = useState<string>("all");

  const state = useAsync<Data>(async () => {
    const [overview, { runs }] = await Promise.all([api.overview(), api.runs()]);
    const sources = overview.sources ?? [];
    const matchrate = await api.matchrate(dataset);
    const byDataset: DatasetSummary[] = await Promise.all(
      sources.map(async (s) => ({
        key: s.key,
        label: s.label || s.key,
        count: s.count,
        matchrate: await api.matchrate(s.key),
      })),
    );
    return { sources, matchrate, byDataset, runs };
  }, [dataset]);

  const filterOptions = useMemo(() => {
    if (state.status !== "ready") return [{ key: "all", label: "All datasets", count: 0 }];
    const total = state.data.sources.reduce((s, x) => s + x.count, 0);
    return [
      { key: "all", label: "All datasets", count: total },
      ...state.data.sources.map((s) => ({
        key: s.key,
        label: s.label ? `${s.key}` : s.key,
        count: s.count,
      })),
    ];
  }, [state]);

  if (state.status === "loading") {
    return <main className={styles.main}>Loading retrieval diagnostics…</main>;
  }
  if (state.status === "error") {
    return <main className={styles.main}>Couldn’t load diagnostics — {state.error.message}</main>;
  }

  const { matchrate: m, runs, byDataset } = state.data;
  const n = m.n ?? m.eligible ?? m.evaluated ?? 0;
  const scopeLabel = dataset === "all" ? "all datasets" : dataset;

  const tiles = [
    { label: "Rank 1", value: pct1(m.rank1_rate, m.rank1, n), note: "GT is the first candidate" },
    { label: "Top 3", value: pct1(m.top3_rate, m.top3, n), note: "GT within first 3" },
    { label: "Top 5", value: pct1(m.top5_rate, m.top5, n), note: "GT within first 5" },
    { label: "Top 10", value: pct1(m.top10_rate, m.top10, n), note: "GT within first 10" },
    { label: "Top 50", value: pct1(m.top50_rate, m.top50, n), note: "GT anywhere in list" },
    {
      label: "Miss",
      value: pct1(m.miss_rate, m.miss ?? m.search_failure, n),
      note: "GT absent — hard ceiling",
      danger: true,
    },
  ];

  const coverageByN: Record<number, number> = {
    1: pctNum(m.rank1_rate, m.rank1, n),
    3: pctNum(m.top3_rate, m.top3, n),
    5: pctNum(m.top5_rate, m.top5, n),
    10: pctNum(m.top10_rate, m.top10, n),
    20: pctNum(m.top20_rate, m.top20, n),
    50: pctNum(m.top50_rate, m.top50, n),
  };

  // Latest version per run name; accuracy scoped when a dataset is selected
  const latest = latestRunsByName(runs);
  const algos = latest
    .map((a) => ({ run: a, pct: accuracyForDataset(a, dataset) }))
    .filter((a) => a.pct != null)
    .sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0));
  const best =
    dataset === "all"
      ? bestRun(runs)
      : algos[0]?.run ?? null;
  const ceiling = coverageByN[50] ?? 0;

  const topNPoints: TopNPoint[] = TOP_NS.map((depth) => {
    const win = bestModelAtExactN(latest, dataset, depth);
    return {
      n: depth,
      label: `N=${depth}`,
      coverage: coverageByN[depth] ?? 0,
      modelName: win?.run.name ?? null,
      modelVer: win?.run.version ?? null,
      accuracy: win?.pct ?? null,
    };
  });
  const covVals = topNPoints.map((p) => p.coverage).filter((v) => Number.isFinite(v));
  const yMin = Math.max(0, Math.floor((Math.min(...covVals, 40) - 5) / 5) * 5);

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <p className={`sectionLabel ${styles.kicker}`}>Results · Retrieval diagnostics</p>
        <h1 className={styles.h1}>Could the provider even see the answer?</h1>
        <p className={styles.sub}>
          MapKit candidate coverage on the {n.toLocaleString()} eligible cases
          {dataset === "all" ? "" : ` in ${dataset}`} (GT-canonical, provider-scored
          {m.overrides_applied
            ? ` · ${m.overrides_applied} Reconcile override${m.overrides_applied === 1 ? "" : "s"} applied`
            : ""}
          ). Separate from algorithm selection accuracy — if GT never appears, no algorithm can pick
          it. Non-MapKit holdouts: {m.excluded_non_mapkit ?? m.counts?.excluded_non_mapkit ?? "—"}.
        </p>
      </div>

      {/* dataset filter */}
      <div className={styles.filters} role="tablist" aria-label="Dataset filter">
        <span className={`sectionLabel ${styles.filtersLabel}`}>Dataset</span>
        {filterOptions.map((opt) => {
          const active = dataset === opt.key;
          const elig =
            opt.key === "all"
              ? n
              : byDataset.find((d) => d.key === opt.key)?.matchrate.n ??
                byDataset.find((d) => d.key === opt.key)?.matchrate.eligible;
          return (
            <button
              key={opt.key}
              type="button"
              role="tab"
              aria-selected={active}
              className={`${styles.filter} ${active ? styles.filterOn : ""}`}
              onClick={() => setDataset(opt.key)}
              title={
                opt.key === "all"
                  ? `All datasets · ${opt.count} rows`
                  : `${opt.key} · ${opt.count} rows` +
                    (elig != null ? ` · ${elig} eligible` : "")
              }
            >
              <span className={styles.filterName}>
                {opt.key === "all" ? "All" : opt.key}
              </span>
              <span className={styles.filterMeta}>
                {opt.count.toLocaleString()}
                {elig != null && opt.key !== "all" ? ` · ${elig}` : ""}
              </span>
            </button>
          );
        })}
      </div>

      {/* per-dataset snapshot when viewing all */}
      {dataset === "all" && byDataset.length > 0 && (
        <div className={styles.dsTable}>
          <div className={`${styles.dsRow} ${styles.dsHead}`}>
            <span>Dataset</span>
            <span>Rows</span>
            <span>Eligible</span>
            <span>Rank1</span>
            <span>Top5</span>
            <span>Top50</span>
            <span>Miss</span>
          </div>
          {byDataset.map((d) => {
            const mr = d.matchrate;
            const en = mr.n ?? mr.eligible ?? 0;
            return (
              <button
                key={d.key}
                type="button"
                className={styles.dsRow}
                onClick={() => setDataset(d.key)}
                title={`Filter to ${d.key}`}
              >
                <span className={styles.dsName}>{d.key}</span>
                <span className={styles.dsMono}>{d.count.toLocaleString()}</span>
                <span className={styles.dsMono}>{en.toLocaleString()}</span>
                <span className={styles.dsMono}>{pct1(mr.rank1_rate, mr.rank1, en)}</span>
                <span className={styles.dsMono}>{pct1(mr.top5_rate, mr.top5, en)}</span>
                <span className={styles.dsMono}>{pct1(mr.top50_rate, mr.top50, en)}</span>
                <span className={styles.dsMono}>{pct1(mr.miss_rate, mr.miss ?? mr.search_failure, en)}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className={styles.tiles}>
        {tiles.map((t) => (
          <StatTile
            key={t.label}
            label={t.label}
            value={t.value}
            valueTone={t.danger ? "danger" : "primary"}
            note={t.note}
            size="md"
          />
        ))}
      </div>

      <div className={styles.charts}>
        <div className={styles.card}>
          <p className={styles.miniLabel}>
            Top-N ceiling (line) · best model at exact k (bars) · {scopeLabel}
          </p>
          <CoverageAndModelChart points={topNPoints} yMin={yMin} />
        </div>

        <div className={styles.algoCard}>
          <p className={styles.miniLabel}>
            Selection accuracy by algorithm
            {dataset !== "all" ? ` · ${dataset}` : ""}
          </p>
          {algos.length === 0 && (
            <p className={styles.captionSmall}>
              {dataset === "all"
                ? "No scored runs yet."
                : `No per-dataset metrics for ${dataset} on stored runs (try All, or a run scoped to this dataset).`}
            </p>
          )}
          {algos.map(({ run: a, pct }) => {
            const isBest = best && a.name === best.name && a.version === best.version;
            const value = pct ?? 0;
            return (
              <div key={`${a.name}-${a.version}`} className={styles.algoRow}>
                <div className={styles.algoHead}>
                  <span className={isBest ? styles.algoNameBest : styles.algoName}>
                    {a.name} · v{a.version}
                  </span>
                  <span
                    className={styles.algoPct}
                    style={{ color: isBest ? "var(--accent-default)" : "var(--text-secondary)" }}
                  >
                    {value}%
                  </span>
                </div>
                <div className={styles.algoTrack}>
                  <div
                    className={styles.algoFill}
                    style={{
                      width: `${Math.min(100, value)}%`,
                      background: isBest ? "var(--accent-default)" : "var(--text-tertiary)",
                    }}
                  />
                </div>
              </div>
            );
          })}
          <p className={styles.captionSmall}>
            Latest version per run name · strict scoring · retrieval ceiling {ceiling.toFixed(1)}%
            at N=50 · scope {scopeLabel}
          </p>
        </div>
      </div>
    </main>
  );
}
