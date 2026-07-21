import { useState } from "react";
import Button from "../components/Button";
import ProgressBar from "../components/ProgressBar";
import styles from "./NewRun.module.css";

const STEPS = ["Algorithm", "Inputs", "Scope & run"];

const PRESETS = [
  { label: "Recommended · 4", active: true },
  { label: "Everything · 11", active: false },
  { label: "Minimal · 2", active: false },
];

type Input = {
  name: string;
  path: string;
  pct: string;
  checked: boolean;
  warn?: string;
  warnTone?: boolean;
};

const INPUTS: Input[] = [
  { name: "photo", path: "case.photo", pct: "100%", checked: true },
  { name: "exif.gps", path: "case.exif.gps", pct: "94%", checked: true },
  { name: "mapkit.nearby", path: "case.candidates[ ]", pct: "100%", checked: true },
  { name: "ocr.text", path: "case.ocr.text", pct: "61%", checked: true, warn: "⚠ drops 223 rows", warnTone: true },
  { name: "heading", path: "case.exif.heading", pct: "38%", checked: false, warn: "⚠ sparse", warnTone: true },
  { name: "device.locale", path: "case.locale", pct: "100%", checked: false },
];

function Stepper() {
  return (
    <div className={styles.stepper}>
      {STEPS.map((label, i) => (
        <div key={label} className={styles.stepGroup}>
          <span className={`${styles.stepNum} ${i === 0 ? styles.stepActive : ""}`}>{i + 1}</span>
          <span className={`${styles.stepLabel} ${i === 0 ? styles.stepLabelActive : ""}`}>
            {label}
          </span>
          {i < STEPS.length - 1 && <span className={styles.connector} />}
        </div>
      ))}
    </div>
  );
}

function InputChip({ input, onToggle }: { input: Input; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={`${styles.chip} ${input.checked ? styles.chipOn : styles.chipOff}`}
      onClick={onToggle}
    >
      <span className={`${styles.box} ${input.checked ? styles.boxOn : ""}`}>
        {input.checked && "✓"}
      </span>
      <span className={styles.chipName}>{input.name}</span>
      <span className={styles.chipPath}>{input.path}</span>
      <span className={styles.chipSpacer} />
      {input.warn && (
        <span className={input.warnTone ? styles.warnText : styles.mutedText}>{input.warn}</span>
      )}
      <span className={input.warnTone ? styles.warnPct : styles.chipPct}>{input.pct}</span>
    </button>
  );
}

export default function NewRun() {
  const [inputs, setInputs] = useState(INPUTS);
  const [preset, setPreset] = useState(0);

  const toggle = (idx: number) =>
    setInputs((prev) => prev.map((it, i) => (i === idx ? { ...it, checked: !it.checked } : it)));

  return (
    <main className={styles.main}>
      <div className={styles.titles}>
        <p className={`sectionLabel ${styles.kicker}`}>Run → Score → Inspect</p>
        <h1 className={styles.h1}>New run</h1>
        <p className={styles.sub}>
          Attach a prediction script, choose the inputs it receives, and score it against ground
          truth.
        </p>
      </div>

      <Stepper />

      {/* 1 · Algorithm */}
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
            <code className={styles.signature}>
              def predict(case) → str | {'{'}"prediction", "reason"{'}'}
            </code>
            <div className={styles.fileActions}>
              <a href="#" className={styles.linkAccent}>
                View code →
              </a>
              <a href="#" className={styles.linkMuted}>
                Replace
              </a>
            </div>
          </div>
        </div>
        <div className={styles.exampleRow}>
          <Button kind="secondary">Load example</Button>
          <span className={styles.headHint}>
            Minimal baseline that returns the nearest candidate — a safe starting point.
          </span>
        </div>
      </section>

      {/* 2 · Inputs */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>2 · Inputs</span>
          <span className={styles.headHint}>— what each case exposes to predict(case)</span>
        </div>
        <div className={styles.presets}>
          {PRESETS.map((p, i) => (
            <button
              key={p.label}
              type="button"
              className={`${styles.preset} ${i === preset ? styles.presetOn : ""}`}
              onClick={() => setPreset(i)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className={styles.inputsRow}>
          <div className={styles.inputGrid}>
            {inputs.map((it, i) => (
              <InputChip key={it.name} input={it} onToggle={() => toggle(i)} />
            ))}
          </div>
          <div className={styles.eligibility}>
            <p className={styles.eligLabel}>Eligible cases</p>
            <div className={styles.eligValueRow}>
              <span className={styles.eligValue}>1,032</span>
              <span className={styles.eligOf}>/ 1,284 (80%)</span>
            </div>
            <ProgressBar value={0.8} width="100%" />
            <p className={styles.eligNote}>ocr.text is the binding constraint — 223 rows lack it.</p>
          </div>
        </div>
      </section>

      {/* 3 · Scope & run */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>3 · Scope &amp; run</span>
        </div>
        <div className={styles.scopeRow}>
          <div className={styles.field}>
            <p className={styles.fieldLabel}>Run name</p>
            <div className={styles.input}>
              <span className={styles.inputText}>heuristic-v2</span>
            </div>
            <p className={styles.fieldHint}>saves as v8 — versions are automatic</p>
          </div>

          <div className={styles.field}>
            <p className={styles.fieldLabel}>Save mode</p>
            <div className={styles.input}>
              <span className={styles.inputText}>Auto — next version (v8)</span>
              <span className={styles.caret}>▾</span>
            </div>
            <p className={styles.fieldHint}>or overwrite an existing version</p>
          </div>

          <div className={styles.field}>
            <p className={styles.fieldLabel}>Datasets</p>
            <div className={styles.datasetRow}>
              <span className={`${styles.dataset} ${styles.datasetOn}`}>✓ linkedspaces · 812</span>
              <span className={`${styles.dataset} ${styles.datasetOn}`}>✓ union-city · 214</span>
              <span className={styles.dataset}>○ vancouver · 258</span>
            </div>
            <p className={styles.fieldHint}>GT scope: canonical + similar</p>
          </div>

          <div className={styles.scopeSpacer} />

          <div className={styles.runCol}>
            <Button kind="primary">▶&nbsp;&nbsp;Run evaluation</Button>
            <span className={styles.runHint}>~3 min on 1,032 cases · lands in Results</span>
          </div>
        </div>
      </section>
    </main>
  );
}
