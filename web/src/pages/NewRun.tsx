import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../components/Button";
import ProgressBar from "../components/ProgressBar";
import { api, type MatchRate, type Overview, type SchemaField } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./NewRun.module.css";

const STEPS = ["Algorithm", "Inputs", "Scope & run"];

/** Backend PARAM_SIGNALS keys (tools/run_algorithm.py). */
const SIGNAL_PARAMS: {
  key: string;
  label: string;
  path: string;
  /** CSV columns used to estimate fill % for this signal */
  cols: string[];
}[] = [
  { key: "image", label: "Photo", path: "case.photo", cols: ["photo", "photo_url"] },
  { key: "lat,lon", label: "Coordinates", path: "case.lat / case.lon", cols: ["capture_lat", "capture_lon"] },
  { key: "timestamp", label: "Timestamp", path: "case.timestamp", cols: ["timestamp"] },
  { key: "ocr_text", label: "OCR text", path: "case.ocr_text", cols: ["caption_ondevice"] },
  { key: "vlm_caption", label: "VLM caption", path: "case.vlm_caption", cols: ["vlm_caption"] },
  {
    key: "nearby_candidates",
    label: "Nearby candidates",
    path: "case.nearby_candidates",
    cols: ["app_nearby_top1", "app_nearby_n_wide"],
  },
  {
    key: "city,country,address",
    label: "Geocode",
    path: "case.geocode",
    cols: ["city", "country", "address"],
  },
];

const RECOMMENDED = new Set(["image", "lat,lon", "ocr_text", "nearby_candidates"]);
const MINIMAL = new Set(["image", "lat,lon"]);

const DEFAULT_SCRIPT = `"""Baseline: pick the nearest MapKit candidate.

Contract: define predict(case) -> str (predicted place name), or "" to abstain.
\`case\` only exposes the input signals selected in the UI; it never contains GT.
"""


def predict(case):
    candidates = case.get("nearby_candidates") or []
    if not candidates:
        return ""
    return candidates[0].get("name") or ""
`;

function Stepper({ step }: { step: number }) {
  return (
    <div className={styles.stepper}>
      {STEPS.map((label, i) => (
        <div key={label} className={styles.stepGroup}>
          <span className={`${styles.stepNum} ${i <= step ? styles.stepActive : ""}`}>{i + 1}</span>
          <span className={`${styles.stepLabel} ${i === step ? styles.stepLabelActive : ""}`}>
            {label}
          </span>
          {i < STEPS.length - 1 && <span className={styles.connector} />}
        </div>
      ))}
    </div>
  );
}

function fillFor(schema: SchemaField[] | undefined, fill: Record<string, number> | undefined, cols: string[]): number {
  if (fill) {
    const vals = cols.map((c) => fill[c] ?? 0).filter((n) => n > 0);
    if (vals.length) return Math.max(...vals);
  }
  if (schema) {
    for (const s of schema) {
      if (s.cols.some((c) => cols.includes(c))) return s.fill;
    }
  }
  return 0;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface PageData {
  overview: Overview;
  matchrate: MatchRate;
  byDataset: Record<string, MatchRate>;
  /** highest version per safe run name */
  nextVersionByName: Record<string, number>;
}

function slugifyRunName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/(?:__)?v\d+$/i, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "algorithm";
}

export default function NewRun() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const state = useAsync<PageData>(async () => {
    const [overview, matchrate, { runs }] = await Promise.all([
      api.overview(),
      api.matchrate(),
      api.runs(),
    ]);
    const byDataset: Record<string, MatchRate> = {};
    await Promise.all(
      (overview.sources || []).map(async (s) => {
        try {
          byDataset[s.key] = await api.matchrate(s.key);
        } catch {
          /* optional */
        }
      }),
    );
    const nextVersionByName: Record<string, number> = {};
    for (const r of runs) {
      const key = slugifyRunName(r.name);
      const v = typeof r.version === "number" ? r.version : 0;
      nextVersionByName[key] = Math.max(nextVersionByName[key] ?? 0, v);
    }
    return { overview, matchrate, byDataset, nextVersionByName };
  }, []);

  const [scriptText, setScriptText] = useState(DEFAULT_SCRIPT);
  const [fileName, setFileName] = useState("baseline_nearest.py");
  const [fileSize, setFileSize] = useState(new Blob([DEFAULT_SCRIPT]).size);
  const [runName, setRunName] = useState("baseline-nearest");
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [scopeAll, setScopeAll] = useState(true);
  const [scopeKeys, setScopeKeys] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultMsg, setResultMsg] = useState<string | null>(null);

  const overview = state.status === "ready" ? state.data.overview : null;
  const matchrate = state.status === "ready" ? state.data.matchrate : null;
  const byDataset = state.status === "ready" ? state.data.byDataset : {};
  const total = overview?.total ?? 0;
  const sources = overview?.sources ?? [];

  // default scope keys once sources load
  const activeScope = useMemo(() => {
    if (scopeAll) return new Set(sources.map((s) => s.key));
    if (scopeKeys.size) return scopeKeys;
    return new Set(sources.map((s) => s.key));
  }, [scopeAll, scopeKeys, sources]);

  const fields = useMemo(() => {
    const schema = overview?.schema;
    const fill = overview?.fill;
    return SIGNAL_PARAMS.map((p) => ({
      ...p,
      fill: fillFor(schema, fill, p.cols),
    }));
  }, [overview]);

  const presets = useMemo(
    () => [
      { id: "recommended", label: "Recommended", members: fields.filter((f) => RECOMMENDED.has(f.key)) },
      { id: "everything", label: "Everything", members: fields },
      { id: "minimal", label: "Minimal", members: fields.filter((f) => MINIMAL.has(f.key)) },
    ],
    [fields],
  );

  const active = selected ?? new Set(presets[0].members.map((f) => f.key));
  const applyPreset = (members: typeof fields) => setSelected(new Set(members.map((f) => f.key)));
  const toggle = (key: string) => {
    const next = new Set(active);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };

  const selectedFields = fields.filter((f) => active.has(f.key));
  // Real eligibility is GT/provider based (matchrate), not min(fill).
  // Input fill only describes signal availability for predict(case).
  const eligible = useMemo(() => {
    if (!matchrate) return 0;
    if (scopeAll || activeScope.size === sources.length) {
      return matchrate.n ?? matchrate.eligible ?? 0;
    }
    let sum = 0;
    for (const key of activeScope) {
      const m = byDataset[key];
      sum += m?.n ?? m?.eligible ?? 0;
    }
    return sum;
  }, [matchrate, scopeAll, activeScope, sources.length, byDataset]);

  const binding = selectedFields.length
    ? selectedFields.reduce((a, b) => (a.fill <= b.fill ? a : b))
    : null;
  const eligPct = total > 0 ? Math.round((eligible / total) * 100) : 0;

  const activePresetId = presets.find(
    (p) => p.members.length === active.size && p.members.every((f) => active.has(f.key)),
  )?.id;

  const onPickFile = async (file: File | null) => {
    if (!file) return;
    const text = await file.text();
    setScriptText(text);
    setFileName(file.name);
    setFileSize(file.size);
    const base = file.name.replace(/\.(py|js|sh|rs|c)$/i, "");
    if (base) setRunName(slugifyRunName(base));
  };

  const stableName = slugifyRunName(runName);
  const nextVer =
    (state.status === "ready" ? state.data.nextVersionByName[stableName] ?? 0 : 0) + 1;

  const toggleDataset = (key: string) => {
    setScopeAll(false);
    setScopeKeys((prev) => {
      const base = prev.size ? new Set(prev) : new Set(sources.map((s) => s.key));
      if (base.has(key)) base.delete(key);
      else base.add(key);
      if (base.size === 0) return new Set(sources.map((s) => s.key));
      if (base.size === sources.length) {
        setScopeAll(true);
        return new Set();
      }
      return base;
    });
  };

  const canRun =
    !!scriptText.trim() &&
    !!runName.trim() &&
    active.size > 0 &&
    activeScope.size > 0 &&
    !running;

  const onRun = async () => {
    if (!canRun) return;
    setRunning(true);
    setError(null);
    setResultMsg(null);
    try {
      const scope =
        scopeAll || activeScope.size === sources.length
          ? "all"
          : [...activeScope].join(",");
      const res = await api.submitRun({
        name: stableName,
        script_text: scriptText,
        lang: "python",
        scope,
        mode: "exact",
        params: [...active],
        save_mode: "auto",
      });
      const acc = res.metrics?.accuracy_pct;
      setResultMsg(
        `Run saved: ${res.name} · v${res.version}` +
          (acc != null ? ` · ${acc}% strict` : "") +
          ` · ${res.n_cases ?? res.metrics?.n_eligible ?? "?"} cases`,
      );
      navigate(`/results?name=${encodeURIComponent(res.name)}&version=${res.version}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className={styles.main}>
      <div className={styles.titles}>
        <p className={`sectionLabel ${styles.kicker}`}>Run → Score → Inspect</p>
        <h1 className={styles.h1}>New run</h1>
        <p className={styles.sub}>
          Attach a prediction script, choose the inputs it receives, and score it against ground truth.
        </p>
      </div>

      <Stepper step={running ? 2 : scriptText ? 1 : 0} />

      {/* 1 · Algorithm */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>1 · Algorithm</span>
          <span className={styles.headHint}>— one function: predict(case) → place name</span>
        </div>
        <div className={styles.algoRow}>
          <div
            className={styles.dropzone}
            role="button"
            tabIndex={0}
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileRef.current?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              void onPickFile(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <span className={styles.dropIcon}>⬆</span>
            <span className={styles.dropTitle}>Drop your script — or click to browse</span>
            <span className={styles.dropTypes}>.py · predict(case) → str</span>
            <input
              ref={fileRef}
              type="file"
              accept=".py,.js,.sh,.txt,text/x-python,text/plain"
              hidden
              onChange={(e) => void onPickFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className={styles.attached}>
            <div className={styles.fileRow}>
              <span>📄</span>
              <span className={styles.fileName}>{fileName}</span>
              <span className={styles.fileSize}>{formatBytes(fileSize)}</span>
            </div>
            <code className={styles.signature}>def predict(case) → str</code>
            <label className={styles.headHint} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              Run name (stable slug · auto version)
              <input
                value={runName}
                onChange={(e) => setRunName(e.target.value)}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 13,
                  padding: "6px 10px",
                  borderRadius: 6,
                  border: "1px solid var(--border-default)",
                  background: "var(--bg-panel)",
                  color: "var(--text-primary)",
                }}
              />
              <span>
                will save as <code>{stableName}__v{nextVer}.json</code>
              </span>
            </label>
            <div className={styles.fileActions}>
              <button
                type="button"
                className={styles.linkAccent}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, font: "inherit" }}
                onClick={() => {
                  setScriptText(DEFAULT_SCRIPT);
                  setFileName("baseline_nearest.py");
                  setFileSize(new Blob([DEFAULT_SCRIPT]).size);
                  setRunName("baseline-nearest");
                }}
              >
                Reset to baseline
              </button>
              <button
                type="button"
                className={styles.linkMuted}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, font: "inherit" }}
                onClick={() => fileRef.current?.click()}
              >
                Replace file
              </button>
            </div>
          </div>
        </div>
        <details style={{ marginTop: 4 }}>
          <summary className={styles.headHint} style={{ cursor: "pointer" }}>
            Preview script ({scriptText.split("\n").length} lines)
          </summary>
          <pre
            style={{
              marginTop: 8,
              maxHeight: 220,
              overflow: "auto",
              padding: 12,
              background: "var(--bg-subtle)",
              borderRadius: 8,
              fontSize: 11.5,
              fontFamily: "var(--font-mono)",
              color: "var(--text-secondary)",
              whiteSpace: "pre-wrap",
            }}
          >
            {scriptText}
          </pre>
        </details>
      </section>

      {/* 2 · Inputs */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={`sectionLabel ${styles.stepTag}`}>2 · Inputs</span>
          <span className={styles.headHint}>— signals exposed to predict(case); never includes GT</span>
        </div>

        {state.status === "loading" && <p className={styles.headHint}>Loading fields…</p>}
        {state.status === "error" && (
          <p className={styles.headHint}>Couldn’t load fields — {state.error.message}</p>
        )}

        {state.status === "ready" && (
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
                      <span className={styles.chipName}>{f.label}</span>
                      <span className={styles.chipPath}>{f.path}</span>
                      <span className={styles.chipSpacer} />
                      {sparse && (
                        <span className={styles.warnText}>⚠ {Math.max(0, total - f.fill)} missing</span>
                      )}
                      <span className={sparse ? styles.warnPct : styles.chipPct}>{cov}%</span>
                    </button>
                  );
                })}
              </div>
              <div className={styles.eligibility}>
                <p className={styles.eligLabel}>Eligible cases (scored cohort)</p>
                <div className={styles.eligValueRow}>
                  <span className={styles.eligValue}>{eligible.toLocaleString()}</span>
                  <span className={styles.eligOf}>
                    / {total.toLocaleString()} ({eligPct}%)
                  </span>
                </div>
                <ProgressBar value={total > 0 ? eligible / total : 0} width="100%" />
                <p className={styles.eligNote}>
                  Eligibility is GT-canonical · MapKit provider · non-POI excluded — same rules as
                  match-rate. Input selection only controls what predict() sees
                  {binding ? `; sparsest signal is ${binding.label} (${Math.round((binding.fill / Math.max(1, total)) * 100)}% fill)` : ""}.
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
              {sources.map((s) => {
                const on = activeScope.has(s.key);
                const elig = byDataset[s.key]?.n ?? byDataset[s.key]?.eligible;
                return (
                  <button
                    key={s.key}
                    type="button"
                    className={`${styles.dataset} ${on ? styles.datasetOn : ""}`}
                    onClick={() => toggleDataset(s.key)}
                    style={{ cursor: "pointer" }}
                  >
                    {on ? "✓ " : ""}
                    {s.key} · {s.count}
                    {elig != null ? ` · elig ${elig}` : ""}
                  </button>
                );
              })}
            </div>
            <p className={styles.fieldHint}>
              {eligible.toLocaleString()} eligible with current scope · mode exact
            </p>
          </div>
          <div className={styles.scopeSpacer} />
          <div className={styles.runCol}>
            <Button kind="primary" disabled={!canRun} loading={running} onClick={() => void onRun()}>
              ▶&nbsp;&nbsp;Run evaluation
            </Button>
            <span className={styles.runHint}>
              {running
                ? "Scoring in progress — this can take a few minutes for the full cohort…"
                : "Runs predict() on every eligible case and saves a versioned result"}
            </span>
            {error && (
              <p className={styles.warnText} style={{ maxWidth: 280 }}>
                ⚠ {error}
              </p>
            )}
            {resultMsg && (
              <p className={styles.headHint} style={{ maxWidth: 280 }}>
                ✓ {resultMsg}
              </p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
