import type { ConfSimCase, OcrStrength } from "./api";

/**
 * Shared confidence-gate model: score, hard pre-filters, τ fitting, cohort
 * evaluation, and a client-side coordinate-ascent weight optimizer.
 *
 * GT (`c.correct`) is NEVER a score input — it is only used to *evaluate* a
 * cohort after the fact. See docs/confidence-gate.md.
 *
 * Hard gates are split:
 *   · spatialStrict — block when weighted pick ≠ physical nearest
 *   · requireDecisiveEvidence — mirror decide(): non-ambiguous + (OCR | large margin)
 * Faithful enables both; explore enables neither (soft spatial via w_s).
 */

/** Tunable gate params (client-side). */
export interface Params {
  tau: number;
  R: number; // density radius (m)
  mRef: number; // margin reference (m)
  dRef: number; // nearest-distance reference (m)
  /** Hard-block when weighted pick ≠ physical nearest. */
  spatialStrict: boolean;
  /**
   * Faithful decide()-style hard gates: block ambiguous resolution and require
   * OCR support or margin ≥ M_ref (VLM alone cannot open the gate).
   */
  requireDecisiveEvidence: boolean;
  wM: number;
  wO: number;
  wS: number; // soft spatial weight (used when !spatialStrict)
  wD: number;
  wRho: number; // density; may go negative when crowding is protective
  wG: number;
  wV: number; // VLM contribution cap when corroborates
  wCat: number; // photo scene↔pick agreement cap (corroborates, cannot open alone)
  /**
   * Per-category correctness prior weight. Scales a signed adjustment learned
   * from TRAIN GT (empirical-Bayes shrunk hit-rate per pick category, centered
   * on the global rate) — below-average categories subtract confidence,
   * above-average add. 0 disables. See `catPrior` for the fitted table.
   */
  wCatPrior: number;
  /**
   * Fitted per-category prior table. Must be fit on a train set only (never the
   * case being scored — that leaks GT). null → the wCatPrior term is inert.
   */
  catPrior: CatPrior | null;
}

export type Preset = "faithful" | "explore";

/** How labeled POIs are scored against GT (eval only — never a gate input). */
export type CorrectMode = "exact" | "relations";

const K = 4; // density crowding scale

/** faithful: reproduce current decide() (docs §Presets). */
export const FAITHFUL: Params = {
  tau: 1.0,
  R: 80,
  mRef: 60,
  dRef: 100,
  spatialStrict: true,
  requireDecisiveEvidence: true,
  wM: 1.0,
  wO: 1.0,
  wS: 0,
  wD: 0,
  wRho: 0,
  wG: 0.5,
  wV: 0.3,
  wCat: 0,
  wCatPrior: 0,
  catPrior: null,
};

/** explore: fold density / distance into the search for a better gate. */
export const EXPLORE: Params = {
  tau: 1.0,
  R: 80,
  mRef: 60,
  dRef: 100,
  spatialStrict: false,
  requireDecisiveEvidence: false,
  wM: 1.0,
  wO: 1.0,
  wS: 0.5,
  wD: 0.5,
  wRho: 0.5,
  wG: 0.5,
  wV: 0.3,
  wCat: 0.3,
  wCatPrior: 0,
  catPrior: null,
};

export function ocrTermValue(strength: OcrStrength | undefined): number {
  if (strength === "full") return 1.0;
  if (strength === "tokens") return 0.7;
  return 0;
}

export function strengthOf(c: ConfSimCase): OcrStrength {
  if (c.ocr_strength === "full" || c.ocr_strength === "tokens" || c.ocr_strength === "none") {
    return c.ocr_strength;
  }
  // Backward compat if an older server only sent the boolean.
  return c.ocr_supported ? "full" : "none";
}

/** Resolve GT correctness for KPI buckets (eval-only). */
export function caseIsCorrect(c: ConfSimCase, mode: CorrectMode): boolean {
  if (mode === "relations") {
    return c.correct_relations ?? c.correct;
  }
  return c.correct_exact ?? c.correct;
}

/** Overlay the active correct-mode onto `c.correct` for shared helpers. */
export function withCorrectMode(cases: ConfSimCase[], mode: CorrectMode): ConfSimCase[] {
  return cases.map((c) => ({ ...c, correct: caseIsCorrect(c, mode) }));
}

/* ------------------------------------------------------------------ */
/* Per-category correctness prior (empirical-Bayes shrinkage)          */
/* ------------------------------------------------------------------ */

export interface CatStat {
  n: number; // train support for this category
  correct: number; // train correct count
  raw: number; // raw correct rate (n>0)
  shrunk: number; // empirical-Bayes shrunk rate (pulled toward global)
  adj: number; // shrunk − global (0 when below min-support)
  active: boolean; // met min-support → contributes a nonzero adjustment
}

export interface CatPrior {
  global: number; // train global correct rate
  alpha: number; // EB shrinkage pseudo-count (prior strength)
  minSupport: number; // categories below this get no adjustment (df control)
  n: number; // train size the prior was fit on
  stats: Record<string, CatStat>;
}

/** Normalize a pick category into a stable bucket key ("(none)" when absent). */
export function catKey(c: ConfSimCase): string {
  const k = (c.pick_category || "").trim().toLowerCase();
  return k || "(none)";
}

/**
 * Fit a per-category correctness prior from TRAIN GT only. Empirical-Bayes:
 * each category's rate is pulled toward the global rate with pseudo-count
 * `alpha` (Beta-Binomial posterior mean), so low-support categories regress to
 * global instead of trusting 1–2 samples. Categories with fewer than
 * `minSupport` train cases get no adjustment at all (a harder df floor). The
 * result is a fixed lookup applied out-of-sample — never to the case it was fit
 * on (that would leak GT). `mode` selects exact vs relations correctness.
 */
export function fitCatPrior(
  train: ConfSimCase[],
  mode: CorrectMode,
  alpha = 8,
  minSupport = 8,
): CatPrior {
  const n = train.length;
  let gCorrect = 0;
  const agg: Record<string, { n: number; c: number }> = {};
  for (const c of train) {
    const ok = caseIsCorrect(c, mode);
    if (ok) gCorrect++;
    const k = catKey(c);
    const a = (agg[k] ||= { n: 0, c: 0 });
    a.n++;
    if (ok) a.c++;
  }
  const global = n ? gCorrect / n : 0;
  const stats: Record<string, CatStat> = {};
  for (const [k, a] of Object.entries(agg)) {
    const raw = a.n ? a.c / a.n : global;
    const shrunk = (a.c + alpha * global) / (a.n + alpha);
    const active = a.n >= minSupport;
    stats[k] = { n: a.n, correct: a.c, raw, shrunk, adj: active ? shrunk - global : 0, active };
  }
  return { global, alpha, minSupport, n, stats };
}

/** Signed confidence adjustment for a case from the fitted prior ([-1,1]). */
export function catAdjust(c: ConfSimCase, prior: CatPrior | null | undefined): number {
  if (!prior) return 0;
  const s = prior.stats[catKey(c)];
  if (!s) return 0; // category unseen in train → global → no deviation
  return Math.min(Math.max(s.adj, -1), 1);
}

export interface TermBreakdown {
  margin: number;
  ocr: number;
  spatial: number;
  dist: number;
  density: number;
  generic: number;
  vlm: number;
  scene: number;
  catPrior: number;
  total: number;
}

/** Interpretable additive confidence score — docs/confidence-gate.md §2. */
export function breakdown(c: ConfSimCase, p: Params): TermBreakdown {
  const marginRaw = c.margin_m != null ? Math.min(Math.max(c.margin_m / p.mRef, 0), 1) : 0;
  const ocrRaw = ocrTermValue(strengthOf(c));
  const spatialRaw = c.spatial_agreement ? 1 : 0;
  const distRaw =
    c.app_poi_dist_m != null ? Math.min(Math.max(1 - c.app_poi_dist_m / p.dRef, 0), 1) : 0;
  const nR = (c.cand_dists || []).filter((d) => d <= p.R).length;
  const densityRaw = Math.min(Math.max((nR - 1) / K, 0), 1);
  const genericRaw = c.generic_name ? 1 : 0;
  const vlmRaw = c.vlm_support ? 1 : 0;
  // Continuous scene↔pick agreement [0,1] from VNClassifyImageRequest (a-priori).
  const sceneRaw = Math.min(Math.max(c.scene_agreement ?? 0, 0), 1);

  const margin = p.wM * marginRaw;
  const ocr = p.wO * ocrRaw;
  // Soft spatial only when not hard-filtering; faithful uses hard pre-filter.
  const spatial = p.spatialStrict ? 0 : p.wS * spatialRaw;
  const dist = p.wD * distRaw;
  // w_ρ may be negative (learned): then crowding *adds* confidence.
  const density = p.wRho * densityRaw;
  const generic = p.wG * genericRaw;
  // Doc: vlm_term corroborates 1/0 with cap 0.3 — weight w_v is that cap.
  const vlm = p.wV >= 0 ? Math.min(p.wV * vlmRaw, p.wV) : p.wV * vlmRaw;
  // Scene corroborates like VLM: capped at w_cat, cannot open the gate alone.
  const scene = p.wCat >= 0 ? Math.min(p.wCat * sceneRaw, p.wCat) : p.wCat * sceneRaw;
  // Per-category prior: signed. Below-average categories subtract confidence,
  // above-average add. Fit on train GT only (p.catPrior) — a-priori at runtime
  // (the pick's category is known without GT); the rates are a learned prior.
  const catPrior = p.wCatPrior * catAdjust(c, p.catPrior);

  const total = margin + ocr + spatial + dist - density - generic + vlm + scene + catPrior;
  return { margin, ocr, spatial, dist, density, generic, vlm, scene, catPrior, total };
}

export function score(c: ConfSimCase, p: Params): number {
  return breakdown(c, p).total;
}

/**
 * Hard pre-filters force Near (unscored); else s ≥ τ → labeled.
 *
 * Always: 0 candidates · single candidate without OCR.
 * spatialStrict: weighted ≠ physical nearest.
 * requireDecisiveEvidence: ambiguous resolution · no OCR and margin < M_ref
 * (VLM alone cannot open — mirrors decide()).
 */
export function hardBlockReason(c: ConfSimCase, p: Params): string | null {
  if (c.no_candidates || c.n_cand === 0) return "NO_USABLE_CANDIDATES";
  if (p.spatialStrict && c.spatial_conflict) return "WEIGHTED_NEAREST_CONFLICT";
  const ocrOk = strengthOf(c) !== "none";
  if ((c.single_candidate || c.n_cand === 1) && !ocrOk) {
    return "SINGLE_CANDIDATE_UNCORROBORATED";
  }
  if (p.requireDecisiveEvidence) {
    if (c.decision === "ambiguous") return "AMBIGUOUS_MARGIN";
    const largeMargin = c.margin_m != null && c.margin_m >= p.mRef;
    if (!ocrOk && !largeMargin) {
      return "NO_STRONG_OCR";
    }
  }
  return null;
}

export function labeled(c: ConfSimCase, p: Params): boolean {
  if (hardBlockReason(c, p)) return false;
  return score(c, p) >= p.tau;
}

/**
 * Compare gate `labeled` to product `decide()` action on the same payload.
 * Faithful at default τ should be AUTO_PICK ≡ labeled (hard gates are load-bearing;
 * score alone is not an equivalent of decide()).
 */
export interface PolicyAgreement {
  n: number;
  autoN: number;
  labeledN: number;
  agree: number;
  disagree: { dataset: string; photo: string; auto: boolean; labeled: boolean }[];
}

export function policyAgreement(cases: ConfSimCase[], p: Params): PolicyAgreement {
  let autoN = 0;
  let labeledN = 0;
  let agree = 0;
  const disagree: PolicyAgreement["disagree"] = [];
  for (const c of cases) {
    const isAuto = c.action === "AUTO_PICK";
    const isLab = labeled(c, p);
    if (isAuto) autoN++;
    if (isLab) labeledN++;
    if (isAuto === isLab) agree++;
    else disagree.push({ dataset: c.dataset, photo: c.photo, auto: isAuto, labeled: isLab });
  }
  return { n: cases.length, autoN, labeledN, agree, disagree };
}

/** Faithful core locks — hard gates + weights that make AUTO ≡ labeled at τ=1. */
export function isFaithfulCore(p: Params): boolean {
  return (
    p.spatialStrict &&
    p.requireDecisiveEvidence &&
    p.mRef === FAITHFUL.mRef &&
    p.wM === FAITHFUL.wM &&
    p.wO === FAITHFUL.wO &&
    p.wS === FAITHFUL.wS &&
    p.wD === FAITHFUL.wD &&
    p.wRho === FAITHFUL.wRho &&
    p.wG === FAITHFUL.wG &&
    p.wV === FAITHFUL.wV &&
    p.wCat === FAITHFUL.wCat &&
    p.wCatPrior === FAITHFUL.wCatPrior
  );
}

export type Bucket = "correct" | "wrong" | "near";
export function bucketOf(c: ConfSimCase, p: Params): Bucket {
  if (!labeled(c, p)) return "near";
  return c.correct ? "correct" : "wrong";
}

/**
 * Primary Near reason: hard filters first, else the largest missing contribution
 * that kept s below τ (drives the signal-contribution panel).
 */
export function nearReason(c: ConfSimCase, p: Params): string {
  const hard = hardBlockReason(c, p);
  if (hard) return hard;
  const b = breakdown(c, p);
  if (b.total >= p.tau) return "BELOW_TAU"; // shouldn't appear for Near
  // Rank positive missing terms and active penalties.
  const deficits: { name: string; value: number }[] = [];
  if (b.margin < p.wM * 0.99) deficits.push({ name: "AMBIGUOUS_MARGIN", value: p.wM - b.margin });
  if (b.ocr < 1e-9) deficits.push({ name: "NO_STRONG_OCR", value: p.wO });
  if (!p.spatialStrict && !c.spatial_agreement && p.wS > 0) {
    deficits.push({ name: "WEIGHTED_NEAREST_CONFLICT", value: p.wS });
  }
  if (b.density > 1e-9) deficits.push({ name: "DENSITY_CROWDING", value: b.density });
  if (b.generic > 1e-9) deficits.push({ name: "GENERIC_NAME", value: b.generic });
  if (b.catPrior < -1e-9) deficits.push({ name: "CATEGORY_PRIOR_LOW", value: -b.catPrior });
  if (b.dist < p.wD * 0.5 && p.wD > 0) {
    deficits.push({ name: "FAR_NEAREST", value: p.wD - b.dist });
  }
  deficits.sort((a, b0) => b0.value - a.value);
  return deficits[0]?.name ?? "BELOW_TAU";
}

/**
 * τ score ceiling for a cohort under params `p`. Under explore/learned weights
 * a case's additive score can exceed 2, so a fixed τ_max would truncate the
 * frontier and let Auto report a τ that still leaks. Span τ up to the max score
 * among τ-gated cases (hard-blocked cases are Near regardless); floor at 2 so
 * the default faithful range stays stable.
 */
export function scoreCeiling(cases: ConfSimCase[], p: Params): number {
  let m = 1;
  for (const c of cases) if (!hardBlockReason(c, p)) m = Math.max(m, score(c, p));
  return Math.max(2, Math.ceil(m * 20) / 20);
}

export interface FitTauResult {
  /** Loosest τ within budget (or strictest τ if budget is infeasible). */
  tau: number;
  /** False when even the strictest τ still exceeds the wrong budget. */
  feasible: boolean;
  /** Wrong-labeled % of n at τ = sMax (lower bound of leak for this weight set). */
  minWrongPct: number;
  /** Wrong-labeled count at the returned τ. */
  wrongAtTau: number;
}

/**
 * Loosest τ (max coverage) whose wrong-labeled share stays within `budgetPct`
 * of `cases`. Monotone in τ, so the first budget violation ends the sweep.
 * When even τ=sMax leaks more than the budget, returns that τ with feasible=false.
 */
export function fitTau(
  cases: ConfSimCase[],
  p: Params,
  budgetPct: number,
  sMax: number,
): FitTauResult {
  const n = cases.length;
  if (!n) {
    return { tau: p.tau, feasible: true, minWrongPct: 0, wrongAtTau: 0 };
  }

  const wrongAt = (t: number): number => {
    let w = 0;
    for (const c of cases) if (labeled(c, { ...p, tau: t }) && !c.correct) w++;
    return w;
  };

  const wrongStrict = wrongAt(sMax);
  const minWrongPct = (100 * wrongStrict) / n;
  const feasible = minWrongPct <= budgetPct + 1e-9;

  let best = sMax;
  if (feasible) {
    for (let t = sMax; t >= -1e-9; t -= 0.05) {
      const wrong = wrongAt(t);
      if ((100 * wrong) / n <= budgetPct) best = t;
      else break;
    }
  }

  const tau = Math.round(best * 100) / 100;
  return {
    tau,
    feasible,
    minWrongPct,
    wrongAtTau: wrongAt(tau),
  };
}

export interface CohortEval {
  n: number;
  correct: number;
  wrong: number;
  labeledN: number;
  coverage: number; // labeled / n
  precision: number; // correct / labeled
  wrongPct: number; // 100 * wrong / n
}

export function evaluate(cases: ConfSimCase[], p: Params): CohortEval {
  let correct = 0;
  let wrong = 0;
  for (const c of cases) {
    if (labeled(c, p)) c.correct ? correct++ : wrong++;
  }
  const n = cases.length;
  const labeledN = correct + wrong;
  return {
    n,
    correct,
    wrong,
    labeledN,
    coverage: n ? labeledN / n : 0,
    precision: labeledN ? correct / labeledN : 1,
    wrongPct: n ? (100 * wrong) / n : 0,
  };
}

/* ------------------------------------------------------------------ */
/* Deterministic train / val split                                     */
/* ------------------------------------------------------------------ */

// FNV-1a — stable across renders (no Math.random), so the split never reshuffles.
function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export interface Split {
  train: ConfSimCase[];
  val: ConfSimCase[];
}

/** Deterministic hash split; `seed` re-partitions without touching order. */
export function splitCases(cases: ConfSimCase[], valFrac = 0.3, seed = 0): Split {
  const train: ConfSimCase[] = [];
  const val: ConfSimCase[] = [];
  for (const c of cases) {
    const h = hashStr(`${seed}:${c.dataset}/${c.photo}`) % 1000;
    if (h / 1000 < valFrac) val.push(c);
    else train.push(c);
  }
  return { train, val };
}

/* ------------------------------------------------------------------ */
/* K-fold cross-validation (generalization check)                      */
/* ------------------------------------------------------------------ */

export interface FoldResult {
  fold: number;
  n: number; // held-out cases in this fold
  tau: number; // τ fit on the other folds
  valCov: number;
  valWrong: number; // % of fold
  feasible: boolean;
}

export interface CrossVal {
  k: number;
  budget: number;
  folds: FoldResult[];
  meanCov: number;
  stdCov: number;
  meanWrong: number;
  stdWrong: number;
  feasibleFolds: number;
}

/** Stable fold assignment by hash (independent of the train/val split seed). */
function foldOf(c: ConfSimCase, k: number, seed: number): number {
  return hashStr(`${seed}:cv:${c.dataset}/${c.photo}`) % k;
}

/** Refit the per-category prior on each fold's train split (leak-free CV). */
export interface CatCvConfig {
  mode: CorrectMode;
  alpha: number;
  minSupport: number;
}

/**
 * K-fold CV of a *fixed* weight direction: each fold is held out as val, τ is
 * refit on the other k−1 folds at `budget`, then val is scored. Reports mean ±
 * std of val coverage / wrong-leak so a single lucky split can't pass for
 * generalization. Only the weights are fixed — τ is refit per fold (correct CV).
 *
 * When `catCfg` is given, the per-category prior is *also* refit on each fold's
 * train split (ignoring any incoming `weights.catPrior`), so the held-out fold
 * never sees a prior estimated from its own cases. This is the only trustworthy
 * generalization number for the category prior — an in-sample fit inflates it.
 */
export function crossValidate(
  cases: ConfSimCase[],
  weights: Params,
  budget: number,
  k = 5,
  seed = 0,
  catCfg: CatCvConfig | null = null,
): CrossVal {
  const folds: FoldResult[] = [];
  const covs: number[] = [];
  const wrongs: number[] = [];
  let feasibleFolds = 0;
  for (let f = 0; f < k; f++) {
    const train: ConfSimCase[] = [];
    const val: ConfSimCase[] = [];
    for (const c of cases) (foldOf(c, k, seed) === f ? val : train).push(c);
    if (!val.length || !train.length) {
      folds.push({ fold: f, n: val.length, tau: weights.tau, valCov: 0, valWrong: 0, feasible: false });
      continue;
    }
    // Refit the category prior on this fold's train only, so val stays held-out.
    const fw: Params = catCfg
      ? { ...weights, catPrior: fitCatPrior(train, catCfg.mode, catCfg.alpha, catCfg.minSupport) }
      : weights;
    const sMax = scoreCeiling(train, fw);
    const fit = fitTau(train, fw, budget, sMax);
    const va = evaluate(val, { ...fw, tau: fit.tau });
    if (fit.feasible) feasibleFolds++;
    folds.push({
      fold: f,
      n: val.length,
      tau: fit.tau,
      valCov: va.coverage,
      valWrong: va.wrongPct,
      feasible: fit.feasible,
    });
    covs.push(va.coverage);
    wrongs.push(va.wrongPct);
  }
  const mean = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0);
  const std = (a: number[], m: number) =>
    a.length ? Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / a.length) : 0;
  const meanCov = mean(covs);
  const meanWrong = mean(wrongs);
  return {
    k,
    budget,
    folds,
    meanCov,
    stdCov: std(covs, meanCov),
    meanWrong,
    stdWrong: std(wrongs, meanWrong),
    feasibleFolds,
  };
}

/* ------------------------------------------------------------------ */
/* Coordinate-ascent weight optimizer (constrained + regularized)      */
/* ------------------------------------------------------------------ */

export type LearnKey = "wM" | "wD" | "wS" | "wV" | "wRho" | "wCat";

export interface Coord {
  key: LearnKey;
  label: string;
  min: number;
  max: number;
}

/**
 * Only the "live" signals are learned. OCR is dead (≈AUC .50 on this cohort) so
 * w_o is pinned to 0; generic penalty (w_g) stays a fixed prior. w_ρ may go
 * negative because crowding turned out protective, not confusing. w_cat (photo
 * scene) is a corroboration term, capped small so it cannot open the gate alone.
 */
export const LEARNABLE: Coord[] = [
  { key: "wM", label: "w_m margin", min: 0, max: 2 },
  { key: "wD", label: "w_d dist", min: 0, max: 2 },
  { key: "wS", label: "w_s spatial", min: 0, max: 2 },
  { key: "wV", label: "w_v VLM", min: 0, max: 1 },
  { key: "wRho", label: "w_ρ density", min: -1, max: 1 },
  { key: "wCat", label: "w_cat scene", min: 0, max: 0.5 },
];

/** Base params the optimizer starts from (explore-like, OCR pinned off). */
export const LEARN_BASE: Params = {
  ...EXPLORE,
  spatialStrict: false,
  requireDecisiveEvidence: false,
  wO: 0,
  wCatPrior: 0,
  catPrior: null,
};

export interface LearnConfig {
  budget: number; // allowed wrong-labeled % (fit on train)
  lambda: number; // L2 pull toward the prior (regularization)
  valFrac: number;
  seed: number;
}

export interface HistoryPoint {
  iter: number;
  trainCov: number;
  valCov: number;
  trainWrong: number;
  valWrong: number;
  tau: number;
  feasible: boolean;
}

export interface Checkpoint {
  iter: number;
  params: Params; // full params incl. fitted τ
  valCov: number;
  valWrong: number;
  trainCov: number;
}

export interface LearnState {
  params: Params; // current weights (τ is the train-fitted τ)
  coordIdx: number; // next coordinate to probe
  iter: number;
  step: number; // current coordinate step size (anneals)
  stalls: number; // consecutive coords with no accepted move
  history: HistoryPoint[];
  best: Checkpoint | null; // best-by-val checkpoint (early stopping)
  done: boolean;
  probing: LearnKey | null; // coordinate touched by the last step (for UI)
  lastLog: string;
  /** Latest train fitTau feasibility (for UI banners). */
  trainFeasible: boolean;
  minWrongPct: number;
}

const STEP0 = 0.2;
const STEP_MIN = 0.03;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

function reg(p: Params, cfg: LearnConfig): number {
  let s = 0;
  for (const c of LEARNABLE) {
    const d = p[c.key] - LEARN_BASE[c.key];
    s += d * d;
  }
  return cfg.lambda * s;
}

/** Search objective: train coverage at the budget-fitted τ, minus L2 pull. */
function objective(
  weights: Params,
  train: ConfSimCase[],
  cfg: LearnConfig,
): { j: number; tau: number; trainCov: number; feasible: boolean; minWrongPct: number } {
  const sMax = scoreCeiling(train, weights);
  const fit = fitTau(train, weights, cfg.budget, sMax);
  const tr = evaluate(train, { ...weights, tau: fit.tau });
  // Infeasible budgets get a hard penalty so the search prefers weight sets that
  // can actually meet the wrong-leak constraint at some τ.
  const j = (fit.feasible ? tr.coverage : -1) - reg(weights, cfg);
  return {
    j,
    tau: fit.tau,
    trainCov: tr.coverage,
    feasible: fit.feasible,
    minWrongPct: fit.minWrongPct,
  };
}

export function initLearn(): LearnState {
  return {
    params: { ...LEARN_BASE, tau: LEARN_BASE.tau },
    coordIdx: 0,
    iter: 0,
    step: STEP0,
    stalls: 0,
    history: [],
    best: null,
    done: false,
    probing: null,
    lastLog: "ready — press Run",
    trainFeasible: true,
    minWrongPct: 0,
  };
}

/**
 * One coordinate-ascent tick: probe the current coordinate ±step, accept the
 * best improvement to the train objective, refit τ, record train/val metrics,
 * and update the best-by-val checkpoint. Pure — drive it from a timer.
 */
export function learnStep(
  s: LearnState,
  train: ConfSimCase[],
  val: ConfSimCase[],
  cfg: LearnConfig,
): LearnState {
  if (s.done) return s;
  const coord = LEARNABLE[s.coordIdx];
  const cur = objective(s.params, train, cfg);
  let bestW = s.params;
  let bestJ = cur.j;
  let moved = false;
  let from = s.params[coord.key];
  let to = from;

  for (const d of [s.step, -s.step]) {
    const v = clamp(from + d, coord.min, coord.max);
    if (Math.abs(v - from) < 1e-9) continue;
    const cand = { ...s.params, [coord.key]: v };
    const o = objective(cand, train, cfg);
    if (o.j > bestJ + 1e-9) {
      bestJ = o.j;
      bestW = cand;
      moved = true;
      to = v;
    }
  }

  // Refit τ for the chosen weights and score both splits.
  const sMax = scoreCeiling(train, bestW);
  const fit = fitTau(train, bestW, cfg.budget, sMax);
  const params: Params = { ...bestW, tau: fit.tau };
  const tr = evaluate(train, params);
  const va = evaluate(val, params);
  const iter = s.iter + 1;

  // Cap history so long runs stay cheap to re-render.
  const nextPoint: HistoryPoint = {
    iter,
    trainCov: tr.coverage,
    valCov: va.coverage,
    trainWrong: tr.wrongPct,
    valWrong: va.wrongPct,
    tau: fit.tau,
    feasible: fit.feasible,
  };
  const history = [...s.history, nextPoint].slice(-400);

  // Best-by-val (early stopping): only checkpoints whose val leak is within
  // budget qualify — this is what defends against overfitting the train split.
  let best = s.best;
  if (va.wrongPct <= cfg.budget + 1e-9 && va.coverage > (best?.valCov ?? -1)) {
    best = {
      iter,
      params,
      valCov: va.coverage,
      valWrong: va.wrongPct,
      trainCov: tr.coverage,
    };
  }

  // Anneal the step on a full stalled cycle; stop when it is small enough.
  let step = s.step;
  let stalls = moved ? 0 : s.stalls + 1;
  let done = false;
  if (stalls >= LEARNABLE.length) {
    if (step > STEP_MIN) {
      step = step / 2;
      stalls = 0;
    } else {
      done = true;
    }
  }

  const lastLog = !fit.feasible
    ? `iter ${iter} · train budget infeasible (min leak ${fit.minWrongPct.toFixed(1)}%) · τ ${fit.tau.toFixed(2)}`
    : moved
      ? `iter ${iter} · ${coord.label} ${from.toFixed(2)}→${to.toFixed(2)} · ` +
        `train ${(tr.coverage * 100).toFixed(0)}% · val ${(va.coverage * 100).toFixed(0)}%` +
        (best?.iter === iter ? " ★ best" : "")
      : `iter ${iter} · ${coord.label} held (no gain, step ${step.toFixed(2)})`;

  return {
    params,
    coordIdx: (s.coordIdx + 1) % LEARNABLE.length,
    iter,
    step,
    stalls,
    history,
    best,
    done,
    probing: coord.key,
    lastLog,
    trainFeasible: fit.feasible,
    minWrongPct: fit.minWrongPct,
  };
}
