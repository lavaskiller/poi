import { useEffect, useMemo, useState } from "react";
import Button from "../components/Button";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./Onboarding.module.css";

export default function Onboarding({ onSeeded }: { onSeeded: () => void }) {
  const presets = useAsync(() => api.seedPresets(), []);
  const [preset, setPreset] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selectable = present on disk. Default to the first available one.
  const available = useMemo(
    () => (presets.status === "ready" ? presets.data.presets.filter((p) => p.available) : []),
    [presets],
  );
  useEffect(() => {
    if (!preset && available.length) setPreset(available[0].id);
  }, [available, preset]);

  const current = available.find((p) => p.id === preset) ?? available[0] ?? null;

  async function load() {
    if (!current) return;
    setLoading(true);
    setError(null);
    try {
      await api.seed(current.id);
      onSeeded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    }
  }

  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <span className={styles.icon}>🗂</span>
        <h1 className={styles.title}>No dataset yet</h1>
        <p className={styles.desc}>
          The evaluation API is connected. Load a bundled setup to explore with real data — or add
          your own dataset ZIP later.
        </p>

        {presets.status === "loading" && (
          <p className={styles.presetDesc}>Looking for seed bundles…</p>
        )}

        {presets.status === "error" && (
          <p className={styles.error}>Couldn’t list seed bundles — {presets.error.message}</p>
        )}

        {presets.status === "ready" && !presets.data.bundle_present && (
          <p className={styles.error}>
            No seed bundle found. Place the shared bundle at{" "}
            <code>{presets.data.seed_path}/</code> (from Google Drive), then retry.
          </p>
        )}

        {presets.status === "ready" && presets.data.bundle_present && available.length === 0 && (
          <p className={styles.error}>
            The bundle at <code>{presets.data.seed_path}/</code> has no usable preset
            (missing <code>eval_set_reconciled.csv</code>).
          </p>
        )}

        {available.length > 0 && (
          <>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>Default setup</span>
              <select
                className={styles.select}
                value={current?.id ?? ""}
                onChange={(e) => setPreset(e.target.value)}
                disabled={loading}
              >
                {available.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            {current && (
              <p className={styles.presetDesc}>
                {current.desc}
                {current.desc ? " " : ""}
                <span className={styles.presetMeta}>
                  {current.rows.toLocaleString()} rows · {current.runs} baseline
                  {current.runs === 1 ? "" : "s"}
                </span>
              </p>
            )}

            <Button kind="primary" loading={loading} disabled={!current} onClick={load}>
              Load default setup
            </Button>
          </>
        )}

        {presets.status === "error" || (presets.status === "ready" && !presets.data.bundle_present) ? (
          <button type="button" className={styles.retry} onClick={presets.reload} disabled={loading}>
            Retry
          </button>
        ) : null}

        {error && <p className={styles.error}>Couldn’t load the seed — {error}</p>}
        <p className={styles.hint}>Seeds the backend once. You can delete or replace it anytime.</p>
      </div>
    </div>
  );
}
