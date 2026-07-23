import { useState } from "react";
import MapPicker from "../components/MapPicker";
import { api, type ReconcileCandidate, type ReconcileCase } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./ReconcileMapKit.module.css";

const TOP_N = 5;

export default function ReconcileMapKit() {
  const [dataset, setDataset] = useState<string | null>(null);
  const queue = useAsync(() => api.reconcileQueue(dataset), [dataset]);
  const [idx, setIdx] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [history, setHistory] = useState<Array<{ index: number; saved: boolean }>>([]);
  const [choice, setChoice] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // query point (selectable) + live re-query results
  const [coord, setCoord] = useState<{ lat: number; lon: number } | null>(null);
  const [probeCands, setProbeCands] = useState<ReconcileCandidate[] | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState<string | null>(null);

  const selectDataset = (next: string | null) => {
    setDataset(next);
    setIdx(0);
    setSavedCount(0);
    setHistory([]);
    setChoice(null);
    setShowAll(false);
    setCoord(null);
    setProbeCands(null);
    setProbeMsg(null);
    setError(null);
  };

  if (queue.status === "loading") return <main className={styles.center}>Loading reconciliation queue…</main>;
  if (queue.status === "error")
    return <main className={styles.center}>Couldn’t load queue — {queue.error.message}</main>;

  const data = queue.data;
  const cases = data.cases;
  const doneBase = data.done;

  const goBack = async () => {
    const previous = history[history.length - 1];
    if (!previous) return;
    setBusy(true);
    setError(null);
    try {
      if (previous.saved) {
        const previousCase = cases[previous.index];
        await api.reconcileUndo({ dataset: previousCase.dataset, photo: previousCase.photo });
        setSavedCount((count) => Math.max(0, count - 1));
      }
      setHistory((items) => items.slice(0, -1));
      setIdx(previous.index);
      setChoice(null);
      setShowAll(false);
      setCoord(null);
      setProbeCands(null);
      setProbeMsg(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (cases.length === 0 || idx >= cases.length) {
    return (
      <main className={styles.main}>
        <Header total={data.total_non_mapkit} done={doneBase + savedCount} remaining={Math.max(0, data.remaining - savedCount)} datasets={data.datasets} selectedDataset={dataset} onDatasetChange={selectDataset} />
        <div className={styles.empty}>
          <span className={styles.emptyIcon}>✓</span>
          <p className={styles.emptyTitle}>Nothing left in this batch</p>
          <p className={styles.emptyDesc}>
            {savedCount > 0 ? `${savedCount} matches saved. ` : ""}Reload to pull the next batch.
          </p>
          <button type="button" className={styles.reloadBtn} onClick={queue.reload}>
            Reload queue
          </button>
          <button type="button" className={styles.secondary} disabled={busy || history.length === 0} onClick={goBack}>
            ← Back to previous case
          </button>
          {error && <p className={styles.error}>{error}</p>}
        </div>
      </main>
    );
  }

  const current: ReconcileCase = cases[idx];
  const caseLat = parseFloat(current.lat);
  const caseLon = parseFloat(current.lon);
  const hasCoord = Number.isFinite(caseLat) && Number.isFinite(caseLon);
  const point = coord ?? (hasCoord ? { lat: caseLat, lon: caseLon } : null);
  const moved = hasCoord && point != null && (point.lat !== caseLat || point.lon !== caseLon);

  const advance = (saved = false) => {
    setHistory((items) => [...items, { index: idx, saved }]);
    setChoice(null);
    setShowAll(false);
    setCoord(null);
    setProbeCands(null);
    setProbeMsg(null);
    setIdx((i) => i + 1);
  };

  async function save(chosen: string) {
    setBusy(true);
    setError(null);
    try {
      await api.reconcileSave({ dataset: current.dataset, photo: current.photo, gt: current.gt, chosen });
      setSavedCount((n) => n + 1);
      advance(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reprobe() {
    if (!point) return;
    setProbing(true);
    setProbeMsg(null);
    setChoice(null);
    try {
      const res = await api.mapkitProbe(point.lat, point.lon);
      if (res.ok) {
        setProbeCands(res.candidates);
        if (res.candidates.length === 0) setProbeMsg("Still nothing here — move the point and try again.");
      } else {
        setProbeMsg(res.message || "Probe failed.");
      }
    } catch (e) {
      setProbeMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  }

  const activeCands = probeCands ?? current.candidates;
  const selectedCand = choice ? activeCands.find((c) => c.name === choice) : null;
  const selectedLoc =
    selectedCand && selectedCand.lat != null && selectedCand.lon != null
      ? { lat: Number(selectedCand.lat), lon: Number(selectedCand.lon) }
      : null;
  const visible = showAll ? activeCands : activeCands.slice(0, TOP_N);
  const hiddenCount = activeCands.length - visible.length;
  const listLabel = probeCands
    ? `${probeCands.length} candidates at this point`
    : activeCands.length > 0
      ? `Pick the matching MapKit place · ${activeCands.length} candidates`
      : "No MapKit candidates at the photo location";

  return (
    <main className={styles.main}>
      <Header total={data.total_non_mapkit} done={doneBase + savedCount} remaining={Math.max(0, data.remaining - savedCount)} datasets={data.datasets} selectedDataset={dataset} onDatasetChange={selectDataset} />

      <div className={styles.progressRow}>
        <div className={styles.progressTrack}>
          <div className={styles.progressFill} style={{ width: `${((doneBase + savedCount) / Math.max(1, data.total_non_mapkit)) * 100}%` }} />
        </div>
        <span className={styles.progressText}>
          {idx + 1} of {cases.length} in this batch
        </span>
      </div>

      <div className={styles.split}>
        {/* left: the case */}
        <div className={styles.caseCol}>
          <div className={styles.photo}>
            <img className={styles.photoImg} src={current.image} alt={current.photo} loading="lazy" />
          </div>
          <div className={styles.gtBox}>
            <span className={styles.gtLabel}>Ground truth (unmatched)</span>
            <span className={styles.gtName}>{current.gt || "—"}</span>
            {current.ocr && <span className={styles.ocr}>OCR: “{current.ocr}”</span>}
            <span className={styles.dataset}>{current.dataset}</span>
          </div>
        </div>

        {/* right: map + candidates */}
        <div className={styles.pickCol}>
          {hasCoord && point ? (
            <>
              <div className={styles.mapWrap}>
                <MapPicker
                  key={current.photo}
                  photo={{ lat: caseLat, lon: caseLon }}
                  point={point}
                  selected={selectedLoc}
                  onChange={(lat, lon) => {
                    setCoord({ lat, lon });
                    setProbeCands(null);
                  }}
                />
              </div>
              <div className={styles.investRow}>
                <span className={styles.legendDot} style={{ background: "var(--warning-fg)" }} />
                <span className={styles.coordText}>photo</span>
                <span className={styles.legendDot} style={{ background: "var(--accent-default)" }} />
                <span className={styles.coordText}>
                  query {point.lat.toFixed(5)}, {point.lon.toFixed(5)}
                </span>
                {selectedLoc && (
                  <>
                    <span className={styles.legendDot} style={{ background: "var(--success-fg)" }} />
                    <span className={styles.coordText}>picked</span>
                  </>
                )}
                <span style={{ flex: 1 }} />
                {moved && (
                  <button type="button" className={styles.seeMore} onClick={() => { setCoord(null); setProbeCands(null); }}>
                    reset
                  </button>
                )}
                <button type="button" className={styles.secondary} disabled={probing} onClick={reprobe}>
                  {probing ? "Querying… (~20–30s)" : "Re-query MapKit here"}
                </button>
              </div>
            </>
          ) : (
            <p className={styles.noCand}>No coordinate for this case — can’t map or re-query.</p>
          )}

          <p className={styles.pickLabel}>{listLabel}</p>
          {probeMsg && <p className={styles.error}>{probeMsg}</p>}
          {activeCands.length > 0 && (
            <div className={styles.candList}>
              {visible.map((c, i) => {
                const on = choice === c.name;
                return (
                  <button
                    key={`${c.name}-${i}`}
                    type="button"
                    className={`${styles.cand} ${on ? styles.candOn : ""}`}
                    onClick={() => setChoice(c.name)}
                    disabled={busy}
                  >
                    <span className={styles.candRank}>{c.rank}</span>
                    <span className={styles.candName}>{c.name || "—"}</span>
                    {c.category && <span className={styles.candCat}>{c.category}</span>}
                    {c.distance != null && <span className={styles.candDist}>{Math.round(c.distance)}m</span>}
                    {on && <span className={styles.candCheck}>✓</span>}
                  </button>
                );
              })}
              {activeCands.length > TOP_N && (
                <button type="button" className={styles.seeMore} onClick={() => setShowAll((s) => !s)}>
                  {showAll ? "See fewer" : `See more (${hiddenCount})`}
                </button>
              )}
            </div>
          )}

          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button type="button" className={styles.primary} disabled={busy || !choice} onClick={() => choice && save(choice)}>
              {busy ? "Saving…" : "Save match"}
            </button>
            <button type="button" className={styles.ghost} disabled={busy} onClick={() => save("")}>
              Not in MapKit
            </button>
            <button type="button" className={styles.ghost} disabled={busy} onClick={() => advance(false)}>
              Skip
            </button>
            <button type="button" className={styles.secondary} disabled={busy || history.length === 0} onClick={goBack}>
              ← Back
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

function Header({
  total,
  done,
  remaining,
  datasets,
  selectedDataset,
  onDatasetChange,
}: {
  total: number;
  done: number;
  remaining: number;
  datasets: Array<{ name: string; total: number; done: number; remaining: number }>;
  selectedDataset: string | null;
  onDatasetChange: (dataset: string | null) => void;
}) {
  return (
    <header className={styles.header}>
      <p className={`sectionLabel ${styles.kicker}`}>Data · GT ↔ MapKit reconciliation</p>
      <h1 className={styles.h1}>Match unresolved ground truth to MapKit</h1>
      <p className={styles.sub}>
        {total} cases classified <code className={styles.code}>NON_MAPKIT</code> — GT couldn’t be
        auto-matched. Pick a candidate, or move the query point on the map and re-query MapKit.
        <span className={styles.counts}>
          {" "}
          {done} done · {remaining} remaining
        </span>
      </p>
      <label className={styles.datasetFilter}>
        <span>Dataset to reconcile</span>
        <select
          className={styles.datasetSelect}
          value={selectedDataset == null ? "all" : `dataset:${datasets.findIndex((item) => item.name === selectedDataset)}`}
          onChange={(event) => {
            const index = Number(event.target.value.slice("dataset:".length));
            onDatasetChange(event.target.value === "all" ? null : datasets[index]?.name ?? null);
          }}
        >
          <option value="all">All datasets ({datasets.reduce((sum, item) => sum + item.remaining, 0)} remaining)</option>
          {datasets.map((item, index) => (
            <option key={`${index}:${item.name}`} value={`dataset:${index}`}>
              {item.name || "(unnamed)"} ({item.remaining} remaining / {item.total} total)
            </option>
          ))}
        </select>
      </label>
    </header>
  );
}
