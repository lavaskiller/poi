import styles from "./Tag.module.css";

export type TagTone = "success" | "warning" | "nonpoi" | "danger" | "neutral";

const LABELS: Record<TagTone, string> = {
  success: "SUCCESS",
  warning: "WARNING",
  nonpoi: "NON-POI",
  danger: "DANGER",
  neutral: "NEUTRAL",
};

interface TagProps {
  tone?: TagTone;
  children?: React.ReactNode;
}

export default function Tag({ tone = "neutral", children }: TagProps) {
  return <span className={[styles.tag, styles[tone]].join(" ")}>{children ?? LABELS[tone]}</span>;
}
