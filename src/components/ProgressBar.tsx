import styles from "./ProgressBar.module.css";

interface ProgressBarProps {
  /** 0–1 */
  value: number;
  width?: number | string;
}

export default function ProgressBar({ value, width = 200 }: ProgressBarProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={styles.track} style={{ width }}>
      <div className={styles.fill} style={{ width: `${pct}%` }} />
    </div>
  );
}
