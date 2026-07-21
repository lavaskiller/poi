import styles from "./StatTile.module.css";

type NoteTone = "tertiary" | "warning" | "success" | "danger";

interface StatTileProps {
  label: string;
  value: string;
  note?: string;
  noteTone?: NoteTone;
}

export default function StatTile({ label, value, note, noteTone = "tertiary" }: StatTileProps) {
  return (
    <div className={styles.tile}>
      <p className={`sectionLabel ${styles.label}`}>{label}</p>
      <p className={styles.value}>{value}</p>
      {note && <p className={`${styles.note} ${styles[noteTone]}`}>{note}</p>}
    </div>
  );
}
