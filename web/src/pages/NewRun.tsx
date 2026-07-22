import { useMemo, useState } from "react";
import Button from "../components/Button";
import ProgressBar from "../components/ProgressBar";
import { api, type SchemaField } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./NewRun.module.css";

const STEPS = ["Algorithm", "Inputs", "Scope & run"];

// which real columns each preset selects (matched against a field's cols)
const RECOMMENDED = new Set(["photo", "capture_lat", "caption_ondevice", "app_nearby_top1", "app_nearby_n_wide"]);
const MINIMAL = new Set(["photo", "capture_lat"]);

interface Field {
  key: string;
  name: string;
  path: string;
  fill: number;
  cols: string[];
}

function fieldsMatch(f: Field, set: Set<string>): boolean {
  return f.cols.some((c) => set.has(c));
}

function Stepper() {
  return (
    <div className={styles.stepper}>
      {STEPS.map((label, i) => (
        <div key={label} className={styles.stepGroup}>
          <span className={`${styles.stepNum} ${i === 0 ? styles.stepActive : ""}`}>{i + 1}</span>
          <span className={`${styles.stepLabel} ${i === 0 ? styles.stepLabelActive : ""}`}>{label}</span>
          {i < STEPS.length - 1 && <span className={styles.connector} />}
        </div>
      ))}
    </div>
  );
}

export default function NewRun() {
  const overview = useAsync(() => api.overview(), []);

  const fields = useMemo<Field[]>(() => {
    const schema: SchemaField[] = overview.status === "ready" ? overview.data.schema ?? [] : [];
    // exposable to predict(case): input signals + MapKit baseline hints (GT excluded)
    return schema
      .filter((s) => s.role_key === "in" || s.role_key === "bl")
      .map((s) => ({
        key: s.cols[0] ?? s.group,
        name: s.group,
        path: `case.${s.cols[0] ?? ""}`,
        fill: s.fill,
        cols: s.cols,
      }));
  }, [overview.status]);

  const total = overview.status === "ready" ? overview.data.total : 0;

  const presets = useMemo(
    () => [
      { id: "recommended", label: "Recommended", members: fields.filter((f) => fieldsMatch(f, RECOMMENDED)) },
      { id: "everything", label: "Everything", members: fields },
      { id: "minimal", label: "Minimal", members: fields.filter((f) => fieldsMatch(f, MINIMAL)) },
    ],
    [fields],
  );

  const [selected, setSelected] = useState<Set<string> | null>(null);
  // default to Recommended once fields load
  const active = selected ?? new Set(presets[0].members.map((f) => f.key));

  const applyPreset = (members: Field[]) => setSelected(new Set(members.map((f) => f.key)));
  const toggle = (key: string) => {
    const next = new Set(active);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };

  const selectedFields = fields.filter((f) => active.has(f.key));
  // a row is eligible if it has every selected input → min coverage across them
  const eligible = selectedFields.length ? Math.min(...selectedFields.map((f) => f.fill)) : total;
  const binding = selectedFields.length
    ? selectedFields.reduce((a, b) => (a.fill <= b.fill ? a : b))
    : null;
  const eligPct = total > 0 ? Math.round((eligible / total) * 100) : 0;

  const activePresetId = presets.find(
    (p) => p.members.length === active.size && p.members.every((f) => active.has(f.key)),
  )?.id;

  return (
    <main className={styles.main}>
      <div className={styles.titles}>
        <p className={`sectionLabel ${styles.kicker}`}>Run → Score → Inspect</p>
        <h1 className={styles.h1}>New run</h1>
        <p className={styles.sub}>
          Attach a prediction script, choose the inputs it receives, and score it against ground truth.
        </p>
      </div>

      <Stepper />

      {/* 1 · Algorithm (attach — not yet wired to execution) */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>1 · Algorithm</span>
          <span className={styles.headHint}>— one function: predict(case) → place name</span>
        </div>
        <div className={styles.algoRow}>
          <div className={styles.dropzone}>
            <span className={styles.dropIcon}>⬆</span>
            <span className={styles.dropTitle}>Drop your script — or click to browse</span>
            <span className={styles.dropTypes}>.py · .js · .rs · .c · .sh</span>
          </div>
          <div className={styles.attached}>
            <div className={styles.fileRow}>
              <span>📄</span>
              <span className={styles.fileName}>heuristic_v2.py</span>
              <span className={styles.fileSize}>4.2 KB</span>
            </div>
            <code className={styles.signature}>def predict(case) → str</code>
            <div className={styles.fileActions}>
              <span className={styles.linkMuted}>Run execution wiring is next (POST /api/run).</span>
            </div>
          </div>
        </div>
      </section>

      {/* 2 · Inputs — real schema */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>2 · Inputs</span>
          <span className={styles.headHint}>— what each case actually exposes to predict(case)</span>
        </div>

        {overview.status === "loading" && <p className={styles.headHint}>Loading fields…</p>}
        {overview.status === "error" && (
          <p className={styles.headHint}>Couldn’t load fields — {overview.error.message}</p>
        )}

        {overview.status === "ready" && (
          <>
            <div className={styles.presets}>
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`${styles.preset} ${activePresetId === p.id ? styles.presetOn : ""}`}
                  onClick={() => applyPreset(p.members)}
                >
                  {p.label} · {p.members.length}
                </button>
              ))}
              {!activePresetId && <span className={styles.headHint}>Custom · {active.size}</span>}
            </div>

            <div className={styles.inputsRow}>
              <div className={styles.inputGrid}>
                {fields.map((f) => {
                  const on = active.has(f.key);
                  const cov = total > 0 ? Math.round((f.fill / total) * 100) : 0;
                  const sparse = cov < 90;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      className={`${styles.chip} ${on ? styles.chipOn : styles.chipOff}`}
                      onClick={() => toggle(f.key)}
                    >
                      <span className={`${styles.box} ${on ? styles.boxOn : ""}`}>{on && "✓"}</span>
                      <span className={styles.chipName}>{f.name}</span>
                      <span className={styles.chipPath}>{f.path}</span>
                      <span className={styles.chipSpacer} />
                      {sparse && <span className={styles.warnText}>⚠ {total - f.fill} missing</span>}
                      <span className={sparse ? styles.warnPct : styles.chipPct}>{cov}%</span>
                    </button>
                  );
                })}
              </div>
              <div className={styles.eligibility}>
                <p className={styles.eligLabel}>Eligible cases</p>
                <div className={styles.eligValueRow}>
                  <span className={styles.eligValue}>{eligible.toLocaleString()}</span>
                  <span className={styles.eligOf}>
                    / {total.toLocaleString()} ({eligPct}%)
                  </span>
                </div>
                <ProgressBar value={total > 0 ? eligible / total : 0} width="100%" />
                <p className={styles.eligNote}>
                  {binding
                    ? `${binding.name} is the binding constraint — ${total - binding.fill} rows lack it.`
                    : "Select at least one input."}
                </p>
              </div>
            </div>
          </>
        )}
      </section>

      {/* 3 · Scope & run */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>3 · Scope &amp; run</span>
        </div>
        <div className={styles.scopeRow}>
          <div className={styles.field}>
            <p className={styles.fieldLabel}>Datasets</p>
            <div className={styles.datasetRow}>
              {(overview.status === "ready" ? overview.data.sources : []).map((s) => (
                <span key={s.key} className={`${styles.dataset} ${styles.datasetOn}`}>
                  ✓ {s.key} · {s.count}
                </span>
              ))}
            </div>
            <p className={styles.fieldHint}>{eligible.toLocaleString()} eligible with current inputs</p>
          </div>
          <div className={styles.scopeSpacer} />
          <div className={styles.runCol}>
            <Button kind="primary" disabled>
              ▶&nbsp;&nbsp;Run evaluation
            </Button>
            <span className={styles.runHint}>execution wiring (POST /api/run) is the next step</span>
          </div>
        </div>
      </section>
    </main>
  );
}
