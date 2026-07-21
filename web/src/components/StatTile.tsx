import styles from "./StatTile.module.css";

type Tone = "primary" | "tertiary" | "warning" | "success" | "danger";

interface StatTileProps {
  label: string;
  value: string;
  valueTone?: Tone;
  note?: string;
  noteTone?: Exclude<Tone, "primary">;
  size?: "lg" | "md";
}

export default function StatTile({
  label,
  value,
  valueTone = "primary",
  note,
  noteTone = "tertiary",
  size = "lg",
}: StatTileProps) {
  return (
    <div className={styles.tile}>
      <p className={`sectionLabel ${styles.label}`}>{label}</p>
      <p className={`${styles.value} ${styles[`v_${valueTone}`]} ${size === "md" ? styles.md : ""}`}>
        {value}
      </p>
      {note && <p className={`${styles.note} ${styles[noteTone]}`}>{note}</p>}
    </div>
  );
}
