import { useRef, useState } from "react";
import { api } from "../lib/api";
import styles from "./Onboarding.module.css";

export default function Onboarding({ onSeeded }: { onSeeded: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    if (!/\.zip$/i.test(file.name)) {
      setError(`“${file.name}” is not a .zip — drop the seed bundle ZIP.`);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.seedUpload(file);
      onSeeded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (loading) return;
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  }

  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <span className={styles.icon}>🗂</span>
        <h1 className={styles.title}>No dataset yet</h1>
        <p className={styles.desc}>
          The evaluation API is connected. Drop a seed-bundle ZIP to explore with real data — or add
          your own dataset ZIP later.
        </p>

        <button
          type="button"
          className={`${styles.dropzone} ${dragOver ? styles.dropzoneOver : ""} ${
            loading ? styles.dropzoneBusy : ""
          }`}
          onClick={() => !loading && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            if (!loading) setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          disabled={loading}
        >
          {loading ? (
            <>
              <span className={styles.spinner} aria-hidden />
              <span className={styles.dzTitle}>Uploading &amp; seeding…</span>
            </>
          ) : (
            <>
              <span className={styles.dzIcon} aria-hidden>
                ⬇
              </span>
              <span className={styles.dzTitle}>
                Drag a seed-bundle ZIP here, or <span className={styles.dzLink}>browse</span>
              </span>
              <span className={styles.dzHint}>
                expects <code>eval_set_reconciled.csv</code> + <code>dashboard_config.json</code> +{" "}
                <code>generated/runs/</code>
              </span>
            </>
          )}
        </button>

        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />

        {error && <p className={styles.error}>Couldn’t seed — {error}</p>}
        <p className={styles.hint}>Seeds the backend once. You can delete or replace it anytime.</p>
      </div>
    </div>
  );
}
