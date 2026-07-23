import { Link } from "react-router-dom";
import Button from "../components/Button";
import StatTile from "../components/StatTile";
import { api, bestRun, relTime, type Overview, type Run } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./Home.module.css";

function pct(part: number, whole: number): number {
  return whole > 0 ? Math.round((part / whole) * 100) : 0;
}

interface HomeData {
  overview: Overview;
  runs: Run[];
}

export default function Home() {
  const state = useAsync<HomeData>(async () => {
    const [overview, runs] = await Promise.all([api.overview(), api.runs()]);
    return { overview, runs: runs.runs };
  }, []);

  if (state.status === "loading") {
    return (
      <main className={styles.main}>
        <div className={styles.skeletonBlock} style={{ height: 64, width: 360 }} />
        <div className={styles.skeletonBlock} style={{ height: 200 }} />
        <div className={styles.skeletonBlock} style={{ height: 120 }} />
      </main>
    );
  }
  if (state.status === "error") {
    return <main className={styles.main}>Couldn’t load overview — {state.error.message}</main>;
  }

  const { overview, runs } = state.data;
  const total = overview.total;
  const nDatasets = overview.sources.length;
  const gtCov = pct(overview.gt_present ?? 0, total);
  const photoCov = pct(overview.photo_present ?? 0, total);
  const countries = overview.countries ?? [];

  const best = bestRun(runs);
  // Only compare versions with the same evaluation cohort (eval hash) when known.
  const sameCohort = (a: Run, b: Run) => {
    if (a.evaluation_set_sha256 && b.evaluation_set_sha256) {
      return a.evaluation_set_sha256 === b.evaluation_set_sha256;
    }
    // Unknown hash: still require same scope + mode so we don't mix apples.
    return (a.scope || "all") === (b.scope || "all") && (a.mode || "exact") === (b.mode || "exact");
  };
  const prevOfBest = best
    ? runs.find(
        (r) =>
          r.name === best.name &&
          r.version === best.version - 1 &&
          sameCohort(r, best),
      )
    : undefined;
  const delta =
    best && prevOfBest && typeof prevOfBest.accuracy_pct === "number"
      ? (best.accuracy_pct ?? 0) - prevOfBest.accuracy_pct
      : null;
  const deltaNote =
    delta == null
      ? best
        ? "No prior version in the same evaluation cohort"
        : null
      : `vs ${best!.name} v${prevOfBest!.version} · same cohort`;

  const trend = best
    ? runs
        .filter(
          (r) =>
            r.name === best.name &&
            typeof r.accuracy_pct === "number" &&
            (!best.evaluation_set_sha256 ||
              !r.evaluation_set_sha256 ||
              r.evaluation_set_sha256 === best.evaluation_set_sha256),
        )
        .sort((a, b) => a.version - b.version)
    : [];
  const trendMax = Math.max(1, ...trend.map((r) => r.accuracy_pct ?? 0));

  const nElig = best?.n_eligible ?? 0;
  const correct = best?.correct ?? (best ? Math.round(((best.accuracy_pct ?? 0) / 100) * nElig) : 0);
  const incorrect = Math.max(0, nElig - correct);
  const noGt = Math.max(0, total - nElig);
  const outcomes = [
    { key: "correct", n: correct, color: "var(--success-fg)", label: `Correct ${correct}` },
    { key: "incorrect", n: incorrect, color: "var(--warning-fg)", label: `Incorrect ${incorrect}` },
    { key: "nogt", n: noGt, color: "var(--bg-subtle)", label: `Ineligible / holdout ${noGt}` },
  ];
  const outcomeTotal = Math.max(1, correct + incorrect + noGt);

  const recent = [...runs]
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
    .slice(0, 5);
  const latest = recent[0];

  return (
    <main className={styles.main}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <p className={`sectionLabel ${styles.kicker}`}>POI Evaluation · Internal</p>
          <h1 className={styles.h1}>
            {best && delta != null && delta > 0
              ? "Selection accuracy is improving."
              : "POI evaluation overview"}
          </h1>
          <p className={styles.sub}>
            {latest ? `Last run ${relTime(latest.created_at)} · ` : ""}
            {gtCov}% GT coverage · {total.toLocaleString()} cases across {nDatasets} datasets
          </p>
        </div>
        <Link to="/datasets" style={{ textDecoration: "none" }}>
          <Button kind="secondary">Upload data</Button>
        </Link>
        <Link to="/new-run" style={{ textDecoration: "none" }}>
          <Button kind="primary">▶&nbsp;&nbsp;New run</Button>
        </Link>
      </header>

      {(overview.config_warnings?.length ?? 0) > 0 && (
        <div className={styles.warnStrip}>
          {overview.config_warnings!.map((w, i) => (
            <span key={i}>⚠ {w}</span>
          ))}
        </div>
      )}

      <section className={styles.hero}>
        <div className={styles.heroTop}>
          <div className={styles.metric}>
            <p className={`sectionLabel ${styles.metricLabel}`}>Selection accuracy — best run</p>
            <div className={styles.metricRow}>
              <span className={styles.metricValue}>{best ? `${best.accuracy_pct}%` : "—"}</span>
              {delta != null ? (
                <span
                  className={`${styles.delta} ${delta >= 0 ? styles.deltaUp : styles.deltaDown}`}
                  title={deltaNote ?? undefined}
                >
                  {delta >= 0 ? "▲" : "▼"} {delta >= 0 ? "+" : ""}
                  {delta.toFixed(1)} pts vs v{prevOfBest!.version}
                </span>
              ) : (
                best && (
                  <span className={`${styles.delta} ${styles.deltaMuted}`} title={deltaNote ?? undefined}>
                    no Δ · new cohort or first version
                  </span>
                )
              )}
            </div>
            <p className={styles.metricMeta}>
              {best
                ? `${best.name} · v${best.version} · ${best.scope || "all"} · eligible ${best.n_eligible.toLocaleString()} / ${total.toLocaleString()}${
                    best.evaluation_set_sha256
                      ? ` · eval ${best.evaluation_set_sha256.slice(0, 8)}…`
                      : ""
                  }`
                : "no scored runs yet"}
            </p>
            {deltaNote && delta != null && (
              <p className={styles.deltaExplain} title="Δ only vs the previous version of the same run name that shares evaluation_set_sha256 (or scope+mode when hash is missing).">
                Δ {deltaNote}
                {best?.evaluation_set_sha256
                  ? ` · hash ${best.evaluation_set_sha256.slice(0, 8)}…`
                  : ""}
              </p>
            )}
            {best && (
              <div className={styles.toggle}>
                <Link
                  to={`/results?name=${encodeURIComponent(best.name)}&version=${best.version}`}
                  className={`${styles.chip} ${styles.chipActive}`}
                  style={{ textDecoration: "none" }}
                >
                  Strict · {best.accuracy_pct}%
                </Link>
                {best.accuracy_canonical_pct != null && (
                  <span className={styles.chip}>Canonical · {best.accuracy_canonical_pct}%</span>
                )}
              </div>
            )}
          </div>

          {trend.length > 0 && (
            <div className={styles.trend}>
              <p className={`sectionLabel ${styles.trendLabel}`}>Version trend (same cohort)</p>
              <div className={styles.bars}>
                {trend.map((r) => {
                  const active = best && r.version === best.version;
                  return (
                    <div key={r.version} className={styles.bar}>
                      <div
                        className={styles.barFill}
                        style={{
                          height: 40 + ((r.accuracy_pct ?? 0) / trendMax) * 70,
                          background: active ? "var(--accent-default)" : "var(--bg-subtle)",
                        }}
                      />
                      <span
                        className={styles.barLabel}
                        style={{ color: active ? "var(--accent-default)" : "var(--text-tertiary)" }}
                      >
                        v{r.version}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className={styles.outcomes}>
          <p className={`sectionLabel ${styles.outcomeLabel}`}>
            Outcome composition — best run · {nElig.toLocaleString()} eligible
          </p>
          <div className={styles.stack}>
            {outcomes.map((o) => (
              <span key={o.key} style={{ width: `${(o.n / outcomeTotal) * 100}%`, background: o.color }} />
            ))}
          </div>
          <div className={styles.legend}>
            {outcomes.map((o) => (
              <span key={o.key} className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: o.color }} />
                {o.label}
              </span>
            ))}
          </div>
        </div>
      </section>

      {overview.readiness && (
        <section className={styles.block}>
          <div className={styles.blockHead}>
            <p className={`sectionLabel ${styles.blockLabel}`}>Setup readiness</p>
            <span className={styles.link} style={{ cursor: "default" }}>
              GT {overview.readiness.counts.gt_eligible} · art{" "}
              {overview.readiness.counts.artifact_ready} · run{" "}
              {overview.readiness.counts.runnable_now}
            </span>
          </div>
          <div className={styles.tiles}>
            {(
              [
                ["Dataset loaded", overview.readiness.dataset_loaded, `${overview.readiness.counts.rows} rows`],
                ["GT ready", overview.readiness.gt_ready, `${overview.readiness.counts.gt_eligible} eligible`],
                [
                  "Candidate artifacts",
                  overview.readiness.candidate_artifacts_ready,
                  `${overview.readiness.counts.artifact_ready} ready`,
                ],
                [
                  "Runnable",
                  overview.readiness.runnable,
                  overview.readiness.runnable
                    ? `${overview.readiness.counts.runnable_now} cases`
                    : "blocked — re-probe MapKit or re-seed",
                ],
              ] as const
            ).map(([label, ok, note]) => (
              <StatTile
                key={label}
                label={label}
                value={ok ? "✓" : "—"}
                note={note}
                noteTone={ok ? "tertiary" : "warning"}
              />
            ))}
          </div>
        </section>
      )}

      <section className={styles.block}>
        <div className={styles.blockHead}>
          <p className={`sectionLabel ${styles.blockLabel}`}>Data health</p>
          <a className={styles.link} href="/datasets">
            Open datasets →
          </a>
        </div>
        <div className={styles.tiles}>
          <StatTile label="Total rows" value={total.toLocaleString()} note={`across ${nDatasets} datasets`} />
          <StatTile
            label="GT coverage"
            value={`${gtCov}%`}
            note={`${(total - (overview.gt_present ?? 0)).toLocaleString()} rows missing GT${gtCov < 100 ? " ⚠" : ""}`}
            noteTone={gtCov < 100 ? "warning" : "tertiary"}
          />
          <StatTile
            label="Photo refs"
            value={`${photoCov}%`}
            note={`${(overview.photo_present ?? 0).toLocaleString()} rows with photos`}
          />
          <StatTile
            label="Countries"
            value={String(countries.length)}
            note={countries.map((c) => c.flag || c.key).slice(0, 5).join(" · ") || "—"}
          />
        </div>
      </section>

      <section className={styles.block}>
        <p className={`sectionLabel ${styles.blockLabel}`}>Recent runs</p>
        <div className={styles.table}>
          <div className={`${styles.row} ${styles.headRow}`}>
            <div className={styles.cName}>Name</div>
            <div className={styles.cVer}>Ver</div>
            <div className={styles.cData}>Scope</div>
            <div className={styles.cAcc}>Accuracy</div>
            <div className={styles.cDelta}>Δ</div>
            <div className={styles.cStatus}>Eligible</div>
          </div>
          {recent.map((r) => {
            const prev = runs.find(
              (x) => x.name === r.name && x.version === r.version - 1 && sameCohort(x, r),
            );
            const d =
              typeof r.accuracy_pct === "number" && typeof prev?.accuracy_pct === "number"
                ? r.accuracy_pct - prev.accuracy_pct
                : null;
            const title =
              d == null
                ? "No prior version in the same evaluation cohort"
                : `vs v${prev!.version} same cohort` +
                  (r.evaluation_set_sha256 ? ` · ${r.evaluation_set_sha256.slice(0, 8)}…` : "");
            return (
              <Link
                key={`${r.name}-${r.version}`}
                to={`/results?name=${encodeURIComponent(r.name)}&version=${r.version}`}
                className={styles.row}
                style={{ textDecoration: "none", color: "inherit" }}
                title={title}
              >
                <div className={`${styles.cName} mono ${styles.strong}`}>{r.name}</div>
                <div className={`${styles.cVer} mono ${styles.muted}`}>v{r.version}</div>
                <div className={styles.cData}>{r.scope || "all"}</div>
                <div className={`${styles.cAcc} mono ${styles.strong}`}>
                  {r.accuracy_pct != null ? `${r.accuracy_pct}%` : "—"}
                </div>
                <div
                  className={`${styles.cDelta} mono`}
                  style={{
                    color:
                      d == null
                        ? "var(--text-tertiary)"
                        : d >= 0
                          ? "var(--success-fg)"
                          : "var(--danger-fg)",
                  }}
                >
                  {d == null ? "—" : `${d >= 0 ? "+" : ""}${d.toFixed(1)}`}
                </div>
                <div className={`${styles.cStatus} mono ${styles.muted}`}>
                  {r.n_eligible?.toLocaleString?.() ?? r.n_eligible}
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    </main>
  );
}
