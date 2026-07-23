import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import CaseCard, { type CaseCardData } from "../components/CaseCard";
import { api, bestRun, formatDuration, photoUrl, relTime, type Run, type RunDetail } from "../lib/api";
import { useRefreshOnFocus } from "../lib/dataRefresh";
import { useAsync } from "../lib/useAsync";
import styles from "./Compare.module.css";

type DeltaTone = "success" | "danger" | "muted";

function runKey(r: Run) {
  return `${r.name}__v${r.version}`;
}

function cohortKey(r: Run) {
  return `${r.evaluation_set_sha256 || "unknown"}|${r.scope || "all"}|${r.mode || "exact"}`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n}%`;
}

function deltaStr(a: number | null | undefined, b: number | null | undefined, invert = false): {
  text: string;
  tone: DeltaTone;
} {
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) {
    return { text: "—", tone: "muted" };
  }
  const d = b - a;
  if (Math.abs(d) < 0.05) return { text: "— 0", tone: "muted" };
  const better = invert ? d < 0 : d > 0;
  const arrow = d > 0 ? "▲" : "▼";
  const sign = d > 0 ? "+" : "";
  return {
    text: `${arrow} ${sign}${Number.isInteger(d) ? d : d.toFixed(1)}`,
    tone: better ? "success" : "danger",
  };
}

interface CompareData {
  runs: Run[];
  left: RunDetail;
  right: RunDetail;
}

export default function Compare() {
  const [searchParams] = useSearchParams();
  const list = useAsync(() => api.runs().then((r) => r.runs), []);
  useRefreshOnFocus(list.softReload);
  const runs = list.status === "ready" ? list.data : [];
  const [pickA, setPickA] = useState<string>("");
  const [pickB, setPickB] = useState<string>("");
  const [filter, setFilter] = useState<"all" | "fixed" | "broken">("all");
  const [urlApplied, setUrlApplied] = useState(false);

  const scored = useMemo(
    () =>
      [...runs]
        .filter((r) => typeof r.accuracy_pct === "number")
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [runs],
  );

  const best = useMemo(() => bestRun(runs), [runs]);

  // Default: best vs previous version of same name, else next best different run
  const defaults = useMemo(() => {
    if (!best) return { a: null as Run | null, b: null as Run | null };
    const prev = scored.find((r) => r.name === best.name && r.version === best.version - 1);
    if (prev) return { a: prev, b: best };
    const other = scored.find((r) => runKey(r) !== runKey(best));
    return { a: other ?? best, b: best };
  }, [best, scored]);

  // Results → Compare: ?b=name&bv=version (and optional a/av) preselect runs once.
  useEffect(() => {
    if (urlApplied || scored.length === 0) return;
    const bName = searchParams.get("b") || searchParams.get("name") || "";
    const bVer = searchParams.get("bv") || searchParams.get("version") || "";
    const aName = searchParams.get("a") || "";
    const aVer = searchParams.get("av") || "";

    const find = (name: string, ver: string) => {
      if (!name || !ver) return null;
      const v = Number(ver);
      if (!Number.isFinite(v)) return null;
      return scored.find((r) => r.name === name && r.version === v) ?? null;
    };

    const fromB = find(bName, bVer);
    const fromA = find(aName, aVer);

    if (fromB) {
      setPickB(runKey(fromB));
      // Pair with previous version of same name when possible, else default A.
      const prev = scored.find((r) => r.name === fromB.name && r.version === fromB.version - 1);
      if (fromA) setPickA(runKey(fromA));
      else if (prev) setPickA(runKey(prev));
      else if (defaults.a && runKey(defaults.a) !== runKey(fromB)) setPickA(runKey(defaults.a));
      else {
        const other = scored.find((r) => runKey(r) !== runKey(fromB));
        if (other) setPickA(runKey(other));
      }
    } else if (fromA) {
      setPickA(runKey(fromA));
    }
    setUrlApplied(true);
  }, [scored, searchParams, urlApplied, defaults.a]);

  const keyA = pickA || (defaults.a ? runKey(defaults.a) : "");
  const keyB = pickB || (defaults.b ? runKey(defaults.b) : "");
  const runA = scored.find((r) => runKey(r) === keyA) ?? defaults.a;
  const runB = scored.find((r) => runKey(r) === keyB) ?? defaults.b;

  const detail = useAsync<CompareData | null>(async () => {
    if (!runA || !runB) return null;
    const [{ run: left }, { run: right }] = await Promise.all([
      api.run(runA.name, runA.version),
      api.run(runB.name, runB.version),
    ]);
    return { runs: scored, left, right };
  }, [runA?.name, runA?.version, runB?.name, runB?.version]);

  if (list.status === "loading") {
    return <main className={styles.main}>Loading runs…</main>;
  }
  if (list.status === "error") {
    return <main className={styles.main}>Couldn’t load runs — {list.error.message}</main>;
  }
  if (scored.length < 2) {
    return (
      <main className={styles.main}>
        <div className={styles.header}>
          <p className={`sectionLabel ${styles.kicker}`}>Compare runs</p>
          <h1 className={styles.h1}>Need at least two scored runs</h1>
          <p className={styles.sub}>
            {scored.length === 0
              ? "No scored runs yet."
              : `Only one scored run (${scored[0].name} · v${scored[0].version}).`}{" "}
            <Link to="/new-run">Submit another run</Link> to compare.
          </p>
        </div>
      </main>
    );
  }

  const left = detail.status === "ready" ? detail.data?.left : null;
  const right = detail.status === "ready" ? detail.data?.right : null;
  const a = left ?? runA!;
  const b = right ?? runB!;

  const sameCohort = cohortKey(a) === cohortKey(b);
  const winnerIsB = (b.accuracy_pct ?? 0) >= (a.accuracy_pct ?? 0);
  const winner = winnerIsB ? b : a;

  const rows: { metric: string; va: string; vb: string; delta: string; tone: DeltaTone }[] = [
    (() => {
      const d = deltaStr(a.accuracy_pct, b.accuracy_pct);
      return {
        metric: "Selection accuracy (strict)",
        va: fmtPct(a.accuracy_pct),
        vb: fmtPct(b.accuracy_pct),
        delta: d.text,
        tone: d.tone,
      };
    })(),
    (() => {
      const d = deltaStr(a.accuracy_canonical_pct, b.accuracy_canonical_pct);
      return {
        metric: "Canonical accuracy",
        va: fmtPct(a.accuracy_canonical_pct),
        vb: fmtPct(b.accuracy_canonical_pct),
        delta: d.text,
        tone: d.tone,
      };
    })(),
    (() => {
      const d = deltaStr(a.n_eligible, b.n_eligible);
      return {
        metric: "Eligible cases",
        va: String(a.n_eligible ?? "—"),
        vb: String(b.n_eligible ?? "—"),
        delta: d.text === "— 0" ? "— 0" : d.text,
        tone: "muted",
      };
    })(),
    (() => {
      const d = deltaStr(a.correct, b.correct);
      return {
        metric: "Correct (strict)",
        va: String(a.correct ?? "—"),
        vb: String(b.correct ?? "—"),
        delta: d.text,
        tone: d.tone,
      };
    })(),
    (() => {
      const d = deltaStr(a.duration_ms ?? null, b.duration_ms ?? null, true);
      return {
        metric: "Host runtime",
        va: formatDuration(a.duration_ms),
        vb: formatDuration(b.duration_ms),
        delta: a.duration_ms != null && b.duration_ms != null ? d.text : "—",
        tone: a.duration_ms != null && b.duration_ms != null ? d.tone : "muted",
      };
    })(),
  ];

  // Flipped cases when both details loaded
  type Flip = {
    dataset: string;
    photo: string;
    card: CaseCardData;
    kind: "fixed" | "broken";
  };
  const flips: Flip[] = [];
  if (left && right) {
    const mapB = new Map(right.cases.map((c) => [`${c.dataset}/${c.photo}`, c]));
    for (const ca of left.cases) {
      const cb = mapB.get(`${ca.dataset}/${ca.photo}`);
      if (!cb) continue;
      if (ca.correct === cb.correct) continue;
      const fixed = !ca.correct && cb.correct;
      flips.push({
        dataset: ca.dataset,
        photo: ca.photo,
        kind: fixed ? "fixed" : "broken",
        card: {
          band: fixed ? "success" : "danger",
          filename: ca.photo,
          image: photoUrl(ca.dataset, ca.photo, { thumb: true, w: 720 }),
          title: `${ca.dataset} — ${fixed ? "fixed ✓" : "broken ✗"}`,
          predictedLabel: `v${a.version} PICK`,
          predicted: `${ca.correct ? "✓ " : "✗ "}${ca.prediction || "—"}`,
          predictedTone: ca.correct ? "success" : "danger",
          groundTruthLabel: `v${b.version} PICK`,
          groundTruth: `${cb.correct ? "✓ " : "✗ "}${cb.prediction || "—"}`,
          groundTruthTone: cb.correct ? "success" : "danger",
          gtSrc: `gt · ${ca.gt}`,
        },
      });
    }
  }

  const fixedN = flips.filter((f) => f.kind === "fixed").length;
  const brokenN = flips.filter((f) => f.kind === "broken").length;
  const shown = flips
    .filter((f) => filter === "all" || f.kind === filter)
    .slice(0, 12);

  const labelA = `${a.name} · v${a.version}`;
  const labelB = `${b.name} · v${b.version}`;

  return (
    <main className={styles.main}>
      <div className={styles.header}>
        <p className={`sectionLabel ${styles.kicker}`}>Compare runs</p>
        <h1 className={styles.h1}>
          {a.name === b.name ? `${a.name} — v${b.version} vs v${a.version}` : `${labelB} vs ${labelA}`}
        </h1>
        <p className={styles.sub}>
          {sameCohort
            ? `Same cohort · ${b.n_eligible?.toLocaleString?.() ?? b.n_eligible} eligible · ${b.mode || "exact"} match`
            : "Different cohort or scoring mode — deltas may not be apples-to-apples"}
        </p>
      </div>

      <div className={styles.tray}>
        <span className={styles.trayCount}>
          COMPARING 2 / {scored.length}
        </span>
        <label className={`${styles.runChip} ${styles.runChipOn}`}>
          A{" "}
          <select
            value={keyA}
            onChange={(e) => setPickA(e.target.value)}
            style={{
              border: "none",
              background: "transparent",
              color: "inherit",
              font: "inherit",
              maxWidth: 220,
            }}
          >
            {scored.map((r) => (
              <option key={runKey(r)} value={runKey(r)}>
                {r.name} · v{r.version} · {fmtPct(r.accuracy_pct)}
              </option>
            ))}
          </select>
        </label>
        <label className={`${styles.runChip} ${styles.runChipOn}`}>
          B{" "}
          <select
            value={keyB}
            onChange={(e) => setPickB(e.target.value)}
            style={{
              border: "none",
              background: "transparent",
              color: "inherit",
              font: "inherit",
              maxWidth: 220,
            }}
          >
            {scored.map((r) => (
              <option key={runKey(r)} value={runKey(r)}>
                {r.name} · v{r.version} · {fmtPct(r.accuracy_pct)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!sameCohort && (
        <div className={styles.guard}>
          These runs differ in evaluation cohort, scope, or mode
          {a.evaluation_set_sha256 && b.evaluation_set_sha256
            ? ` (eval hash ${a.evaluation_set_sha256.slice(0, 8)}… vs ${b.evaluation_set_sha256.slice(0, 8)}…)`
            : ""}
          . Prefer comparing runs with the same evaluation_set_sha256.
        </div>
      )}

      <div className={styles.duel}>
        <div className={`${styles.duelCard} ${winnerIsB ? styles.winner : ""}`}>
          <div className={styles.duelHead}>
            <span className={styles.duelVer}>
              v{b.version} · {relTime(b.created_at)}
            </span>
            {winnerIsB && <span className={styles.winnerPill}>WINNER</span>}
          </div>
          <span className={styles.duelValue}>{fmtPct(b.accuracy_pct)}</span>
          <span className={styles.duelSub}>
            {b.correct ?? "—"} correct · runtime {formatDuration(b.duration_ms)}
          </span>
        </div>
        <div className={`${styles.duelCard} ${!winnerIsB ? styles.winner : ""}`}>
          <div className={styles.duelHead}>
            <span className={styles.duelVer}>
              v{a.version} · {relTime(a.created_at)}
            </span>
            {!winnerIsB && <span className={styles.winnerPill}>WINNER</span>}
          </div>
          <span className={`${styles.duelValue} ${winnerIsB ? styles.duelValueMuted : ""}`}>
            {fmtPct(a.accuracy_pct)}
          </span>
          <span className={styles.duelSub}>
            {a.correct ?? "—"} correct · runtime {formatDuration(a.duration_ms)}
          </span>
        </div>
      </div>

      <div className={styles.table}>
        <div className={`${styles.row} ${styles.headRow}`}>
          <div className={styles.cMetric}>METRIC</div>
          <div className={styles.cCol}>A · v{a.version}</div>
          <div className={styles.cCol}>B · v{b.version}</div>
          <div className={styles.cCol}>Δ</div>
        </div>
        {rows.map((r) => (
          <div key={r.metric} className={styles.row}>
            <div className={styles.cMetric}>{r.metric}</div>
            <div className={`${styles.cCol} mono ${styles.muted}`}>{r.va}</div>
            <div className={`${styles.cCol} mono ${styles.strong}`}>{r.vb}</div>
            <div
              className={`${styles.cCol} mono`}
              style={{
                color:
                  r.tone === "success"
                    ? "var(--success-fg)"
                    : r.tone === "danger"
                      ? "var(--danger-fg)"
                      : "var(--text-tertiary)",
              }}
            >
              {r.delta}
            </div>
          </div>
        ))}
      </div>

      <div className={styles.flipsHead}>
        <span className={`sectionLabel ${styles.flipsLabel}`}>
          {detail.status === "loading"
            ? "Loading case flips…"
            : `${flips.length} flipped cases`}
        </span>
        <button
          type="button"
          className={`${styles.filter} ${filter === "all" ? styles.filterOn : ""}`}
          onClick={() => setFilter("all")}
        >
          All · {flips.length}
        </button>
        <button
          type="button"
          className={`${styles.filter} ${filter === "fixed" ? styles.filterOn : ""}`}
          onClick={() => setFilter("fixed")}
        >
          <span className={styles.dot} style={{ background: "var(--success-fg)" }} />
          Fixed by B · {fixedN}
        </button>
        <button
          type="button"
          className={`${styles.filter} ${filter === "broken" ? styles.filterOn : ""}`}
          onClick={() => setFilter("broken")}
        >
          <span className={styles.dot} style={{ background: "var(--danger-fg)" }} />
          Broken by B · {brokenN}
        </button>
      </div>

      {detail.status === "error" && (
        <p className={styles.sub}>Couldn’t load case details — {detail.error.message}</p>
      )}

      <div className={styles.flipsGallery}>
        {shown.map((f) => (
          <Link
            key={`${f.dataset}/${f.photo}`}
            to={`/case?dataset=${encodeURIComponent(f.dataset)}&photo=${encodeURIComponent(f.photo)}&run_name=${encodeURIComponent(winner.name)}&version=${winner.version}`}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <CaseCard {...f.card} />
          </Link>
        ))}
      </div>
      {flips.length === 0 && detail.status === "ready" && (
        <p className={styles.sub}>No flipped outcomes between these two runs on the overlapping case set.</p>
      )}
      {shown.length < flips.filter((f) => filter === "all" || f.kind === filter).length && (
        <p className={styles.sub}>
          Showing first {shown.length} of{" "}
          {flips.filter((f) => filter === "all" || f.kind === filter).length}
        </p>
      )}
    </main>
  );
}
