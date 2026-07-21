import CandidateRow, { type CandidateRowData } from "../components/CandidateRow";
import styles from "./CaseInspector.module.css";

const SIGNALS = [
  { name: "exif.gps", value: "37.5446, 127.0559", present: true },
  { name: "ocr.text", value: "“cafe onion · est 2016”", present: true },
  { name: "mapkit.nearby", value: "12 candidates · 150m radius", present: true },
  { name: "heading", value: "—  not captured", present: false },
];

const CANDIDATES: CandidateRowData[] = [
  { rank: 1, name: "Onion Bakery Seongsu", score: "0.74", scoreValue: 0.74, distance: "24m", state: "miss", tag: "✗ PICK ≠ GT" },
  { rank: 2, name: "Seongsu Baking Studio", score: "0.71", scoreValue: 0.71, distance: "31m" },
  { rank: 3, name: "Café Onion — Seongsu 2F", score: "0.70", scoreValue: 0.70, distance: "38m", state: "gt", tag: "GT" },
  { rank: 4, name: "Daelim Changgo Gallery", score: "0.55", scoreValue: 0.55, distance: "55m" },
  { rank: 5, name: "Zagmachi Coffee", score: "0.41", scoreValue: 0.41, distance: "78m" },
];

export default function CaseInspector() {
  return (
    <main className={styles.main}>
      {/* header */}
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Case inspector · run heuristic-v2 v7</p>
          <div className={styles.titleRow}>
            <h1 className={styles.h1}>Case #0412 — Café, Seongsu</h1>
            <span className={styles.missPill}>SELECTION MISS</span>
          </div>
          <p className={styles.sub}>
            dataset linkedspaces · GT tier: canonical · photo IMG_2841.HEIC
          </p>
        </div>
        <div className={styles.nav}>
          <button type="button" className={styles.navBtn}>
            ← Prev
          </button>
          <span className={styles.navCount}>12 / 161</span>
          <button type="button" className={styles.navBtn}>
            Next →
          </button>
        </div>
      </header>

      <div className={styles.split}>
        {/* photo column */}
        <div className={styles.photoCol}>
          <div className={styles.photo}>
            <span className={styles.photoName}>IMG_2841.HEIC</span>
          </div>
          <div className={styles.signals}>
            <p className={styles.miniLabel}>Signals on this case</p>
            {SIGNALS.map((s) => (
              <div key={s.name} className={styles.signalRow}>
                <span
                  className={styles.signalDot}
                  style={{ background: s.present ? "var(--success-fg)" : "var(--text-tertiary)" }}
                />
                <span className={styles.signalName}>{s.name}</span>
                <span className={s.present ? styles.signalValue : styles.signalMuted}>
                  {s.value}
                </span>
              </div>
            ))}
          </div>
          <div className={styles.map}>
            <span className={styles.mapLabel}>MAP</span>
            <div className={styles.mapLegend}>
              <span className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: "var(--danger-fg)" }} />
                picked
              </span>
              <span className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: "var(--success-fg)" }} />
                ground truth
              </span>
              <span className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: "var(--accent-default)" }} />
                photo location
              </span>
            </div>
          </div>
        </div>

        {/* detail column */}
        <div className={styles.detailCol}>
          <div className={styles.verdict}>
            <p className={styles.verdictTitle}>Wrong pick — ground truth was rank 3 of 12</p>
            <p className={styles.verdictBody}>
              The picked candidate scored 0.74 vs 0.70 for GT. Distance weighting favored the bakery
              next door.
            </p>
          </div>

          <div className={styles.card}>
            <div className={styles.pvgRow}>
              <span className={styles.pvgLabel}>PREDICTED</span>
              <span className={`${styles.pvgName} ${styles.danger}`}>Onion Bakery Seongsu</span>
              <span className={`${styles.pvgPill} ${styles.pillDanger}`}>rank 1 · score 0.74</span>
            </div>
            <div className={styles.pvgRow}>
              <span className={styles.pvgLabel}>GROUND TRUTH</span>
              <span className={`${styles.pvgName} ${styles.success}`}>Café Onion — Seongsu 2F</span>
              <span className={`${styles.pvgPill} ${styles.pillSuccess}`}>rank 3 · score 0.70</span>
              <span className={styles.gtSrc}>src · kakao (name-classified, not resolved)</span>
            </div>
          </div>

          <div className={styles.card}>
            <p className={styles.miniLabel}>Candidates — mapkit.nearby · 12</p>
            {CANDIDATES.map((c) => (
              <CandidateRow key={c.rank} {...c} />
            ))}
            <a href="#" className={styles.moreLink}>
              + 7 more candidates
            </a>
          </div>

          <div className={styles.why}>
            <p className={styles.miniLabel}>Why — predict() reason</p>
            <p className={styles.whyText}>matched ocr token “onion” → name-similarity 0.91;</p>
            <p className={styles.whyText}>
              distance weight 0.7 preferred 24m bakery over 38m café
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
