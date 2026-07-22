import { useState } from "react";
import styles from "./CaseCard.module.css";

export type CaseBand = "warning" | "danger" | "policy" | "success";
type ValueTone = "danger" | "policy" | "success" | "secondary";

export interface CaseCardData {
  band: CaseBand;
  filename: string;
  image?: string;
  title: string;
  predicted: string;
  predictedTone?: ValueTone;
  groundTruth: string;
  groundTruthTone?: ValueTone;
  gtSrc?: string;
  predictedLabel?: string;
  groundTruthLabel?: string;
}

const BAND_COLOR: Record<CaseBand, string> = {
  warning: "var(--warning-fg)",
  danger: "var(--danger-fg)",
  policy: "var(--policy-fg)",
  success: "var(--success-fg)",
};

const TONE_COLOR: Record<ValueTone, string> = {
  danger: "var(--danger-fg)",
  policy: "var(--policy-fg)",
  success: "var(--success-fg)",
  secondary: "var(--text-secondary)",
};

export default function CaseCard({
  band,
  filename,
  image,
  title,
  predicted,
  predictedTone = "danger",
  groundTruth,
  groundTruthTone = "success",
  gtSrc,
  predictedLabel = "PREDICTED",
  groundTruthLabel = "GROUND TRUTH",
}: CaseCardData) {
  const [broken, setBroken] = useState(false);
  return (
    <div className={styles.card}>
      <div className={styles.band} style={{ background: BAND_COLOR[band] }} />
      <div className={styles.inner}>
        <div className={styles.photo}>
          {image && !broken ? (
            <img
              className={styles.photoImg}
              src={image}
              alt={filename}
              loading="lazy"
              onError={() => setBroken(true)}
            />
          ) : (
            <span className={styles.filename}>{filename}</span>
          )}
        </div>
        <div className={styles.body}>
          <p className={styles.title}>{title}</p>
          <div className={styles.kv}>
            <span className={styles.kvLabel}>{predictedLabel}</span>
            <span className={styles.kvValue} style={{ color: TONE_COLOR[predictedTone] }}>
              {predicted}
            </span>
          </div>
          <div className={styles.kv}>
            <span className={styles.kvLabel}>{groundTruthLabel}</span>
            <span className={styles.kvValue} style={{ color: TONE_COLOR[groundTruthTone] }}>
              {groundTruth}
            </span>
            {gtSrc && <span className={styles.gtSrc}>{gtSrc}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
