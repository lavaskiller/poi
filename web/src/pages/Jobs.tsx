import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, relTime, type Job } from "../lib/api";
import styles from "./Datasets.module.css";

function jobTitle(j: Job): string {
  const ds = (j.params?.dataset as string | undefined) || "";
  return ds ? `${j.step} — ${ds}` : j.step;
}

/** Prefer server-computed pct; fall back to done/total so the bar never sticks at 0. */
function jobPct(j: Job): number {
  const p = j.progress;
  if (!p) return 0;
  if (typeof p.pct === "number" && Number.isFinite(p.pct)) {
    return Math.min(100, Math.max(0, p.pct));
  }
  const done = typeof p.done === "number" ? p.done : null;
  const total = typeof p.total === "number" ? p.total : null;
  if (done != null && total != null && total > 0) {
    return Math.min(100, Math.max(0, (100 * done) / total));
  }
  return 0;
}

function jobWhen(j: Job): string {
  if (j.status === "running") {
    const pct = jobPct(j);
    const msg =
      typeof j.progress?.message === "string" ? j.progress.message : null;
    const parts: string[] = ["running"];
    if (pct > 0) parts.push(`${Math.round(pct)}%`);
    if (msg) parts.push(msg);
    if (j.elapsed_s != null) parts.push(`${Math.round(j.elapsed_s)}s`);
    return parts.join(" · ");
  }
  if (j.finished) {
    return `${j.status} · ${relTime(new Date(j.finished * 1000).toISOString())}`;
  }
  if (j.started) {
    return `${j.status} · started ${relTime(new Date(j.started * 1000).toISOString())}`;
  }
  return j.status;
}

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [steps, setSteps] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.jobs();
      setJobs([...res.jobs].sort((a, b) => (b.started || 0) - (a.started || 0)));
      setActive(res.active);
      setSteps(res.steps || {});
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(t);
  }, [active, refresh]);

  const running = jobs.filter((j) => j.status === "running");
  const history = jobs.filter((j) => j.status !== "running");

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>Data · Jobs</p>
          <h1 className={styles.h1}>Background jobs</h1>
          <p className={styles.sub}>
            Enrichment and ingest jobs · one at a time ·{" "}
            <Link to="/datasets">manage from Datasets →</Link>
          </p>
        </div>
      </header>

      {error && <p className={styles.ceiling}>⚠ {error}</p>}

      <section className={styles.rowStruct}>
        <div className={styles.rsHead}>
          <p className={styles.miniLabel}>Available steps</p>
        </div>
        <div className={styles.rsGroups}>
          <div className={styles.rsGroup}>
            {Object.entries(steps).map(([step, status]) => (
              <div key={step} className={styles.colRow}>
                <div className={styles.colName}>
                  <span className={styles.colTitle}>{step}</span>
                </div>
                <div className={styles.colMethod}>
                  <span
                    className={styles.methodChip}
                    style={{
                      color: status === "ok" ? "var(--success-fg)" : "var(--warning-fg)",
                    }}
                  >
                    {status === "ok" ? "available" : status}
                  </span>
                </div>
              </div>
            ))}
            {Object.keys(steps).length === 0 && (
              <p className={styles.sub}>No step registry returned.</p>
            )}
          </div>
        </div>
      </section>

      <div className={styles.jobs} style={{ maxWidth: 720 }}>
        <p className={styles.miniLabel}>Active</p>
        {running.length === 0 && (
          <p className={styles.activeNote}>No job running.</p>
        )}
        {running.map((j) => {
          const pct = jobPct(j);
          const msg =
            typeof j.progress?.message === "string" ? j.progress.message : null;
          return (
            <div key={j.id || j.job_id} className={styles.activeJob}>
              <div className={styles.activeHead}>
                <span className={styles.jobDot} style={{ background: "var(--warning-fg)" }} />
                <span className={styles.activeName}>{jobTitle(j)}</span>
                <span className={styles.activeSpacer} />
                <span className={styles.activeStat}>{jobWhen(j)}</span>
              </div>
              <div className={styles.jobTrack}>
                <div
                  className={styles.jobFill}
                  style={{
                    width: `${pct > 0 ? pct : 8}%`,
                    transition: "width 0.4s ease-out",
                  }}
                />
              </div>
              <p className={styles.activeNote}>
                id {j.id || j.job_id}
                {msg ? ` · ${msg}` : ""}
              </p>
            </div>
          );
        })}

        <p className={styles.miniLabel} style={{ marginTop: 16 }}>
          History
        </p>
        {history.length === 0 && (
          <p className={styles.activeNote}>No completed jobs in this server session.</p>
        )}
        {history.map((j) => (
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
    </main>
  );
}
