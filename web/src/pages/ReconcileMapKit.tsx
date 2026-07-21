import { useState } from "react";
import { api, type ReconcileCase } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./ReconcileMapKit.module.css";

export default function ReconcileMapKit() {
  const queue = useAsync(() => api.reconcileQueue(), []);
  const [idx, setIdx] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [choice, setChoice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (queue.status === "loading") {
    return <main className={styles.center}>Loading reconciliation queue…</main>;
  }
  if (queue.status === "error") {
    return <main className={styles.center}>Couldn’t load queue — {queue.error.message}</main>;
  }

  const data = queue.data;
  const cases = data.cases;
  const doneBase = data.done;

  if (cases.length === 0 || idx >= cases.length) {
    return (
      <main className={styles.main}>
        <Header total={data.total_non_mapkit} done={doneBase + savedCount} remaining={Math.max(0, data.remaining - savedCount)} />
        <div className={styles.empty}>
          <span className={styles.emptyIcon}>✓</span>
          <p className={styles.emptyTitle}>Nothing left in this batch</p>
          <p className={styles.emptyDesc}>
            {savedCount > 0 ? `${savedCount} matches saved. ` : ""}Reload to pull the next batch of
            unmatched cases.
          </p>
          <button type="button" className={styles.reloadBtn} onClick={queue.reload}>
            Reload queue
          </button>
        </div>
      </main>
    );
  }

  const current: ReconcileCase = cases[idx];

  async function save(chosen: string) {
    setBusy(true);
    setError(null);
    try {
      await api.reconcileSave({
        dataset: current.dataset,
        photo: current.photo,
        gt: current.gt,
        chosen,
      });
      setSavedCount((n) => n + 1);
      setChoice(null);
      setIdx((i) => i + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.main}>
      <Header
        total={data.total_non_mapkit}
        done={doneBase + savedCount}
        remaining={Math.max(0, data.remaining - savedCount)}
      />

      <div className={styles.progressRow}>
        <div className={styles.progressTrack}>
          <div
            className={styles.progressFill}
            style={{ width: `${((doneBase + savedCount) / Math.max(1, data.total_non_mapkit)) * 100}%` }}
          />
        </div>
        <span className={styles.progressText}>
          {idx + 1} of {cases.length} in this batch
        </span>
      </div>

      <div className={styles.split}>
        {/* left: the case */}
        <div className={styles.caseCol}>
          <div className={styles.photo}>
            <span className={styles.photoName}>{current.photo}</span>
          </div>
          <div className={styles.gtBox}>
            <span className={styles.gtLabel}>Ground truth (unmatched)</span>
            <span className={styles.gtName}>{current.gt || "—"}</span>
            {current.ocr && <span className={styles.ocr}>OCR: “{current.ocr}”</span>}
            <span className={styles.dataset}>{current.dataset}</span>
          </div>
        </div>

        {/* right: candidate picker */}
        <div className={styles.pickCol}>
          <p className={styles.pickLabel}>
            Pick the matching MapKit place · {current.candidates.length} candidates
          </p>
          <div className={styles.candList}>
            {current.candidates.length === 0 && (
              <p className={styles.noCand}>No MapKit candidates for this photo.</p>
            )}
            {current.candidates.map((c, i) => {
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
          </div>

          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={busy || !choice}
              onClick={() => choice && save(choice)}
            >
              {busy ? "Saving…" : "Save match"}
            </button>
            <button type="button" className={styles.secondary} disabled={busy} onClick={() => save("")}>
              Not in list
            </button>
            <button
              type="button"
              className={styles.ghost}
              disabled={busy}
              onClick={() => {
                setChoice(null);
                setIdx((i) => i + 1);
              }}
            >
              Skip
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

function Header({ total, done, remaining }: { total: number; done: number; remaining: number }) {
  return (
    <header className={styles.header}>
      <p className={`sectionLabel ${styles.kicker}`}>Data · GT ↔ MapKit reconciliation</p>
      <h1 className={styles.h1}>Match unresolved ground truth to MapKit</h1>
      <p className={styles.sub}>
        {total} cases classified <code className={styles.code}>NON_MAPKIT</code> — GT couldn’t be
        auto-matched to any MapKit name. Pick the right candidate to augment the correspondence.
        <span className={styles.counts}>
          {" "}
          {done} done · {remaining} remaining
        </span>
      </p>
    </header>
  );
}
