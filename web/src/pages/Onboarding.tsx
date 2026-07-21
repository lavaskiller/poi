import { useState } from "react";
import Button from "../components/Button";
import { api } from "../lib/api";
import styles from "./Onboarding.module.css";

const PRESETS = [
  {
    id: "linkedspaces-baselines",
    label: "linkedspaces sample · baseline-nearest + loop70",
    desc: "216 real-user visits, pre-scored by two baselines (nearest-candidate and the loop70 VLM ensemble).",
  },
];

export default function Onboarding({ onSeeded }: { onSeeded: () => void }) {
  const [preset, setPreset] = useState(PRESETS[0].id);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = PRESETS.find((p) => p.id === preset) ?? PRESETS[0];

  async function load() {
    setLoading(true);
    setError(null);
    try {
      await api.seed(preset);
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
          The evaluation API is connected. Load the default setup to explore with real data — or add
          your own dataset ZIP later.
        </p>

        <label className={styles.field}>
          <span className={styles.fieldLabel}>Default setup</span>
          <select
            className={styles.select}
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            disabled={loading}
          >
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <p className={styles.presetDesc}>{current.desc}</p>

        <Button kind="primary" loading={loading} onClick={load}>
          Load default setup
        </Button>

        {error && <p className={styles.error}>Couldn’t load the seed — {error}</p>}
        <p className={styles.hint}>Seeds the backend once. You can delete or replace it anytime.</p>
      </div>
    </div>
  );
}
