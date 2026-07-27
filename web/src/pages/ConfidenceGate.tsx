import { useMemo, useState } from "react";
import { api, type ConfSimCase, type OcrStrength } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import styles from "./ConfidenceGate.module.css";

/**
 * Tunable gate params (client-side; GT is never an input).
 * See docs/confidence-gate.md — faithful preset reproduces decide().
 */
interface Params {
  tau: number;
  R: number; // density radius (m)
  mRef: number; // margin reference (m)
  dRef: number; // nearest-distance reference (m)
  strict: boolean; // spatial-agreement hard pre-filter
  wM: number;
  wO: number;
  wS: number; // soft spatial weight (used when !strict)
  wD: number;
  wRho: number;
  wG: number;
  wV: number; // VLM contribution cap when corroborates
}

type Preset = "faithful" | "explore";

const K = 4; // density crowding scale

/** faithful: reproduce current decide() (docs §Presets). */
const FAITHFUL: Params = {
  tau: 1.0,
  R: 80,
  mRef: 60,
  dRef: 100,
  strict: true,
  wM: 1.0,
  wO: 1.0,
  wS: 0,
  wD: 0,
  wRho: 0,
  wG: 0.5,
  wV: 0.3,
};

/** explore: fold density / distance into the search for a better gate. */
const EXPLORE: Params = {
  tau: 1.0,
  R: 80,
  mRef: 60,
  dRef: 100,
  strict: false,
  wM: 1.0,
  wO: 1.0,
  wS: 0.5,
  wD: 0.5,
  wRho: 0.5,
  wG: 0.5,
  wV: 0.3,
};

function ocrTermValue(strength: OcrStrength | undefined): number {
  if (strength === "full") return 1.0;
  if (strength === "tokens") return 0.7;
  return 0;
}

function strengthOf(c: ConfSimCase): OcrStrength {
  if (c.ocr_strength === "full" || c.ocr_strength === "tokens" || c.ocr_strength === "none") {
    return c.ocr_strength;
  }
  // Backward compat if an older server only sent the boolean.
  return c.ocr_supported ? "full" : "none";
}

export interface TermBreakdown {
  margin: number;
  ocr: number;
  spatial: number;
  dist: number;
  density: number;
  generic: number;
  vlm: number;
  total: number;
}

/** Interpretable additive confidence score — docs/confidence-gate.md §2. */
function breakdown(c: ConfSimCase, p: Params): TermBreakdown {
  const marginRaw = c.margin_m != null ? Math.min(Math.max(c.margin_m / p.mRef, 0), 1) : 0;
  const ocrRaw = ocrTermValue(strengthOf(c));
  const spatialRaw = c.spatial_agreement ? 1 : 0;
  const distRaw =
    c.app_poi_dist_m != null ? Math.min(Math.max(1 - c.app_poi_dist_m / p.dRef, 0), 1) : 0;
  const nR = (c.cand_dists || []).filter((d) => d <= p.R).length;
  const densityRaw = Math.min(Math.max((nR - 1) / K, 0), 1);
  const genericRaw = c.generic_name ? 1 : 0;
  const vlmRaw = c.vlm_support ? 1 : 0;

  const margin = p.wM * marginRaw;
  const ocr = p.wO * ocrRaw;
  // Soft spatial only when not hard-filtering; faithful uses hard pre-filter.
  const spatial = p.strict ? 0 : p.wS * spatialRaw;
  const dist = p.wD * distRaw;
  const density = p.wRho * densityRaw;
  const generic = p.wG * genericRaw;
  // Doc: vlm_term corroborates 1/0 with cap 0.3 — weight w_v is that cap.
  const vlm = Math.min(p.wV * vlmRaw, p.wV);

  const total = margin + ocr + spatial + dist - density - generic + vlm;
  return { margin, ocr, spatial, dist, density, generic, vlm, total };
}

function score(c: ConfSimCase, p: Params): number {
  return breakdown(c, p).total;
}

/**
 * Hard pre-filters force Near (unscored); else s ≥ τ → labeled.
 *
 * Faithful mode also mirrors `poi_confidence_policy.decide()`: AUTO needs a
 * non-ambiguous weighted resolution, spatial agreement, and either OCR support
 * or a large margin (≥ M_ref). VLM may boost the score but never satisfies
 * these hard gates alone — docs/confidence-gate.md.
 */
function hardBlockReason(c: ConfSimCase, p: Params): string | null {
  if (c.no_candidates || c.n_cand === 0) return "NO_USABLE_CANDIDATES";
  if (p.strict && c.spatial_conflict) return "WEIGHTED_NEAREST_CONFLICT";
  const ocrOk = strengthOf(c) !== "none";
  if ((c.single_candidate || c.n_cand === 1) && !ocrOk) {
    return "SINGLE_CANDIDATE_UNCORROBORATED";
  }
  // Faithful hard gates (strict spatial is part of the faithful preset).
  if (p.strict) {
    if (c.decision === "ambiguous") return "AMBIGUOUS_MARGIN";
    const largeMargin = c.margin_m != null && c.margin_m >= p.mRef;
    if (!ocrOk && !largeMargin) {
      // Same as decide(): VLM cannot open the gate by itself.
      return "NO_STRONG_OCR";
    }
  }
  return null;
}

function labeled(c: ConfSimCase, p: Params): boolean {
  if (hardBlockReason(c, p)) return false;
  return score(c, p) >= p.tau;
}

type Bucket = "correct" | "wrong" | "near";
function bucketOf(c: ConfSimCase, p: Params): Bucket {
  if (!labeled(c, p)) return "near";
  return c.correct ? "correct" : "wrong";
}

type Filter = "wrongPOI" | "wrongNear" | "correctNear" | "correctPOI";

/**
 * Primary Near reason: hard filters first, else the largest missing contribution
 * that kept s below τ (drives the signal-contribution panel).
 */
function nearReason(c: ConfSimCase, p: Params): string {
  const hard = hardBlockReason(c, p);
  if (hard) return hard;
  const b = breakdown(c, p);
  if (b.total >= p.tau) return "BELOW_TAU"; // shouldn't appear for Near
  // Rank positive missing terms and active penalties.
  const deficits: { name: string; value: number }[] = [];
  if (b.margin < p.wM * 0.99) deficits.push({ name: "AMBIGUOUS_MARGIN", value: p.wM - b.margin });
  if (b.ocr < 1e-9) deficits.push({ name: "NO_STRONG_OCR", value: p.wO });
  if (!p.strict && !c.spatial_agreement && p.wS > 0) {
    deficits.push({ name: "WEIGHTED_NEAREST_CONFLICT", value: p.wS });
  }
  if (b.density > 1e-9) deficits.push({ name: "DENSITY_CROWDING", value: b.density });
  if (b.generic > 1e-9) deficits.push({ name: "GENERIC_NAME", value: b.generic });
  if (b.dist < p.wD * 0.5 && p.wD > 0) {
    deficits.push({ name: "FAR_NEAREST", value: p.wD - b.dist });
  }
  deficits.sort((a, b0) => b0.value - a.value);
  return deficits[0]?.name ?? "BELOW_TAU";
}

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((100 * n) / d)}%` : "—";
}

function setNum(p: Params, key: keyof Params, v: number): Params {
  return { ...p, [key]: v };
}

export default function ConfidenceGate() {
  const sim = useAsync(() => api.confidenceSim("all"), []);
  const [mode, setMode] = useState<"lab" | "auto">("lab");
  const [preset, setPreset] = useState<Preset>("faithful");
  const [p, setP] = useState<Params>(FAITHFUL);
  const [showWeights, setShowWeights] = useState(false);
  const [allowedWrong, setAllowedWrong] = useState(2); // Auto: max wrong-labeled % of all
  const [filter, setFilter] = useState<Filter>("wrongPOI");

  const cases = sim.status === "ready" ? sim.data.cases : [];
  const n = cases.length;

  const applyPreset = (name: Preset) => {
    setPreset(name);
    setP(name === "faithful" ? { ...FAITHFUL } : { ...EXPLORE });
    setShowWeights(name === "explore");
  };

  const touch = (next: Params) => {
    setP(next);
    // Leaving faithful defaults marks the session as explore-tuned.
    setPreset("explore");
  };

  // Score ceiling for the τ range. Under explore weights a case's additive
  // score can exceed 2, so a fixed τ_max=2 would (a) truncate the frontier and
  // (b) let Auto report a τ that still leaks wrong labels because it cannot
  // tighten past the ceiling. Span τ up to the max score among τ-gated cases
  // (hard-blocked cases are Near regardless, so they don't set the range);
  // floor at 2 so the default faithful range stays stable.
  const sMax = useMemo(() => {
    let m = 1;
    for (const c of cases) if (!hardBlockReason(c, p)) m = Math.max(m, score(c, p));
    return Math.max(2, Math.ceil(m * 20) / 20);
  }, [cases, p]);

  const autoTau = useMemo(() => {
    if (mode !== "auto" || !n) return p.tau;
    // Start at the strictest τ (≈0 coverage, 0 wrong → always within budget)
    // and loosen while the wrong-labeled share stays within the budget.
    let best = sMax;
    for (let t = sMax; t >= -1e-9; t -= 0.05) {
      const wrong = cases.filter((c) => labeled(c, { ...p, tau: t }) && !c.correct).length;
      if ((100 * wrong) / n <= allowedWrong) best = t;
      else break;
    }
    return Math.round(best * 100) / 100;
  }, [mode, allowedWrong, cases, n, p, sMax]);

  const active: Params = mode === "auto" ? { ...p, tau: autoTau } : p;

  const stats = useMemo(() => {
    let correct = 0,
      wrong = 0,
      near = 0,
      avoided = 0,
      sacrificed = 0;
    for (const c of cases) {
      const b = bucketOf(c, active);
      if (b === "correct") correct++;
      else if (b === "wrong") wrong++;
      else {
        near++;
        c.correct ? sacrificed++ : avoided++;
      }
    }
    return { correct, wrong, near, avoided, sacrificed, labeledN: correct + wrong };
  }, [cases, active]);

  const frontier = useMemo(() => {
    const pts: { coverage: number; precision: number }[] = [];
    const steps = 24;
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * sMax;
      let lc = 0,
        lw = 0;
      for (const c of cases) if (labeled(c, { ...active, tau: t })) c.correct ? lc++ : lw++;
      const lab = lc + lw;
      pts.push({ coverage: n ? lab / n : 0, precision: lab ? lc / lab : 1 });
    }
    return pts;
  }, [cases, active, n, sMax]);

  const reasons = useMemo(() => {
    const m = new Map<string, { total: number; wrong: number; correct: number }>();
    for (const c of cases) {
      if (labeled(c, active)) continue;
      const r = nearReason(c, active);
      const e = m.get(r) ?? { total: 0, wrong: 0, correct: 0 };
      e.total++;
      c.correct ? e.correct++ : e.wrong++;
      m.set(r, e);
    }
    return [...m.entries()]
      .map(([name, v]) => ({ name, ...v }))
      .sort((a, b) => b.total - a.total);
  }, [cases, active]);

  const gallery = useMemo(() => {
    return cases
      .filter((c) => {
        const b = bucketOf(c, active);
        if (filter === "wrongPOI") return b === "wrong";
        if (filter === "correctPOI") return b === "correct";
        if (filter === "wrongNear") return b === "near" && !c.correct;
        return b === "near" && c.correct; // correctNear
      })
      .slice(0, 12);
  }, [cases, active, filter]);

  if (sim.status === "loading")
    return (
      <div className={styles.page}>
        <div className={styles.loading}>
          <span className={styles.spinner} /> Precomputing signals for the cohort…
        </div>
      </div>
    );
  if (sim.status === "error")
    return (
      <div className={styles.page}>
        <p className={styles.err}>
          Couldn’t load the confidence simulation — {sim.error.message}. Needs MapKit candidates in{" "}
          <code>poi-data/</code> and a running backend with <code>/api/confidence-sim</code> (restart{" "}
          <code>server.py</code> if the route was just added).
        </p>
      </div>
    );

  const W = 560,
    H = 190,
    PX = 46,
    PY = 14;
  const fx = (cov: number) => PX + cov * (W - PX - 14);
  const fy = (prec: number) => PY + (1 - prec) * (H - PY - 26);
  const dpath = frontier
    .map((pt, i) => `${i ? "L" : "M"}${fx(pt.coverage).toFixed(1)},${fy(pt.precision).toFixed(1)}`)
    .join(" ");
  const cov = n ? stats.labeledN / n : 0;
  const prec = stats.labeledN ? stats.correct / stats.labeledN : 1;

  const TABS: [Filter, string][] = [
    ["wrongPOI", "Wrong → POI"],
    ["wrongNear", "Wrong → Near"],
    ["correctNear", "Correct → Near"],
    ["correctPOI", "Correct → POI"],
  ];
  const galleryIsPOI = filter === "wrongPOI" || filter === "correctPOI";

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Confidence gate</h1>
          <p className={styles.sub}>
            Show a POI only when confident — otherwise fall back to Near (area), so wrong picks never
            reach the user. Score is additive and GT-free; see{" "}
            <code>docs/confidence-gate.md</code>.
          </p>
        </div>
        <div className={styles.controls}>
          <span className={styles.dropdown}>
            <span className={styles.ddKey}>Algorithm</span> mapkit-weighted{" "}
            <span className={styles.caret}>▾</span>
          </span>
          <div className={styles.toggle}>
            <button
              className={mode === "lab" ? styles.segOn : styles.seg}
              onClick={() => setMode("lab")}
            >
              Lab
            </button>
            <button
              className={mode === "auto" ? styles.segOn : styles.seg}
              onClick={() => setMode("auto")}
            >
              Auto
            </button>
          </div>
        </div>
      </div>

      <div className={styles.panel}>
        <div className={styles.panelHead}>
          <span className={styles.kicker}>
            {mode === "lab" ? "POLICY LAB" : "AUTO — MAX COVERAGE @ WRONG BUDGET"}
          </span>
          <div className={styles.presetRow}>
            <button
              type="button"
              className={preset === "faithful" ? styles.presetOn : styles.presetBtn}
              onClick={() => applyPreset("faithful")}
            >
              faithful
            </button>
            <button
              type="button"
              className={preset === "explore" ? styles.presetOn : styles.presetBtn}
              onClick={() => applyPreset("explore")}
            >
              explore
            </button>
          </div>
        </div>
        {mode === "lab" ? (
          <>
            <div className={styles.sliderRow}>
              <label className={styles.sliderLabel}>Gate strictness</label>
              <span className={styles.tau}>
                τ <b>{active.tau.toFixed(2)}</b>
              </span>
            </div>
            <input
              className={styles.slider}
              type="range"
              min={0}
              max={sMax}
              step={0.05}
              value={Math.min(p.tau, sMax)}
              onChange={(e) => touch(setNum(p, "tau", Number(e.target.value)))}
            />
            <div className={styles.ends}>
              <span>← permissive · more coverage</span>
              <span>strict · more blocked →</span>
            </div>
            <div className={styles.knobs}>
              <label className={styles.knob}>
                Radius R
                <input
                  type="range"
                  min={20}
                  max={250}
                  step={10}
                  value={p.R}
                  onChange={(e) => touch(setNum(p, "R", Number(e.target.value)))}
                />
                <b>{p.R} m</b>
              </label>
              <label className={styles.knob}>
                M_ref
                <input
                  type="range"
                  min={20}
                  max={150}
                  step={10}
                  value={p.mRef}
                  onChange={(e) => touch(setNum(p, "mRef", Number(e.target.value)))}
                />
                <b>{p.mRef} m</b>
              </label>
              <label className={styles.knob}>
                D_ref
                <input
                  type="range"
                  min={20}
                  max={250}
                  step={10}
                  value={p.dRef}
                  onChange={(e) => touch(setNum(p, "dRef", Number(e.target.value)))}
                />
                <b>{p.dRef} m</b>
              </label>
              <label className={`${styles.knob} ${styles.knobToggle}`}>
                <input
                  type="checkbox"
                  checked={p.strict}
                  onChange={(e) => touch({ ...p, strict: e.target.checked })}
                />
                spatial strict
              </label>
              <button
                type="button"
                className={styles.weightsToggle}
                onClick={() => setShowWeights((v) => !v)}
              >
                {showWeights ? "Hide weights" : "Weights"}
              </button>
            </div>
            {showWeights && (
              <div className={styles.weights}>
                {(
                  [
                    ["wM", "w_m margin", 0, 2, 0.05],
                    ["wO", "w_o OCR", 0, 2, 0.05],
                    ["wS", "w_s spatial (soft)", 0, 2, 0.05],
                    ["wD", "w_d dist", 0, 2, 0.05],
                    ["wRho", "w_ρ density", 0, 2, 0.05],
                    ["wG", "w_g generic", 0, 2, 0.05],
                    ["wV", "w_v VLM cap", 0, 1, 0.05],
                  ] as const
                ).map(([key, label, min, max, step]) => (
                  <label key={key} className={styles.knob}>
                    {label}
                    <input
                      type="range"
                      min={min}
                      max={max}
                      step={step}
                      value={p[key]}
                      onChange={(e) => touch(setNum(p, key, Number(e.target.value)))}
                    />
                    <b>{p[key].toFixed(2)}</b>
                  </label>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <div className={styles.sliderRow}>
              <label className={styles.sliderLabel}>Allowed wrong-labeled ≤</label>
              <span className={styles.tau}>
                <b>{allowedWrong}%</b> → τ {autoTau.toFixed(2)}
              </span>
            </div>
            <input
              className={styles.slider}
              type="range"
              min={0}
              max={10}
              step={0.5}
              value={allowedWrong}
              onChange={(e) => setAllowedWrong(Number(e.target.value))}
            />
            <div className={styles.ends}>
              <span>← safest (few wrong, low coverage)</span>
              <span>more coverage, more leak →</span>
            </div>
            <p className={styles.strip}>
              Auto fits τ on this cohort’s GT — treat as an estimate; validate on a held-out split.
              Other knobs stay at the current Lab preset ({preset}).
            </p>
          </>
        )}
        <p className={styles.strip}>
          Signals precomputed for mapkit-weighted · τ &amp; weights re-aggregate instantly (no server
          recompute) · hard filters: 0 cand · spatial conflict (strict) · single cand without OCR
        </p>
      </div>

      <div className={styles.kpiRow}>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${styles.barGood}`} />
          <span className={`${styles.tileLabel} ${styles.good}`}>LABELED · CORRECT</span>
          <span className={`${styles.tileNum} ${styles.good}`}>{stats.correct}</span>
          <span className={styles.tileSub}>
            {pct(stats.correct, n)} of cases · precision {pct(stats.correct, stats.labeledN)} among
            shown POI
          </span>
        </div>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${styles.barBad}`} />
          <span className={`${styles.tileLabel} ${styles.bad}`}>LABELED · WRONG</span>
          <span className={`${styles.tileNum} ${styles.bad}`}>{stats.wrong}</span>
          <span className={styles.tileSub}>
            {pct(stats.wrong, n)} · a wrong POI reached the user (worst case ↓)
          </span>
        </div>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${styles.barNeutral}`} />
          <span className={styles.tileLabel}>NEAR · BLOCKED</span>
          <span className={styles.tileNum}>{stats.near}</span>
          <span className={styles.tileSub}>
            {pct(stats.near, n)} · area shown instead of a POI
          </span>
          <div className={styles.mini}>
            <span className={styles.miniGood}>
              ▲ {stats.avoided}
              <small>wrong avoided</small>
            </span>
            <span className={styles.miniWarn}>
              ▼ {stats.sacrificed}
              <small>correct sacrificed</small>
            </span>
          </div>
        </div>
      </div>
      <div className={styles.summary}>
        <span>
          precision <b>{pct(stats.correct, stats.labeledN)}</b>
        </span>
        <span>
          coverage <b>{pct(stats.labeledN, n)}</b>
        </span>
        <span>
          geo-rate <b>{pct(stats.near, n)}</b>
        </span>
        <span>
          n <b>{n} cases</b>
        </span>
        <span>
          preset <b>{preset}</b>
        </span>
      </div>

      <div className={styles.chartsRow}>
        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <b>Tradeoff frontier</b>
            <span>τ sweep 0→{sMax.toFixed(1)}</span>
          </div>
          <p className={styles.chartCaption}>
            Each point is a τ setting. Y = precision among shown POI · X = coverage. Pick the knee.
          </p>
          <svg className={styles.chart} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
            <line x1={PX} y1={PY} x2={PX} y2={H - 26} className={styles.axis} />
            <line x1={PX} y1={H - 26} x2={W - 14} y2={H - 26} className={styles.axis} />
            <path d={dpath} className={styles.curve} fill="none" />
            {frontier.map((pt, i) => (
              <circle key={i} cx={fx(pt.coverage)} cy={fy(pt.precision)} r={2.5} className={styles.pt} />
            ))}
            <circle cx={fx(cov)} cy={fy(prec)} r={5.5} className={styles.cur} />
            <text x={W / 2} y={H - 6} className={styles.axLabel} textAnchor="middle">
              coverage →
            </text>
          </svg>
          <div className={styles.legend}>
            <span className={styles.lgCur}>current τ = {active.tau.toFixed(2)}</span>
            <span className={styles.lgPt}>swept τ</span>
          </div>
        </div>

        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <b>Signal contribution</b>
            <span>→ Near, by rule</span>
          </div>
          <p className={styles.chartCaption}>
            Hard filters first; else the largest missing term under τ. Higher wrong-share = cleaner
            cut.
          </p>
          <div className={styles.reasons}>
            {reasons.length === 0 && (
              <p className={styles.chartCaption}>Nothing blocked at this τ.</p>
            )}
            {reasons.map((r) => (
              <div key={r.name} className={styles.reason}>
                <div className={styles.reasonTop}>
                  <span className={styles.reasonName}>{r.name}</span>
                  <span className={styles.reasonMeta}>
                    <b className={styles.bad}>wrong {pct(r.wrong, r.total)}</b> n={r.total}
                  </span>
                </div>
                <div className={styles.reasonBar}>
                  <span className={styles.segWrong} style={{ flex: r.wrong || 0.001 }} />
                  <span className={styles.segCorrect} style={{ flex: r.correct || 0.001 }} />
                </div>
              </div>
            ))}
          </div>
          <div className={styles.legend}>
            <span className={styles.lgWrong}>wrong avoided (gain)</span>
            <span className={styles.lgCorrect}>correct sacrificed (cost)</span>
          </div>
        </div>
      </div>

      <div className={styles.gallery}>
        <div className={styles.chartHead}>
          <b>Case gallery</b>
          <span>
            {stats.near} blocked · {stats.wrong} leaked
          </span>
        </div>
        <div className={styles.tabs}>
          {TABS.map(([k, label]) => (
            <button
              key={k}
              className={`${styles.tab} ${filter === k ? styles.tabOn : ""}`}
              onClick={() => setFilter(k)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className={styles.cards}>
          {gallery.map((c) => {
            const b = breakdown(c, active);
            const hard = hardBlockReason(c, active);
            return (
              <div key={c.dataset + c.photo} className={styles.card}>
                <div className={styles.photo}>
                  <img src={c.image} alt="" loading="lazy" />
                  <span
                    className={`${styles.badge} ${galleryIsPOI ? styles.badgePOI : styles.badgeNear}`}
                  >
                    {galleryIsPOI ? "POI" : "Near"}
                  </span>
                </div>
                <div className={styles.cardRow}>
                  <span className={styles.cardKey}>pred</span>{" "}
                  <span className={styles.cardVal}>{c.pred || "—"}</span>
                </div>
                <div className={styles.cardRow}>
                  <span className={styles.cardKey}>GT</span>{" "}
                  <span className={c.correct ? styles.good : styles.bad}>{c.gt || "—"}</span>{" "}
                  {c.correct ? "✓" : "✗"}
                </div>
                <div className={styles.cardMeta}>
                  <span className={styles.metaChip}>
                    s {b.total.toFixed(2)}
                    {!hard && b.total < active.tau ? ` < τ` : ""}
                  </span>
                  <span className={styles.metaChip}>
                    margin {c.margin_m != null ? `${c.margin_m.toFixed(0)} m` : "—"}
                  </span>
                  <span className={styles.metaChip}>OCR {strengthOf(c)}</span>
                  {c.generic_name && <span className={styles.metaChip}>generic</span>}
                  {c.vlm_support && <span className={styles.metaChip}>VLM</span>}
                  <span className={styles.metaChip}>{c.n_cand} cand</span>
                  {!galleryIsPOI && (
                    <span className={styles.metaChip}>{hard ?? nearReason(c, active)}</span>
                  )}
                </div>
                {!galleryIsPOI && (
                  <div className={styles.contrib}>
                    <span>m {b.margin.toFixed(2)}</span>
                    <span>o {b.ocr.toFixed(2)}</span>
                    {b.spatial > 0 && <span>s {b.spatial.toFixed(2)}</span>}
                    {b.dist > 0 && <span>d {b.dist.toFixed(2)}</span>}
                    {b.density > 0 && <span>−ρ {b.density.toFixed(2)}</span>}
                    {b.generic > 0 && <span>−g {b.generic.toFixed(2)}</span>}
                    {b.vlm > 0 && <span>v {b.vlm.toFixed(2)}</span>}
                  </div>
                )}
              </div>
            );
          })}
          {gallery.length === 0 && (
            <p className={styles.chartCaption}>
              No cases in this bucket at τ {active.tau.toFixed(2)}.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
