import { useEffect, useRef, useState } from "react";
import { api, type SeedPresets } from "../lib/api";
import styles from "./Onboarding.module.css";

/**
 * First-run screen when the data root has no eval CSV.
 *
 * Two package types (do not mix):
 *   • Seed bundle ZIP  — eval_set_reconciled.csv + runs + MapKit candidates
 *                        (+ photos). Used only here.
 *   • Dataset import ZIP — photos + metadata for Datasets → Upload.
 *     That template will fail onboarding (missing eval_set_reconciled.csv).
 */
export default function Onboarding({ onSeeded }: { onSeeded: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<SeedPresets | null>(null);
  const [presetId, setPresetId] = useState("default");

  useEffect(() => {
    let cancelled = false;
    api
      .seedPresets()
      .then((p) => {
        if (cancelled) return;
        setPresets(p);
        const first = p.presets.find((x) => x.available) ?? p.presets[0];
        if (first) setPresetId(first.id);
      })
      .catch(() => {
        if (!cancelled) setPresets({ bundle_present: false, seed_path: "poi-data-seed", presets: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function upload(file: File) {
    if (!/\.zip$/i.test(file.name)) {
      setError(`“${file.name}” is not a .zip — drop the seed-bundle ZIP (not a dataset template).`);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api.seedUpload(file);
      onSeeded();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const hint =
        /eval_set_reconciled|not found in bundle|dataset template/i.test(msg)
          ? " This looks like a dataset-import ZIP, not a seed bundle. Use Datasets → Upload for that package."
          : "";
      setError(`${msg}${hint}`);
      setLoading(false);
    }
  }

  async function loadLocalPreset() {
    setLoading(true);
    setError(null);
    try {
      await api.seed(presetId);
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
    if (file) void upload(file);
  }

  const available = presets?.presets.filter((p) => p.available) ?? [];
  const bundlePresent = presets?.bundle_present === true && available.length > 0;
  const seedPath = presets?.seed_path || "poi-data-seed";

  return (
    <div className={styles.screen}>
      <div className={styles.card}>
        <span className={styles.icon}>🗂</span>
        <h1 className={styles.title}>Load a demo seed to start</h1>
        <p className={styles.desc}>
          Fresh clones ship without evaluation data. Load the <strong>seed bundle</strong> (CSV +
          three named baselines + MapKit candidates + photos) to explore Results, Compare, and New
          Run immediately.
        </p>

        <div className={styles.baselineBox}>
          <p className={styles.baselineTitle}>Named baselines in the seed</p>
          <ul className={styles.baselineList}>
            <li>
              <code>baseline-nearest</code> v1 — distance rank-1 · <strong>38%</strong>
            </li>
            <li>
              <code>mapkit-baseline</code> v1 — Bloggo + OCR override · <strong>39%</strong>
            </li>
            <li>
              <code>mapkit-baseline</code> v2 — OCR + cascade + VLM ensemble ·{" "}
              <strong>48% / 68% canonical</strong>
            </li>
          </ul>
        </div>

        {bundlePresent ? (
          <div className={styles.localSeed}>
            {available.length > 1 && (
              <label className={styles.presetLabel}>
                Local preset
                <select
                  value={presetId}
                  onChange={(e) => setPresetId(e.target.value)}
                  disabled={loading}
                  className={styles.presetSelect}
                >
                  {available.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                      {p.rows ? ` · ${p.rows} rows` : ""}
                      {p.runs ? ` · ${p.runs} runs` : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={loading}
              onClick={() => void loadLocalPreset()}
            >
              {loading ? "Loading seed…" : "Load local demo seed"}
            </button>
            <p className={styles.hint}>
              Found on disk at <code>{seedPath}/</code>
              {available[0]?.rows != null ? ` · ${available[0].rows} rows` : ""}
              {available[0]?.runs != null ? ` · ${available[0].runs} baselines` : ""}
            </p>
            <a className={styles.linkBtn} href="/api/seed/download">
              Download seed ZIP
            </a>
          </div>
        ) : (
          <div className={styles.missingSeed}>
            <p className={styles.missingTitle}>No local seed bundle yet</p>
            <p className={styles.hint}>
              Place a pack at <code>{seedPath}/</code>, or upload a seed ZIP below. Rebuild with:
            </p>
            <pre className={styles.code}>
              {`python3 tools/pack_seed_bundle.py --clean
# optional shareable ZIP:
python3 tools/pack_seed_bundle.py --clean --zip /tmp/poi-data-seed.zip`}
            </pre>
            <p className={styles.hint}>
              Needs a full <code>poi-data/</code> (or shared Drive copy) as the pack source. See{" "}
              <code>docs/onboarding.md</code>.
            </p>
          </div>
        )}

        <div className={styles.divider}>
          <span>or upload a seed-bundle ZIP</span>
        </div>

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
                Drag a <strong>seed-bundle</strong> ZIP here, or{" "}
                <span className={styles.dzLink}>browse</span>
              </span>
              <span className={styles.dzHint}>
                requires <code>eval_set_reconciled.csv</code> + <code>generated/runs/</code> + MapKit
                candidates
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
            if (file) void upload(file);
            e.target.value = "";
          }}
        />

        {error && <p className={styles.error}>Couldn’t seed — {error}</p>}

        <div className={styles.notSeed}>
          <p className={styles.notSeedTitle}>Not a seed bundle</p>
          <p className={styles.hint}>
            The <strong>dataset import template</strong> (Datasets → Download template) is a different
            format for adding your own photos later. Uploading it here fails with{" "}
            <code>eval_set_reconciled.csv not found</code>.
          </p>
        </div>

        <p className={styles.hint}>
          After seeding you should see: dataset loaded · GT ready · candidate artifacts ready ·
          runnable · three scored baselines on Results.
        </p>
      </div>
    </div>
  );
}
