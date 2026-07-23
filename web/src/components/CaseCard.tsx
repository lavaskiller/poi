import { useEffect, useState } from "react";
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
  /**
   * Gallery lives in an overflow scroll pane (not the window). Native
   * loading="lazy" often never fires there — prefer eager for result cards.
   */
  imageLoading?: "eager" | "lazy";
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
  imageLoading = "eager",
}: CaseCardData) {
  const [broken, setBroken] = useState(false);
  // When the gallery pages, the same CaseCard instance can receive a new
  // ``image``; clear a previous onError so the new photo is attempted.
  useEffect(() => {
    setBroken(false);
  }, [image]);
  return (
    <div className={styles.card}>
      <div className={styles.band} style={{ background: BAND_COLOR[band] }} />
      <div className={styles.inner}>
        <div className={styles.photo}>
          {image && !broken ? (
            <img
              key={image}
              className={styles.photoImg}
              src={image}
              alt={filename}
              loading={imageLoading}
              decoding="async"
              onError={() => setBroken(true)}
            />
          ) : (
            <span className={styles.filename} title={filename}>
              {filename}
            </span>
          )}
        </div>
        <div className={styles.body}>
          <p className={styles.title} title={title}>
            {title}
          </p>
          <p className={styles.filenameLine} title={filename}>
            {filename}
          </p>
          <div className={styles.kv}>
            <span className={styles.kvLabel}>{predictedLabel}</span>
            <span
              className={styles.kvValue}
              style={{ color: TONE_COLOR[predictedTone] }}
              title={predicted}
            >
              {predicted}
            </span>
          </div>
          <div className={styles.kv}>
            <span className={styles.kvLabel}>{groundTruthLabel}</span>
            <span
              className={styles.kvValue}
              style={{ color: TONE_COLOR[groundTruthTone] }}
              title={groundTruth}
            >
              {groundTruth}
            </span>
            {gtSrc && <span className={styles.gtSrc}>{gtSrc}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
