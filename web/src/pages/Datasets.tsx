import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../components/Button";
import {
  api,
  relTime,
  type DatasetInfo,
  type Job,
  type MatchRate,
  type SignalInfo,
} from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./Datasets.module.css";

type Tone = "success" | "warning" | "danger";

interface Meter {
  label: string;
  pct: number;
  tone: Tone;
  /** secondary line under the % (e.g. "90 text / 216 ran") */
  hint?: string;
}

const SIGNAL_ORDER = [
  "exif",
  "ocr",
  "mapkit_nearby",
  "gt_mapkit",
  "gt_kakao",
  "geocode",
  "vlm_caption",
];

const RERUN_STEPS = [
  { id: "exif", label: "EXIF" },
  { id: "ocr", label: "OCR" },
  { id: "mapkit_nearby", label: "MapKit nearby" },
  { id: "gt_mapkit", label: "GT MapKit" },
  { id: "gt_kakao", label: "GT Kakao" },
];

const GT_LABEL: Record<string, string> = {
  canonical: "Scoreable (canonical)",
  similar: "Similar only (SIM)",
  not_found: "Not in MapKit",
  kor: "Korea holdout",
  empty: "Empty GT cell",
};

function toneFor(pct: number): Tone {
  if (pct >= 90) return "success";
  if (pct === 0) return "danger";
  return "warning";
}

function fillColor(pct: number): string {
  if (pct >= 90) return "var(--success-fg)";
  if (pct === 0) return "var(--danger-fg)";
  return "var(--warning-fg)";
}

function breakdownCount(sig: SignalInfo | undefined, key: string): number {
  if (!sig?.label_breakdown) return 0;
  const item = sig.label_breakdown.items?.find((i) => i.key === key);
  if (item) return item.count;
  return sig.label_breakdown.excluded?.[key] ?? 0;
}

/** Compact meters users glance at in the closed row. */
function metersFor(ds: DatasetInfo): Meter[] {
  const total = ds.count || 1;
  const exif = ds.signals.exif;
  const ocr = ds.signals.ocr;
  const nearby = ds.signals.mapkit_nearby;
  const gt = ds.signals.gt_mapkit;

  const gps =
    exif?.coverage_metrics?.find((m) => m.key === "coordinates")?.pct ?? exif?.pct ?? 0;
  const ocrText = ocr?.pct ?? 0;
  const ocrRan = ocr?.processed_pct;
  const near = nearby?.pct ?? 0;
  const canonical = breakdownCount(gt, "canonical");
  const scoreablePct = Math.round((100 * canonical) / total);

  return [
    { label: "GPS", pct: gps, tone: toneFor(gps) },
    {
      label: "OCR",
      pct: ocrText,
      tone: toneFor(ocrText),
      hint: ocrRan != null ? `${ocrRan}% ran` : undefined,
    },
    { label: "NEARBY", pct: near, tone: toneFor(near) },
    {
      label: "SCOREABLE",
      pct: scoreablePct,
      tone: toneFor(scoreablePct),
      hint: `${canonical}/${ds.count}`,
    },
  ];
}

function metaLine(ds: DatasetInfo): string {
  const parts = [`${ds.count.toLocaleString()} rows`];
  if (ds.source_type) parts.push(ds.source_type);
  if (ds.label) parts.push(ds.label);
  if (!ds.known) parts.push("unregistered source");
  return parts.join(" · ");
}

function CoverageMeter({ meter }: { meter: Meter }) {
  const color =
    meter.tone === "danger"
      ? "var(--danger-fg)"
      : meter.tone === "warning"
        ? "var(--warning-fg)"
        : "var(--success-fg)";
  return (
    <div className={styles.meter}>
      <div className={styles.meterHead}>
        <span className={styles.meterLabel}>{meter.label}</span>
        <span className={styles.meterPct} style={{ color }}>
          {meter.pct}%
        </span>
      </div>
      <div className={styles.meterTrack}>
        <div className={styles.meterFill} style={{ width: `${meter.pct}%`, background: color }} />
      </div>
      {meter.hint && <span className={styles.meterHint}>{meter.hint}</span>}
    </div>
  );
}

function orderedSignals(signals: Record<string, SignalInfo>): [string, SignalInfo][] {
  const keys = Object.keys(signals);
  const ordered = SIGNAL_ORDER.filter((k) => k in signals);
  const rest = keys.filter((k) => !SIGNAL_ORDER.includes(k)).sort();
  return [...ordered, ...rest].map((k) => [k, signals[k]]);
}

function jobTitle(j: Job): string {
  const ds = (j.params?.dataset as string | undefined) || "";
  return ds ? `${j.step} — ${ds}` : j.step;
}

function jobWhen(j: Job): string {
  if (j.status === "running") {
    const pct = j.progress?.pct;
    const done = j.progress?.done;
    const total = j.progress?.total;
    const parts: string[] = [];
    if (pct != null) parts.push(`${Math.round(pct)}%`);
    if (done != null && total != null) parts.push(`${done}/${total}`);
    if (j.elapsed_s != null) parts.push(`${Math.round(j.elapsed_s)}s`);
    return parts.length ? parts.join(" · ") : "running…";
  }
  if (j.finished) {
    const iso = new Date(j.finished * 1000).toISOString();
    return `${j.status} · ${relTime(iso)}`;
  }
  if (j.started) {
    return `${j.status} · started ${relTime(new Date(j.started * 1000).toISOString())}`;
  }
  return j.status;
}

function signalDetailLines(sig: SignalInfo, total: number): string[] {
  const lines: string[] = [];
  lines.push(`${sig.fill.toLocaleString()} / ${total.toLocaleString()} ${sig.result_label?.toLowerCase() || "filled"}`);
  if (sig.empty > 0) lines.push(`${sig.empty.toLocaleString()} empty`);
  if (sig.processed != null) {
    lines.push(
      `${sig.processed.toLocaleString()} processed` +
        (sig.unprocessed != null ? ` · ${sig.unprocessed.toLocaleString()} unprocessed` : ""),
    );
  }
  for (const m of sig.coverage_metrics || []) {
    lines.push(`${m.label}: ${m.count.toLocaleString()} (${m.pct}%)`);
  }
  if (sig.status && sig.status !== "ok") lines.push(`status: ${sig.status}`);
  return lines;
}

function CoveragePanel({
  ds,
  matchrate,
  matchrateStatus,
}: {
  ds: DatasetInfo;
  matchrate: MatchRate | null;
  matchrateStatus: "loading" | "ready" | "error";
}) {
  const total = ds.count;
  const signalEntries = orderedSignals(ds.signals);
  const gt = ds.signals.gt_mapkit;
  const ocr = ds.signals.ocr;
  const nearby = ds.signals.mapkit_nearby;
  const exif = ds.signals.exif;

  const canonical = breakdownCount(gt, "canonical");
  const similar = breakdownCount(gt, "similar");
  const notFound = breakdownCount(gt, "not_found");
  const kor = breakdownCount(gt, "kor");
  const eligible = matchrate?.n ?? matchrate?.eligible;
  const rank1 = matchrate?.rank1_rate;
  const miss = matchrate?.miss_rate ?? (matchrate?.miss != null && eligible ? matchrate.miss / eligible : undefined);

  const gpsPct =
    exif?.coverage_metrics?.find((m) => m.key === "coordinates")?.pct ?? exif?.pct ?? 0;
  const timePct =
    exif?.coverage_metrics?.find((m) => m.key === "timestamp")?.pct ?? 0;

  const headlines: { label: string; value: string; note: string; tone?: Tone }[] = [
    {
      label: "Rows",
      value: total.toLocaleString(),
      note: ds.source_type || ds.label || "dataset size",
    },
    {
      label: "Scoreable GT",
      value: `${canonical.toLocaleString()}`,
      note: `${Math.round((100 * canonical) / Math.max(1, total))}% of rows · MapKit canonical`,
      tone: toneFor(Math.round((100 * canonical) / Math.max(1, total))),
    },
    {
      label: "Eval eligible",
      value:
        matchrateStatus === "loading"
          ? "…"
          : eligible != null
            ? eligible.toLocaleString()
            : "—",
      note:
        matchrateStatus === "error"
          ? "couldn’t load match-rate"
          : "pass GT/provider filters (headline cohort)",
      tone: eligible != null ? toneFor(Math.round((100 * eligible) / Math.max(1, total))) : undefined,
    },
    {
      label: "Retrieval ceiling",
      value:
        rank1 != null
          ? `${(rank1 * 100).toFixed(0)}% R1`
          : matchrateStatus === "loading"
            ? "…"
            : "—",
      note:
        miss != null
          ? `miss ${(miss * 100).toFixed(0)}% · GT absent from candidates`
          : "rank-1 hit rate on eligible",
    },
  ];

  const blockers: string[] = [];
  if (notFound > 0) blockers.push(`${notFound} NON_MAPKIT (reconcile or exclude)`);
  if (kor > 0) blockers.push(`${kor} Korea holdout (needs Kakao)`);
  if (similar > 0) blockers.push(`${similar} SIM_MAPKIT only (not strict-eligible)`);
  if ((ocr?.pct ?? 0) < 50 && (ocr?.processed_pct ?? 0) >= 90) {
    blockers.push(`OCR found text on only ${ocr?.pct ?? 0}% (many blank photos)`);
  }
  if ((nearby?.empty ?? 0) > 0) {
    blockers.push(`${nearby?.empty} rows without nearby candidates`);
  }
  if ((exif?.pct ?? 100) < 100) {
    blockers.push(`${exif?.empty ?? 0} rows missing EXIF GPS/time`);
  }
  if (ds.signals.vlm_caption?.status === "not_implemented" || (ds.signals.vlm_caption?.pct ?? 0) === 0) {
    blockers.push("VLM caption not extracted");
  }

  return (
    <div className={styles.coveragePanel}>
      <div className={styles.headTiles}>
        {headlines.map((h) => (
          <div key={h.label} className={styles.headTile}>
            <span className={styles.headTileLabel}>{h.label}</span>
            <span
              className={styles.headTileValue}
              style={h.tone ? { color: fillColor(h.tone === "success" ? 95 : h.tone === "danger" ? 0 : 50) } : undefined}
            >
              {h.value}
            </span>
            <span className={styles.headTileNote}>{h.note}</span>
          </div>
        ))}
      </div>

      {/* GT breakdown — what actually gates scoring */}
      {gt?.label_breakdown && (
        <div className={styles.block}>
          <p className={styles.miniLabel}>Ground-truth readiness (MapKit)</p>
          <div className={styles.chipRow}>
            {gt.label_breakdown.items.map((item) => (
              <span key={item.key} className={styles.statChip}>
                <span className={styles.statChipLabel}>{GT_LABEL[item.key] || item.key}</span>
                <span className={styles.statChipValue}>
                  {item.count.toLocaleString()} · {item.pct}%
                </span>
              </span>
            ))}
            {Object.entries(gt.label_breakdown.excluded || {}).map(([k, v]) =>
              v > 0 ? (
                <span key={k} className={`${styles.statChip} ${styles.statChipMuted}`}>
                  <span className={styles.statChipLabel}>{GT_LABEL[k] || k}</span>
                  <span className={styles.statChipValue}>{v.toLocaleString()}</span>
                </span>
              ) : null,
            )}
          </div>
        </div>
      )}

      {/* Input signal health */}
      <div className={styles.block}>
        <p className={styles.miniLabel}>Input signals users care about</p>
        <div className={styles.chipRow}>
          <span className={styles.statChip}>
            <span className={styles.statChipLabel}>GPS coordinates</span>
            <span className={styles.statChipValue}>{gpsPct}%</span>
          </span>
          <span className={styles.statChip}>
            <span className={styles.statChipLabel}>Capture time</span>
            <span className={styles.statChipValue}>{timePct}%</span>
          </span>
          <span className={styles.statChip}>
            <span className={styles.statChipLabel}>OCR text found</span>
            <span className={styles.statChipValue}>
              {ocr?.pct ?? 0}%
              {ocr?.processed_pct != null ? ` · ran ${ocr.processed_pct}%` : ""}
            </span>
          </span>
          <span className={styles.statChip}>
            <span className={styles.statChipLabel}>Nearby candidates</span>
            <span className={styles.statChipValue}>
              {nearby?.pct ?? 0}% · {nearby?.fill?.toLocaleString() ?? 0} rows
            </span>
          </span>
        </div>
      </div>

      {blockers.length > 0 && (
        <div className={styles.blockers}>
          <p className={styles.miniLabel}>What limits scoring right now</p>
          <ul className={styles.blockerList}>
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.block}>
        <p className={styles.miniLabel}>All enrichment signals · {total.toLocaleString()} rows</p>
        <div className={styles.sigList}>
          {signalEntries.map(([key, sig]) => {
            const color = fillColor(sig.pct);
            const lines = signalDetailLines(sig, total);
            return (
              <div key={key} className={styles.sigRow}>
                <div className={styles.sigMain}>
                  <div className={styles.colName}>
                    <span className={styles.colTitle}>{sig.label}</span>
                    <span className={styles.colId}>{key}</span>
                  </div>
                  <div className={styles.colBarWrap}>
                    <div className={styles.colTrack}>
                      <div className={styles.colFill} style={{ width: `${sig.pct}%`, background: color }} />
                    </div>
                    <span className={styles.colPct} style={{ color }}>
                      {sig.pct}%
                    </span>
                  </div>
                </div>
                <div className={styles.sigMeta}>
                  {lines.map((line) => (
                    <span key={line} className={styles.methodChip}>
                      {line}
                    </span>
                  ))}
                  {sig.label_breakdown?.items.map((item) => (
                    <span key={item.key} className={styles.methodChip}>
                      {item.key}: {item.count} ({item.pct}%)
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function Datasets() {
  const data = useAsync(() => api.datasets(), []);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [steps, setSteps] = useState<Record<string, string>>({});
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  /** Job / rerun target — independent of coverage expand */
  const [selected, setSelected] = useState<string>("");
  /** Coverage accordion — null means all collapsed (default) */
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [rerunStep, setRerunStep] = useState("ocr");
  const [onlyEmpty, setOnlyEmpty] = useState(true);
  const [jobMsg, setJobMsg] = useState<string | null>(null);
  const [jobErr, setJobErr] = useState<string | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);
  const [templateBusy, setTemplateBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const matchrate = useAsync(
    () => (openKey ? api.matchrate(openKey) : Promise.resolve(null)),
    [openKey],
  );

  const refreshJobs = useCallback(async () => {
    try {
      const res = await api.jobs();
      setJobs([...res.jobs].sort((a, b) => (b.started || 0) - (a.started || 0)));
      setSteps(res.steps || {});
      setActiveJobId(res.active);
    } catch {
      /* keep previous */
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (!activeJobId) return;
    const t = window.setInterval(() => {
      void refreshJobs();
    }, 2000);
    return () => window.clearInterval(t);
  }, [activeJobId, refreshJobs]);

  const datasets = data.status === "ready" ? data.data.datasets : [];
  // Jobs target: first dataset if none chosen — does not open coverage
  const activeKey = selected || datasets[0]?.key || "";
  const active = datasets.find((d) => d.key === activeKey) ?? datasets[0];
  const openDs = openKey ? datasets.find((d) => d.key === openKey) : null;

  useEffect(() => {
    if (!selected && datasets[0]) setSelected(datasets[0].key);
  }, [datasets, selected]);

  const running = jobs.filter((j) => j.status === "running");
  const doneJobs = jobs.filter((j) => j.status !== "running").slice(0, 8);

  const startRerun = async () => {
    if (!active) return;
    setJobErr(null);
    setJobMsg(null);
    const stepStatus = steps[rerunStep];
    if (stepStatus && stepStatus !== "ok") {
      setJobErr(`${rerunStep} is unavailable: ${stepStatus}`);
      return;
    }
    try {
      const res = await api.startJob(rerunStep, {
        dataset: active.key,
        only_empty: onlyEmpty,
      });
      setJobMsg(`Started ${res.step} (job ${res.job_id.slice(0, 8)}…)`);
      await refreshJobs();
      data.reload();
    } catch (e) {
      setJobErr(e instanceof Error ? e.message : String(e));
    }
  };

  const onIngestFiles = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setIngestBusy(true);
    setIngestMsg(null);
    setJobErr(null);
    try {
      const validation = await api.validateUpload(file);
      if (!validation.ok) {
        const n = validation.errors?.length ?? 0;
        setJobErr(`Validation failed (${n} error${n === 1 ? "" : "s"}). Fix the ZIP and retry.`);
        return;
      }
      const nameGuess = file.name.replace(/\.zip$/i, "") || undefined;
      const res = await api.ingest(file, nameGuess);
      setIngestMsg(`Ingest started (job ${res.job_id.slice(0, 8)}…). Rows appear as the job finishes.`);
      await refreshJobs();
    } catch (e) {
      setJobErr(e instanceof Error ? e.message : String(e));
    } finally {
      setIngestBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const toggleCoverage = (key: string) => {
    setSelected(key);
    setOpenKey((prev) => (prev === key ? null : key));
  };

  if (data.status === "loading") {
    return <main className={styles.main}>Loading datasets…</main>;
  }
  if (data.status === "error") {
    return (
      <main className={styles.main}>
        Couldn’t load datasets — {data.error.message}
        <button type="button" className={styles.logLink} onClick={data.reload} style={{ marginLeft: 12 }}>
          Retry
        </button>
      </main>
    );
  }

  if (!active) {
    return (
      <main className={styles.main}>
        <header className={styles.header}>
          <div className={styles.titles}>
            <p className={`sectionLabel ${styles.kicker}`}>Data</p>
            <h1 className={styles.h1}>Datasets</h1>
            <p className={styles.sub}>No datasets loaded yet. Drop a ZIP below to ingest.</p>
          </div>
        </header>
      </main>
    );
  }

  const totalRows = datasets.reduce((s, d) => s + d.count, 0);

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Data</p>
          <h1 className={styles.h1}>Datasets</h1>
          <p className={styles.sub}>
            {totalRows.toLocaleString()} rows across {datasets.length} dataset
            {datasets.length === 1 ? "" : "s"} · live from eval CSV · coverage collapsed by default
          </p>
        </div>
        <Button
          kind="secondary"
          disabled={templateBusy}
          onClick={() => {
            setTemplateBusy(true);
            setJobErr(null);
            void api
              .downloadTemplate()
              .then(() => setIngestMsg("Downloaded poi-dataset-template.zip — fill it and re-upload."))
              .catch((e) => setJobErr(e instanceof Error ? e.message : String(e)))
              .finally(() => setTemplateBusy(false));
          }}
        >
          {templateBusy ? "Downloading…" : "Download template"}
        </Button>
        <Button kind="primary" onClick={() => fileRef.current?.click()} loading={ingestBusy}>
          ＋&nbsp;&nbsp;Add dataset
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => void onIngestFiles(e.target.files)}
        />
      </header>

      {(jobErr || jobMsg || ingestMsg) && (
        <p className={styles.ceiling} style={jobErr ? undefined : { borderColor: "var(--success-fg)" }}>
          {jobErr ? `⚠ ${jobErr}` : `✓ ${jobMsg || ingestMsg}`}
        </p>
      )}

      <div className={styles.list}>
        {datasets.map((ds) => {
          const meters = metersFor(ds);
          const isOpen = openKey === ds.key;
          const isSelected = active.key === ds.key;
          return (
            <div key={ds.key} className={styles.dsBlock}>
              <div
                className={`${styles.dsRow} ${isSelected ? styles.dsRowActive : ""} ${isOpen ? styles.dsRowOpen : ""}`}
              >
                <button
                  type="button"
                  className={styles.dsMain}
                  onClick={() => setSelected(ds.key)}
                  aria-pressed={isSelected}
                >
                  <div className={styles.dsName}>
                    <p className={styles.dsTitle}>{ds.key}</p>
                    <p className={styles.dsMeta}>{metaLine(ds)}</p>
                  </div>
                  {meters.map((m) => (
                    <CoverageMeter key={m.label} meter={m} />
                  ))}
                  <span className={styles.dsSpacer} />
                </button>
                <button
                  type="button"
                  className={styles.dsHintBtn}
                  aria-expanded={isOpen}
                  onClick={() => toggleCoverage(ds.key)}
                >
                  {isOpen ? "Hide coverage ↑" : "Show coverage ↓"}
                </button>
              </div>
              {isOpen && openDs && openDs.key === ds.key && (
                <CoveragePanel
                  ds={openDs}
                  matchrate={matchrate.status === "ready" ? matchrate.data : null}
                  matchrateStatus={
                    matchrate.status === "loading"
                      ? "loading"
                      : matchrate.status === "error"
                        ? "error"
                        : "ready"
                  }
                />
              )}
            </div>
          );
        })}
      </div>

      <div className={styles.bottom}>
        <div className={styles.jobs}>
          <p className={styles.miniLabel}>Background jobs · target {active.key}</p>

          <div className={styles.rerunControls}>
            <span className={styles.rerunLabel}>RERUN</span>
            <label className={styles.select}>
              step:{" "}
              <select
                value={rerunStep}
                onChange={(e) => setRerunStep(e.target.value)}
                style={{
                  border: "none",
                  background: "transparent",
                  font: "inherit",
                  color: "inherit",
                  cursor: "pointer",
                }}
              >
                {RERUN_STEPS.map((s) => (
                  <option key={s.id} value={s.id} disabled={!!(steps[s.id] && steps[s.id] !== "ok")}>
                    {s.label}
                    {steps[s.id] && steps[s.id] !== "ok" ? " (unavailable)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className={styles.select}>dataset: {active.key}</span>
            <button
              type="button"
              className={styles.checkRow}
              onClick={() => setOnlyEmpty((v) => !v)}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
            >
              <span className={styles.checkBox}>{onlyEmpty ? "✓" : ""}</span>
              unprocessed only
            </button>
            <button
              type="button"
              className={styles.rerunBtn}
              onClick={() => void startRerun()}
              disabled={!!activeJobId}
              title={activeJobId ? "A job is already running" : "Start enrichment job"}
            >
              ▶ Rerun
            </button>
          </div>

          {running.length === 0 && (
            <p className={styles.activeNote} style={{ marginTop: 8 }}>
              No job running. One job runs at a time.
            </p>
          )}

          {running.map((j) => {
            const pct = Math.min(100, Math.max(0, j.progress?.pct ?? 0));
            const done = j.progress?.done;
            const total = j.progress?.total;
            return (
              <div key={j.id} className={styles.activeJob}>
                <div className={styles.activeHead}>
                  <span className={styles.jobDot} style={{ background: "var(--warning-fg)" }} />
                  <span className={styles.activeName}>{jobTitle(j)}</span>
                  <span className={styles.activeSpacer} />
                  <span className={styles.activeStat}>
                    {pct > 0 ? `${Math.round(pct)}%` : "running"}
                    {done != null && total != null ? ` · ${done}/${total}` : ""}
                    {j.elapsed_s != null ? ` · ${Math.round(j.elapsed_s)}s` : ""}
                  </span>
                </div>
                <div className={styles.jobTrack}>
                  <div className={styles.jobFill} style={{ width: `${pct || 8}%` }} />
                </div>
                <p className={styles.activeNote}>
                  Keep working — coverage updates when the job finishes. One job runs at a time.
                </p>
              </div>
            );
          })}

          {doneJobs.map((j) => (
            <div key={j.id} className={styles.doneRow}>
              <span
                className={styles.jobDot}
                style={{
                  background:
                    j.status === "done" || j.status === "ok"
                      ? "var(--success-fg)"
                      : "var(--danger-fg)",
                }}
              />
              <span className={styles.doneName}>{jobTitle(j)}</span>
              <span className={styles.activeSpacer} />
              <span className={styles.doneWhen}>{jobWhen(j)}</span>
            </div>
          ))}
        </div>

        <div className={styles.ingest}>
          <p className={styles.miniLabel}>Add a dataset</p>
          <div
            className={styles.dropzone}
            role="button"
            tabIndex={0}
            onClick={() => !ingestBusy && fileRef.current?.click()}
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
              if (!ingestBusy) void onIngestFiles(e.dataTransfer.files);
            }}
          >
            <span className={styles.dropIcon}>⬆</span>
            <span className={styles.dropTitle}>
              {ingestBusy ? "Uploading…" : "Drop a dataset ZIP"}
            </span>
            <span className={styles.dropSub}>
              capture time required (manifest or EXIF) · validated before write
            </span>
          </div>
          <div className={styles.steps}>
            {[
              "Validate structure, photos, and capture time",
              "Ingest rows + photos (local content ids)",
              "Enrichment fills EXIF · OCR · nearby · GT",
            ].map((s, i) => (
              <div key={s} className={styles.stepRow}>
                <span className={styles.stepNum}>{i + 1}.</span>
                <span className={styles.stepText}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
