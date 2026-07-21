import CaseCard, { type CaseCardData } from "../components/CaseCard";
import styles from "./Compare.module.css";

type DeltaTone = "success" | "muted";
const ROWS: { metric: string; v6: string; v7: string; delta: string; tone: DeltaTone }[] = [
  { metric: "Selection accuracy (strict)", v6: "76.3%", v7: "78.4%", delta: "▲ +2.1", tone: "success" },
  { metric: "Canonical accuracy", v6: "83.0%", v7: "84.9%", delta: "▲ +1.9", tone: "success" },
  { metric: "Selection misses", v6: "183", v7: "161", delta: "▼ −22", tone: "success" },
  { metric: "Retrieval misses", v6: "62", v7: "62", delta: "— 0", tone: "muted" },
  { metric: "Host runtime", v6: "3m 02s", v7: "2m 41s", delta: "▼ −21s", tone: "success" },
];

const FLIPS: CaseCardData[] = [
  {
    band: "success",
    filename: "IMG_0554.HEIC",
    title: "Case #0221 — fixed ✓",
    predictedLabel: "V6 PICK",
    predicted: "Seongsu Hardware",
    predictedTone: "secondary",
    groundTruthLabel: "V7 PICK",
    groundTruth: "✓ Café Sikmul  ✓ = GT",
    groundTruthTone: "success",
    gtSrc: "src · kakao",
  },
  {
    band: "success",
    filename: "IMG_1837.HEIC",
    title: "Case #0388 — fixed ✓",
    predictedLabel: "V6 PICK",
    predicted: "Daiso Seongsu",
    predictedTone: "secondary",
    groundTruthLabel: "V7 PICK",
    groundTruth: "✓ Object Seongsu  ✓ = GT",
    groundTruthTone: "success",
    gtSrc: "src · kakao",
  },
  {
    band: "danger",
    filename: "IMG_0102.HEIC",
    title: "Case #0074 — broken ✗",
    predictedLabel: "V6 PICK",
    predicted: "✓ Musinsa Terrace  ✓ = GT",
    predictedTone: "success",
    groundTruthLabel: "V7 PICK",
    groundTruth: "✗ Musinsa Studio",
    groundTruthTone: "danger",
    gtSrc: "src · kakao",
  },
];

export default function Compare() {
  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <p className={`sectionLabel ${styles.kicker}`}>Compare runs</p>
        <h1 className={styles.h1}>heuristic-v2 — v7 vs v6</h1>
        <p className={styles.sub}>
          Same cohort · 1,032 eligible cases · strict exact-match — comparison is apples-to-apples.
        </p>
      </div>

      {/* tray */}
      <div className={styles.tray}>
        <span className={styles.trayCount}>COMPARING 2 / 4</span>
        <span className={`${styles.runChip} ${styles.runChipOn}`}>heuristic-v2 · v7 <span className={styles.x}>✕</span></span>
        <span className={`${styles.runChip} ${styles.runChipOn}`}>heuristic-v2 · v6 <span className={styles.x}>✕</span></span>
        <span className={`${styles.runChip} ${styles.runChipOff}`}>gpt-rerank · v2 ⚠ <span className={styles.x}>✕</span></span>
        <span className={styles.addRun}>＋ Add run</span>
      </div>

      {/* cohort guard */}
      <div className={styles.guard}>
        gpt-rerank · v2 is excluded — different cohort (all datasets vs linkedspaces+2). Only runs
        with the same cohort and scoring mode are comparable.
      </div>

      {/* duel */}
      <div className={styles.duel}>
        <div className={`${styles.duelCard} ${styles.winner}`}>
          <div className={styles.duelHead}>
            <span className={styles.duelVer}>v7 · 2h ago</span>
            <span className={styles.winnerPill}>WINNER</span>
          </div>
          <span className={styles.duelValue}>78.4%</span>
          <span className={styles.duelSub}>809 correct · runtime 2m 41s</span>
        </div>
        <div className={styles.duelCard}>
          <div className={styles.duelHead}>
            <span className={styles.duelVer}>v6 · yesterday</span>
          </div>
          <span className={`${styles.duelValue} ${styles.duelValueMuted}`}>76.3%</span>
          <span className={styles.duelSub}>787 correct · runtime 3m 02s</span>
        </div>
      </div>

      {/* delta table */}
      <div className={styles.table}>
        <div className={`${styles.row} ${styles.headRow}`}>
          <div className={styles.cMetric}>METRIC</div>
          <div className={styles.cCol}>V6</div>
          <div className={styles.cCol}>V7</div>
          <div className={styles.cCol}>Δ</div>
        </div>
        {ROWS.map((r) => (
          <div key={r.metric} className={styles.row}>
            <div className={styles.cMetric}>{r.metric}</div>
            <div className={`${styles.cCol} mono ${styles.muted}`}>{r.v6}</div>
            <div className={`${styles.cCol} mono ${styles.strong}`}>{r.v7}</div>
            <div
              className={`${styles.cCol} mono`}
              style={{ color: r.tone === "success" ? "var(--success-fg)" : "var(--text-tertiary)" }}
            >
              {r.delta}
            </div>
          </div>
        ))}
      </div>

      {/* flips */}
      <div className={styles.flipsHead}>
        <span className={`sectionLabel ${styles.flipsLabel}`}>31 flipped cases</span>
        <span className={`${styles.filter} ${styles.filterOn}`}>All · 31</span>
        <span className={styles.filter}>
          <span className={styles.dot} style={{ background: "var(--success-fg)" }} />
          Fixed by v7 · 25
        </span>
        <span className={styles.filter}>
          <span className={styles.dot} style={{ background: "var(--danger-fg)" }} />
          Broken by v7 · 6
        </span>
      </div>
      <div className={styles.flipsGallery}>
        {FLIPS.map((c) => (
          <CaseCard key={c.filename} {...c} />
        ))}
      </div>
    </main>
  );
}
