import Button from "../components/Button";
import styles from "./Datasets.module.css";

type Tone = "success" | "warning";
interface Meter {
  label: string;
  pct: number;
  tone: Tone;
}
interface Dataset {
  name: string;
  meta: string;
  meters: Meter[];
}

const DATASETS: Dataset[] = [
  {
    name: "linkedspaces",
    meta: "812 rows · KR · ingested 2026-06-30",
    meters: [
      { label: "EXIF", pct: 96, tone: "success" },
      { label: "OCR", pct: 58, tone: "warning" },
      { label: "NEARBY", pct: 100, tone: "success" },
      { label: "GT", pct: 84, tone: "success" },
    ],
  },
  {
    name: "union-city",
    meta: "214 rows · US · ingested 2026-07-08",
    meters: [
      { label: "EXIF", pct: 91, tone: "success" },
      { label: "OCR", pct: 71, tone: "success" },
      { label: "NEARBY", pct: 100, tone: "success" },
      { label: "GT", pct: 77, tone: "warning" },
    ],
  },
  {
    name: "vancouver",
    meta: "258 rows · CA · ingested 2026-07-15",
    meters: [
      { label: "EXIF", pct: 93, tone: "success" },
      { label: "OCR", pct: 64, tone: "warning" },
      { label: "NEARBY", pct: 100, tone: "success" },
      { label: "GT", pct: 76, tone: "warning" },
    ],
  },
];

const DONE_JOBS = [
  { name: "EXIF extraction — vancouver", when: "done · 2h ago" },
  { name: "GT classify — union-city", when: "done · yesterday" },
  { name: "MapKit nearby — vancouver", when: "done · 2 days ago" },
];

function CoverageMeter({ meter }: { meter: Meter }) {
  const color = meter.tone === "warning" ? "var(--warning-fg)" : "var(--success-fg)";
  return (
    <div className={styles.meter}>
      <div className={styles.meterHead}>
        <span className={styles.meterLabel}>{meter.label}</span>
        <span className={styles.meterPct} style={{ color }}>
          {meter.pct}%
        </span>
      </div>
      <div className={styles.meterTrack}>
        <div className={styles.meterFill} style={{ width: `${meter.pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function Datasets() {
  return (
    <main className={styles.main}>
      {/* header */}
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Data</p>
          <h1 className={styles.h1}>Datasets</h1>
          <p className={styles.sub}>
            Ingest photo ZIPs, watch enrichment fill in signals, and keep coverage healthy.
          </p>
        </div>
        <Button kind="secondary">Download template</Button>
        <Button kind="primary">＋&nbsp;&nbsp;Add dataset</Button>
      </header>

      {/* dataset list */}
      <div className={styles.list}>
        {DATASETS.map((ds) => (
          <div key={ds.name} className={styles.dsRow}>
            <div className={styles.dsName}>
              <p className={styles.dsTitle}>{ds.name}</p>
              <p className={styles.dsMeta}>{ds.meta}</p>
            </div>
            {ds.meters.map((m) => (
              <CoverageMeter key={m.label} meter={m} />
            ))}
            <span className={styles.dsSpacer} />
            <a href="#" className={styles.rerunLink}>
              Rerun extraction →
            </a>
            <span className={styles.more}>⋯</span>
          </div>
        ))}
      </div>

      {/* jobs + ingest */}
      <div className={styles.bottom}>
        <div className={styles.jobs}>
          <p className={styles.miniLabel}>Background jobs</p>

          <div className={styles.rerunControls}>
            <span className={styles.rerunLabel}>RERUN</span>
            <span className={styles.select}>
              step: OCR <span className={styles.caret}>▾</span>
            </span>
            <span className={styles.select}>
              dataset: all <span className={styles.caret}>▾</span>
            </span>
            <span className={styles.checkRow}>
              <span className={styles.checkBox}>✓</span>
              unprocessed only
            </span>
            <span className={styles.rerunBtn}>▶ Rerun</span>
          </div>

          <div className={styles.activeJob}>
            <div className={styles.activeHead}>
              <span className={styles.jobDot} style={{ background: "var(--warning-fg)" }} />
              <span className={styles.activeName}>OCR extraction — linkedspaces</span>
              <span className={styles.activeSpacer} />
              <span className={styles.activeStat}>64% · 412/638 · ~4 min left</span>
            </div>
            <div className={styles.jobTrack}>
              <div className={styles.jobFill} style={{ width: "64%" }} />
            </div>
            <p className={styles.activeNote}>
              Keep working — rows appear in Overview as they finish. One job runs at a time.
            </p>
          </div>

          {DONE_JOBS.map((j) => (
            <div key={j.name} className={styles.doneRow}>
              <span className={styles.jobDot} style={{ background: "var(--success-fg)" }} />
              <span className={styles.doneName}>{j.name}</span>
              <span className={styles.activeSpacer} />
              <span className={styles.doneWhen}>{j.when}</span>
              <a href="#" className={styles.logLink}>
                log →
              </a>
            </div>
          ))}
        </div>

        <div className={styles.ingest}>
          <p className={styles.miniLabel}>Add a dataset</p>
          <div className={styles.dropzone}>
            <span className={styles.dropIcon}>⬆</span>
            <span className={styles.dropTitle}>Drop a dataset ZIP</span>
            <span className={styles.dropSub}>validated before anything is written</span>
          </div>
          <div className={styles.steps}>
            {[
              "Validate structure & required columns",
              "Ingest rows + photos",
              "Enrichment fills EXIF · OCR · nearby · GT",
            ].map((s, i) => (
              <div key={s} className={styles.stepRow}>
                <span className={styles.stepNum}>{i + 1}.</span>
                <span className={styles.stepText}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
