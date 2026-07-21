import styles from "./CandidateRow.module.css";

export type CandidateState = "default" | "gt" | "miss" | "hit";

export interface CandidateRowData {
  rank: number;
  name: string;
  score: string;
  scoreValue: number; // 0–1, drives the mini score bar
  distance: string;
  state?: CandidateState;
  tag?: string;
}

const BAR_COLOR: Record<CandidateState, string> = {
  default: "var(--accent-default)",
  gt: "var(--success-fg)",
  miss: "var(--danger-fg)",
  hit: "var(--accent-default)",
};

const TAG_CLASS: Record<CandidateState, string> = {
  default: "",
  gt: styles.tagGt,
  miss: styles.tagMiss,
  hit: styles.tagHit,
};

export default function CandidateRow({
  rank,
  name,
  score,
  scoreValue,
  distance,
  state = "default",
  tag,
}: CandidateRowData) {
  return (
    <div className={`${styles.row} ${styles[state]}`}>
      <span className={styles.rank}>{rank}</span>
      <span className={styles.name}>{name}</span>
      <span className={styles.bar}>
        <span
          className={styles.barFill}
          style={{ width: `${Math.max(0, Math.min(1, scoreValue)) * 26}px`, background: BAR_COLOR[state] }}
        />
      </span>
      <span className={styles.score}>{score}</span>
      <span className={styles.dist}>{distance}</span>
      {tag && <span className={`${styles.tag} ${TAG_CLASS[state]}`}>{tag}</span>}
    </div>
  );
}
