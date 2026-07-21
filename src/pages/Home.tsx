import Button from "../components/Button";
import StatTile from "../components/StatTile";
import ProgressBar from "../components/ProgressBar";
import styles from "./Home.module.css";

const TREND = [
  { label: "v3", h: 70 },
  { label: "v4", h: 82 },
  { label: "v5", h: 89 },
  { label: "v6", h: 100 },
  { label: "v7", h: 105, active: true },
];

const OUTCOMES = [
  { key: "correct", w: 58.7, color: "var(--success-fg)", legend: "Correct 753 (58.6%)" },
  { key: "miss", w: 12.5, color: "var(--warning-fg)", legend: "Selection miss 161" },
  { key: "retrieval", w: 8.7, color: "var(--danger-fg)", legend: "Retrieval miss 112" },
  { key: "deferred", w: 20.1, color: "var(--bg-subtle)", legend: "No GT / deferred 258" },
];

const STEPS = [
  {
    title: "Inspect 89 new failures",
    body: "heuristic-v2 v7 · selection misses ranked by confidence",
    cta: "Open failures →",
  },
  {
    title: "Compare v7 against v6",
    body: "31 cases flipped between versions — see what changed",
    cta: "Open compare →",
  },
  {
    title: "Fill OCR for 112 rows",
    body: "Sparse signals reduce eligible rows and cap accuracy",
    cta: "Run enrichment →",
  },
];

type RunStatus = { text: string; tone: "done" | "running" };
interface RunRow {
  name: string;
  ver: string;
  datasets: string;
  accuracy: string | number; // number → progress (0–1)
  delta?: string;
  deltaTone?: "success" | "danger";
  status: RunStatus;
}

const RUNS: RunRow[] = [
  {
    name: "heuristic-v2",
    ver: "v7",
    datasets: "linkedspaces +2",
    accuracy: "78.4%",
    delta: "+2.1",
    deltaTone: "success",
    status: { text: "done", tone: "done" },
  },
  {
    name: "vlm-fewshot",
    ver: "v1",
    datasets: "linkedspaces",
    accuracy: 0.62,
    delta: "—",
    status: { text: "running · 64%", tone: "running" },
  },
  {
    name: "gpt-rerank",
    ver: "v2",
    datasets: "all datasets",
    accuracy: "71.0%",
    delta: "−0.4",
    deltaTone: "danger",
    status: { text: "done", tone: "done" },
  },
  {
    name: "baseline-nearest",
    ver: "v3",
    datasets: "all datasets",
    accuracy: "52.1%",
    delta: "—",
    status: { text: "done", tone: "done" },
  },
];

function StatusPill({ status }: { status: RunStatus }) {
  return <span className={`${styles.pill} ${styles[status.tone]}`}>{status.text}</span>;
}

export default function Home() {
  return (
    <main className={styles.main}>
      {/* header */}
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>POI Evaluation · Internal</p>
          <h1 className={styles.h1}>Selection accuracy is improving.</h1>
          <p className={styles.sub}>
            Last run 2 hours ago · data healthy · 1,284 cases across 3 datasets
          </p>
        </div>
        <Button kind="secondary">Upload data</Button>
        <Button kind="primary">▶&nbsp;&nbsp;New run</Button>
      </header>

      {/* hero */}
      <section className={styles.hero}>
        <div className={styles.heroTop}>
          <div className={styles.metric}>
            <p className={`sectionLabel ${styles.metricLabel}`}>Selection accuracy — best run</p>
            <div className={styles.metricRow}>
              <span className={styles.metricValue}>78.4%</span>
              <span className={`${styles.delta} ${styles.deltaUp}`}>▲ +2.1 pts vs v6</span>
            </div>
            <p className={styles.metricMeta}>
              heuristic-v2 · v7 · strict exact-match · eligible 1,032 / 1,284
            </p>
            <div className={styles.toggle}>
              <span className={`${styles.chip} ${styles.chipActive}`}>Strict · 78.4%</span>
              <span className={styles.chip}>Canonical · 84.9%</span>
            </div>
          </div>

          <div className={styles.trend}>
            <p className={`sectionLabel ${styles.trendLabel}`}>Version trend</p>
            <div className={styles.bars}>
              {TREND.map((b) => (
                <div key={b.label} className={styles.bar}>
                  <div
                    className={styles.barFill}
                    style={{
                      height: b.h,
                      background: b.active ? "var(--accent-default)" : "var(--bg-subtle)",
                    }}
                  />
                  <span
                    className={styles.barLabel}
                    style={{ color: b.active ? "var(--accent-default)" : "var(--text-tertiary)" }}
                  >
                    {b.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.outcomes}>
          <p className={`sectionLabel ${styles.outcomeLabel}`}>Outcome composition — 1,284 cases</p>
          <div className={styles.stack}>
            {OUTCOMES.map((o) => (
              <span key={o.key} style={{ width: `${o.w}%`, background: o.color }} />
            ))}
          </div>
          <div className={styles.legend}>
            {OUTCOMES.map((o) => (
              <span key={o.key} className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: o.color }} />
                {o.legend}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* data health */}
      <section className={styles.block}>
        <div className={styles.blockHead}>
          <p className={`sectionLabel ${styles.blockLabel}`}>Data health</p>
          <a className={styles.link} href="/datasets">
            Open datasets →
          </a>
        </div>
        <div className={styles.tiles}>
          <StatTile label="Total rows" value="1,284" note="across 3 datasets" />
          <StatTile label="GT coverage" value="81%" note="247 rows missing GT ⚠" noteTone="warning" />
          <StatTile label="Photo refs" value="92%" note="1,181 rows with photos" />
          <StatTile label="Countries" value="4" note="KR · US · CA · JP" />
        </div>
      </section>

      {/* next steps */}
      <section className={styles.block}>
        <p className={`sectionLabel ${styles.blockLabel}`}>What&apos;s next</p>
        <div className={styles.steps}>
          {STEPS.map((s) => (
            <div key={s.title} className={styles.step}>
              <p className={styles.stepTitle}>{s.title}</p>
              <p className={styles.stepBody}>{s.body}</p>
              <a className={styles.link} href="#">
                {s.cta}
              </a>
            </div>
          ))}
        </div>
      </section>

      {/* recent runs */}
      <section className={styles.block}>
        <p className={`sectionLabel ${styles.blockLabel}`}>Recent runs</p>
        <div className={styles.table}>
          <div className={`${styles.row} ${styles.headRow}`}>
            <div className={styles.cName}>Name</div>
            <div className={styles.cVer}>Ver</div>
            <div className={styles.cData}>Datasets</div>
            <div className={styles.cAcc}>Accuracy</div>
            <div className={styles.cDelta}>Δ</div>
            <div className={styles.cStatus}>Status</div>
          </div>
          {RUNS.map((r) => (
            <div key={r.name} className={styles.row}>
              <div className={`${styles.cName} mono ${styles.strong}`}>{r.name}</div>
              <div className={`${styles.cVer} mono ${styles.muted}`}>{r.ver}</div>
              <div className={styles.cData}>{r.datasets}</div>
              <div className={styles.cAcc}>
                {typeof r.accuracy === "number" ? (
                  <ProgressBar value={r.accuracy} width={120} />
                ) : (
                  <span className={`mono ${styles.strong}`}>{r.accuracy}</span>
                )}
              </div>
              <div
                className={`${styles.cDelta} mono`}
                style={{
                  color:
                    r.deltaTone === "success"
                      ? "var(--success-fg)"
                      : r.deltaTone === "danger"
                        ? "var(--danger-fg)"
                        : "var(--text-tertiary)",
                }}
              >
                {r.delta}
              </div>
              <div className={styles.cStatus}>
                <StatusPill status={r.status} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
