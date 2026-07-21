import StatTile from "../components/StatTile";
import styles from "./RetrievalDiagnostics.module.css";

const TILES = [
  { label: "Rank 1", value: "58.2%", note: "GT is the first candidate" },
  { label: "Top 3", value: "71.4%", note: "GT within first 3" },
  { label: "Top 5", value: "76.9%", note: "GT within first 5" },
  { label: "Top 10", value: "82.3%", note: "GT within first 10" },
  { label: "Top 50", value: "91.0%", note: "GT anywhere in list" },
  { label: "Miss", value: "9.0%", note: "GT absent — hard ceiling", danger: true },
];

const CURVE = [
  { n: "N=1", cov: 58.2 },
  { n: "N=3", cov: 71.4 },
  { n: "N=5", cov: 76.9 },
  { n: "N=10", cov: 82.3 },
  { n: "N=20", cov: 86.0 },
  { n: "N=50", cov: 91.0 },
];

const ALGOS = [
  { name: "heuristic-v2 · v7", pct: 78.4, best: true },
  { name: "heuristic-v2 · v6", pct: 76.3, best: false },
  { name: "gpt-rerank · v2", pct: 71, best: false },
  { name: "baseline-nearest · v3", pct: 52.1, best: false },
];

// chart geometry
const W = 580;
const H = 250;
const X0 = 40;
const X1 = 540;
const Y_TOP = 20; // = 100%
const Y_BOT = 220; // = 55%
const yFor = (cov: number) => Y_BOT - ((cov - 55) / (100 - 55)) * (Y_BOT - Y_TOP);
const xFor = (i: number) => X0 + (i * (X1 - X0)) / (CURVE.length - 1);

function CoverageChart() {
  const line = CURVE.map((p, i) => `${xFor(i)},${yFor(p.cov)}`).join(" ");
  return (
    <svg className={styles.chart} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="GT coverage in top-N">
      {[60, 70, 80, 90, 100].map((g) => (
        <g key={g}>
          <line x1={X0} x2={X1} y1={yFor(g)} y2={yFor(g)} stroke="var(--bg-subtle)" strokeWidth={1} />
          <text x={16} y={yFor(g) + 3} className={styles.axisText}>
            {g}
          </text>
        </g>
      ))}
      <polyline points={line} fill="none" stroke="var(--accent-default)" strokeWidth={2} />
      {CURVE.map((p, i) => (
        <g key={p.n}>
          <circle cx={xFor(i)} cy={yFor(p.cov)} r={4} fill="var(--accent-default)" />
          <text x={xFor(i)} y={H - 8} textAnchor="middle" className={styles.axisText}>
            {p.n}
          </text>
        </g>
      ))}
    </svg>
  );
}

export default function RetrievalDiagnostics() {
  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <p className={`sectionLabel ${styles.kicker}`}>Results · Retrieval diagnostics</p>
        <h1 className={styles.h1}>Could the provider even see the answer?</h1>
        <p className={styles.sub}>
          Coverage of the candidate provider (MapKit) — separate from algorithm accuracy. If GT never
          appears in the candidates, no algorithm can pick it: this is the ceiling.
        </p>
      </div>

      <div className={styles.tiles}>
        {TILES.map((t) => (
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
          <p className={styles.miniLabel}>Provider coverage — GT in top-N</p>
          <CoverageChart />
          <p className={styles.caption}>
            Retrieval only — whether the provider returned the GT place at all. A coverage ceiling,
            not algorithm accuracy.
          </p>
        </div>

        <div className={styles.algoCard}>
          <p className={styles.miniLabel}>Selection accuracy by algorithm</p>
          {ALGOS.map((a) => (
            <div key={a.name} className={styles.algoRow}>
              <div className={styles.algoHead}>
                <span className={a.best ? styles.algoNameBest : styles.algoName}>{a.name}</span>
                <span
                  className={styles.algoPct}
                  style={{ color: a.best ? "var(--accent-default)" : "var(--text-secondary)" }}
                >
                  {a.pct}%
                </span>
              </div>
              <div className={styles.algoTrack}>
                <div
                  className={styles.algoFill}
                  style={{
                    width: `${a.pct}%`,
                    background: a.best ? "var(--accent-default)" : "var(--text-tertiary)",
                  }}
                />
              </div>
            </div>
          ))}
          <p className={styles.captionSmall}>
            Latest version per run name · strict scoring · retrieval ceiling 91.0% at N=50
          </p>
        </div>
      </div>
    </main>
  );
}
