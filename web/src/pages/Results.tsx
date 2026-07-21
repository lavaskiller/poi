import Button from "../components/Button";
import StatTile from "../components/StatTile";
import CaseCard, { type CaseCardData } from "../components/CaseCard";
import styles from "./Results.module.css";

const FILTERS = [
  { label: "All failures · 223", active: true },
  { label: "Selection miss · 161", dot: "var(--warning-fg)" },
  { label: "Retrieval miss · 62", dot: "var(--danger-fg)" },
  { label: "Policy / non-POI · 41", dot: "var(--policy-fg)" },
  { label: "No GT · 252", dot: "var(--text-tertiary)" },
];

const CASES: CaseCardData[] = [
  {
    band: "warning",
    filename: "IMG_2841.HEIC",
    title: "Case #0412 — Café, Seongsu",
    predicted: "✗ Onion Bakery Seongsu",
    groundTruth: "✓ Café Onion — Seongsu 2F",
    gtSrc: "src · kakao",
  },
  {
    band: "warning",
    filename: "IMG_1178.HEIC",
    title: "Case #0357 — Coffee chain",
    predicted: "✗ Starbucks Seongsu",
    groundTruth: "✓ Starbucks Seongsu E-Mart",
    gtSrc: "src · kakao",
  },
  {
    band: "danger",
    filename: "IMG_0093.HEIC",
    title: "Case #0290 — Wine bar",
    predicted: "— no candidate matched",
    groundTruth: "✓ Hidden Cellar Wine Bar",
    gtSrc: "src · kakao",
  },
  {
    band: "warning",
    filename: "IMG_3320.HEIC",
    title: "Case #0518 — Noodle shop",
    predicted: "✗ Emoi Vietnam Noodle",
    groundTruth: "✓ Pho Hanoi Seongsu",
    gtSrc: "src · kakao",
  },
  {
    band: "policy",
    filename: "IMG_0761.HEIC",
    title: "Case #0102 — Street scene",
    predicted: "◌ Seongsu Station Exit 3 — deferred",
    predictedTone: "policy",
    groundTruth: "non-POI · policy: defer",
    groundTruthTone: "secondary",
    gtSrc: "src · gt-classify",
  },
  {
    band: "danger",
    filename: "IMG_2214.HEIC",
    title: "Case #0645 — Café, hidden",
    predicted: "✗ Mellower Coffee",
    groundTruth: "✓ Café Onion — not in top 50",
    gtSrc: "src · kakao",
  },
];

export default function Results() {
  return (
    <main className={styles.main}>
      {/* header */}
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Run result</p>
          <div className={styles.titleRow}>
            <h1 className={styles.h1}>heuristic-v2 · v7</h1>
            <span className={styles.bestPill}>BEST YET</span>
          </div>
          <p className={styles.sub}>
            Finished 2 hours ago · 1,032 eligible cases · strict exact-match · host runtime 2m 41s
          </p>
        </div>
        <Button kind="secondary">Compare with…</Button>
        <Button kind="secondary">Export CSV</Button>
      </header>

      {/* metrics */}
      <div className={styles.metrics}>
        <StatTile
          label="Selection accuracy"
          value="✓ 78.4%"
          valueTone="success"
          note="809/1,032 · +2.1 · legacy app_poi_rank"
        />
        <StatTile
          label="Selection miss"
          value="161"
          valueTone="warning"
          note="GT in candidates, wrong pick"
        />
        <StatTile
          label="Retrieval miss"
          value="✗ 62"
          valueTone="danger"
          note="GT absent from candidates"
        />
        <StatTile label="Canonical score" value="84.9%" note="accepts similar-name matches" />
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
        <span className={styles.sortNote}>sorted by confidence · 1–6 of 161</span>
      </div>

      {/* gallery */}
      <div className={styles.gallery}>
        {CASES.map((c) => (
          <CaseCard key={c.filename} {...c} />
        ))}
      </div>
    </main>
  );
}
