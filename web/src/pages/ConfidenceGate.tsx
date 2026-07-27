import { useEffect, useMemo, useState } from "react";
import { api, type ConfSnapshotCase, type ConfSnapshotMeta } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import {
  breakdown,
  bucketOf,
  type CorrectMode,
  type CrossVal,
  crossValidate,
  EXPLORE,
  evaluate,
  FAITHFUL,
  fitTau,
  hardBlockReason,
  initLearn,
  isFaithfulCore,
  labeled,
  LEARNABLE,
  LEARN_BASE,
  learnStep,
  type LearnState,
  nearReason,
  type Params,
  policyAgreement,
  type Preset,
  score,
  scoreCeiling,
  splitCases,
  strengthOf,
  withCorrectMode,
} from "../lib/gateModel";
import styles from "./ConfidenceGate.module.css";

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((100 * n) / d)}%` : "—";
}

function setNum(p: Params, key: keyof Params, v: number): Params {
  return { ...p, [key]: v };
}

type Filter = "wrongPOI" | "wrongNear" | "correctNear" | "correctPOI";
type Mode = "lab" | "auto" | "learn";

type BaseKind = "policy" | "run";

export default function ConfidenceGate() {
  const [mode, setMode] = useState<Mode>("lab");
  const [preset, setPreset] = useState<Preset>("faithful");
  const [p, setP] = useState<Params>(FAITHFUL);
  const [showWeights, setShowWeights] = useState(false);
  const [allowedWrong, setAllowedWrong] = useState(2); // Auto: max wrong-labeled % of all
  const [filter, setFilter] = useState<Filter>("wrongPOI");
  /** Exact vs product (aliases / credit≥1) — eval only, never a gate input. */
  const [correctMode, setCorrectMode] = useState<CorrectMode>("exact");

  // Base pick source: live decide() policy, or a scored Results run.
  const [baseKind, setBaseKind] = useState<BaseKind>("policy");
  const [runSel, setRunSel] = useState<{ name: string; version: number } | null>(null);
  const runsList = useAsync(() => api.runs().then((r) => r.runs), []);
  const doneRuns = useMemo(() => {
    const list = runsList.status === "ready" ? runsList.data : [];
    return [...list]
      .filter((r) => (r.status ?? "done") === "done" && typeof r.accuracy_pct === "number")
      .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  }, [runsList]);

  // Default run selection once the list loads.
  useEffect(() => {
    if (runSel || !doneRuns.length) return;
    setRunSel({ name: doneRuns[0].name, version: doneRuns[0].version });
  }, [doneRuns, runSel]);

  const simKey =
    baseKind === "policy"
      ? "policy"
      : runSel
        ? `run:${runSel.name}@${runSel.version}`
        : "run:none";

  const sim = useAsync(() => {
    if (baseKind === "run") {
      if (!runSel) return Promise.reject(new Error("Select a Results run as the base pick"));
      return api.confidenceSim("all", {
        base: "run",
        run: runSel.name,
        version: runSel.version,
      });
    }
    return api.confidenceSim("all", { base: "policy" });
  }, [simKey]);

  // --- Learn mode ------------------------------------------------------
  const [learn, setLearn] = useState<LearnState>(() => initLearn());
  const [running, setRunning] = useState(false);
  const [learnBudget, setLearnBudget] = useState(2); // wrong budget, fit on train
  const [lambda, setLambda] = useState(0.05); // L2 pull toward the prior
  const [valFrac, setValFrac] = useState(0.3);
  const [seed, setSeed] = useState(0);
  const [speed, setSpeed] = useState(6); // steps / sec
  const [cv, setCv] = useState<CrossVal | null>(null); // k-fold CV of the learned weights

  // --- Saved operating points -----------------------------------------
  const [snaps, setSnaps] = useState<ConfSnapshotMeta[]>([]);
  const [snapBusy, setSnapBusy] = useState(false);
  const [snapMsg, setSnapMsg] = useState<string | null>(null);
  const refreshSnaps = () =>
    api
      .confSnapshots()
      .then((r) => setSnaps(r.snapshots))
      .catch(() => {});
  useEffect(() => {
    refreshSnaps();
  }, []);

  const rawCases = sim.status === "ready" ? sim.data.cases : [];
  const signals = sim.status === "ready" ? sim.data.signals : undefined;
  // Overlay active correct-mode onto c.correct for KPI / Auto / Learn.
  const cases = useMemo(() => withCorrectMode(rawCases, correctMode), [rawCases, correctMode]);
  const n = cases.length;

  const split = useMemo(() => splitCases(cases, valFrac, seed), [cases, valFrac, seed]);
  const cfg = useMemo(
    () => ({ budget: learnBudget, lambda, valFrac, seed }),
    [learnBudget, lambda, valFrac, seed],
  );

  // Any config / split change invalidates the search — restart it.
  useEffect(() => {
    setLearn(initLearn());
    setRunning(false);
    setCv(null);
  }, [split, cfg]);

  // Timer-driven coordinate ascent; each tick re-renders every panel.
  useEffect(() => {
    if (mode !== "learn" || !running || learn.done) return;
    if (!split.train.length || !split.val.length) return;
    const ms = Math.max(1000 / speed, 30);
    const id = setTimeout(() => {
      setLearn((s) => learnStep(s, split.train, split.val, cfg));
    }, ms);
    return () => clearTimeout(id);
  }, [mode, running, learn, split, cfg, speed]);

  useEffect(() => {
    if (learn.done) setRunning(false);
  }, [learn.done]);

  const applyPreset = (name: Preset) => {
    setPreset(name);
    setP(name === "faithful" ? { ...FAITHFUL } : { ...EXPLORE });
    // Faithful locks weights/hard gates — only τ is free. Explore opens the rest.
    setShowWeights(name === "explore");
  };

  const touch = (next: Params) => {
    // Leaving the faithful weight/hard-gate core → explore (score-only drift is explicit).
    if (preset === "faithful" && !isFaithfulCore(next)) {
      setPreset("explore");
      setShowWeights(true);
    }
    setP(next);
  };

  /** Faithful: hard gates + decide()-matching weights locked; τ remains the only free knob. */
  const faithfulLocked = preset === "faithful";

  // Score ceiling for the τ range (see gateModel.scoreCeiling).
  const sMax = useMemo(() => scoreCeiling(cases, p), [cases, p]);

  const autoFit = useMemo(() => {
    if (mode !== "auto" || !n) {
      return { tau: p.tau, feasible: true, minWrongPct: 0, wrongAtTau: 0 };
    }
    return fitTau(cases, p, allowedWrong, sMax);
  }, [mode, allowedWrong, cases, n, p, sMax]);

  const autoTau = autoFit.tau;
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

  const simBase = sim.status === "ready" ? sim.data.base : undefined;
  const isPolicyBase = (simBase?.kind ?? baseKind) === "policy";

  // Product decide() AUTO_PICK vs gate labeled — only meaningful for policy base.
  const agreement = useMemo(() => policyAgreement(cases, active), [cases, active]);
  const agreementOk = agreement.n > 0 && agreement.disagree.length === 0;

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

  // --- Learn-mode derived metrics -------------------------------------
  const trainEval = useMemo(() => evaluate(split.train, learn.params), [split.train, learn.params]);
  const valEval = useMemo(() => evaluate(split.val, learn.params), [split.val, learn.params]);
  const valFrontier = useMemo(() => {
    const sc = scoreCeiling(split.val, learn.params);
    const pts: { coverage: number; precision: number }[] = [];
    const steps = 24;
    const nv = split.val.length;
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * sc;
      let lc = 0,
        lw = 0;
      for (const c of split.val) if (labeled(c, { ...learn.params, tau: t })) c.correct ? lc++ : lw++;
      const lab = lc + lw;
      pts.push({ coverage: nv ? lab / nv : 0, precision: lab ? lc / lab : 1 });
    }
    return pts;
  }, [split.val, learn.params]);

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

  // --- Save / load the current operating point ------------------------
  const buildSnapshotCases = (): ConfSnapshotCase[] =>
    cases.map((c) => {
      const b = bucketOf(c, active);
      return {
        dataset: c.dataset,
        photo: c.photo,
        bucket: b,
        correct: c.correct,
        score: Number(score(c, active).toFixed(3)),
        near_reason: b === "near" ? nearReason(c, active) : null,
      };
    });

  const saveOperatingPoint = async () => {
    const who = baseKind === "run" && runSel ? runSel.name : "policy";
    const suggested = `${who}-${preset}-cov${Math.round(cov * 100)}`;
    const name = window.prompt("Save this operating point as:", suggested);
    if (!name || !name.trim()) return;
    setSnapBusy(true);
    setSnapMsg(null);
    try {
      await api.saveConfSnapshot({
        name: name.trim(),
        base: baseKind,
        run_name: baseKind === "run" ? (runSel?.name ?? null) : null,
        run_version: baseKind === "run" ? (runSel?.version ?? null) : null,
        dataset: "all",
        eval_mode: correctMode,
        preset,
        mode,
        budget: mode === "auto" ? allowedWrong : null,
        params: active as unknown as Record<string, number | boolean>,
        kpis: {
          n,
          coverage: cov,
          precision: prec,
          correct: stats.correct,
          wrong: stats.wrong,
          near: stats.near,
          wrongPct: n ? (100 * stats.wrong) / n : 0,
          labeledN: stats.labeledN,
          agree: agreement.agree,
          autoN: agreement.autoN,
        },
        cases: buildSnapshotCases(),
      });
      await refreshSnaps();
      setSnapMsg(`saved “${name.trim()}”`);
    } catch (e) {
      setSnapMsg(`save failed: ${(e as Error).message}`);
    } finally {
      setSnapBusy(false);
    }
  };

  const loadSnapshot = async (id: string) => {
    setSnapBusy(true);
    setSnapMsg(null);
    try {
      const snap = await api.confSnapshot(id);
      if (snap.base === "run" && snap.run_name && snap.run_version != null) {
        setBaseKind("run");
        setRunSel({ name: snap.run_name, version: snap.run_version });
      } else {
        setBaseKind("policy");
      }
      if (snap.eval_mode) setCorrectMode(snap.eval_mode);
      if (snap.params) {
        setP({ ...(snap.params as unknown as Params) });
        const pr = snap.preset ?? "explore";
        setPreset(pr);
        setShowWeights(pr === "explore");
      }
      if (snap.budget != null) setAllowedWrong(snap.budget);
      setMode(snap.mode === "auto" ? "auto" : "lab");
      setSnapMsg(`loaded “${snap.name}” — tuned into Lab`);
    } catch (e) {
      setSnapMsg(`load failed: ${(e as Error).message}`);
    } finally {
      setSnapBusy(false);
    }
  };

  const deleteSnapshot = async (id: string, name: string) => {
    if (!window.confirm(`Delete saved operating point “${name}”?`)) return;
    setSnapBusy(true);
    try {
      await api.deleteConfSnapshot(id);
      await refreshSnaps();
      setSnapMsg(`deleted “${name}”`);
    } catch (e) {
      setSnapMsg(`delete failed: ${(e as Error).message}`);
    } finally {
      setSnapBusy(false);
    }
  };

  // Save the learned best weights directly, embedding the k-fold CV summary so
  // the honest (cross-validated) generalization number rides along.
  const saveLearned = async () => {
    const best = learn.best?.params ?? learn.params;
    const bestCov = learn.best?.valCov ?? 0;
    const name = window.prompt(
      "Save learned operating point as:",
      `learn-b${learnBudget}-val${Math.round(bestCov * 100)}`,
    );
    if (!name || !name.trim()) return;
    const full = evaluate(cases, best);
    setSnapBusy(true);
    setSnapMsg(null);
    try {
      await api.saveConfSnapshot({
        name: name.trim(),
        base: baseKind,
        run_name: baseKind === "run" ? (runSel?.name ?? null) : null,
        run_version: baseKind === "run" ? (runSel?.version ?? null) : null,
        dataset: "all",
        eval_mode: correctMode,
        preset: "explore",
        mode: "learn",
        budget: learnBudget,
        params: best as unknown as Record<string, number | boolean>,
        kpis: {
          n: full.n,
          coverage: full.coverage,
          precision: full.precision,
          correct: full.correct,
          wrong: full.wrong,
          near: full.n - full.labeledN,
          wrongPct: full.wrongPct,
          labeledN: full.labeledN,
          ...(cv
            ? {
                cvMeanCov: cv.meanCov,
                cvStdCov: cv.stdCov,
                cvMeanWrong: cv.meanWrong,
                cvStdWrong: cv.stdWrong,
                cvK: cv.k,
                cvFeasibleFolds: cv.feasibleFolds,
              }
            : {}),
        },
        cases: cases.map((c) => {
          const b = bucketOf(c, best);
          return {
            dataset: c.dataset,
            photo: c.photo,
            bucket: b,
            correct: c.correct,
            score: Number(score(c, best).toFixed(3)),
            near_reason: b === "near" ? nearReason(c, best) : null,
          };
        }),
      });
      await refreshSnaps();
      setSnapMsg(`saved learned “${name.trim()}”${cv ? " (with CV)" : ""}`);
    } catch (e) {
      setSnapMsg(`save failed: ${(e as Error).message}`);
    } finally {
      setSnapBusy(false);
    }
  };

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
            After a selector picks a POI, decide whether to <b>show it</b> or fall back to{" "}
            <b>Near (area)</b> — using only runtime signals, never GT. This page tunes that gate; it
            does not re-run algorithms (use New run / Results for that).
          </p>
        </div>
        <div className={styles.controls}>
          <label className={styles.algoChip} title="Which pick the gate is judging">
            <span className={styles.ddKey}>Base pick</span>
            <select
              className={styles.baseSelect}
              value={
                baseKind === "policy"
                  ? "policy"
                  : runSel
                    ? `run:${runSel.name}::${runSel.version}`
                    : "run:"
              }
              onChange={(e) => {
                const v = e.target.value;
                if (v === "policy") {
                  setBaseKind("policy");
                  return;
                }
                if (v.startsWith("run:")) {
                  const rest = v.slice(4);
                  const i = rest.lastIndexOf("::");
                  const name = i >= 0 ? rest.slice(0, i) : rest;
                  const version = i >= 0 ? Number(rest.slice(i + 2)) : NaN;
                  if (name && Number.isFinite(version)) {
                    setBaseKind("run");
                    setRunSel({ name, version });
                  }
                }
              }}
            >
              <option value="policy">Policy · mapkit-weighted decide()</option>
              <optgroup label="Results runs">
                {doneRuns.length === 0 && (
                  <option value="run:" disabled>
                    {runsList.status === "loading" ? "Loading runs…" : "No scored runs yet"}
                  </option>
                )}
                {doneRuns.map((r) => (
                  <option key={`${r.name}@${r.version}`} value={`run:${r.name}::${r.version}`}>
                    {r.name} · v{r.version}
                    {r.accuracy_pct != null ? ` · ${r.accuracy_pct.toFixed(0)}%` : ""}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <div className={styles.toggle}>
            <button
              className={correctMode === "exact" ? styles.segOn : styles.seg}
              onClick={() => setCorrectMode("exact")}
              title="Exact GT string match (strict)"
            >
              exact
            </button>
            <button
              className={correctMode === "relations" ? styles.segOn : styles.seg}
              onClick={() => setCorrectMode("relations")}
              title="Exact + reviewed aliases / credit≥1 relations (product metric)"
            >
              relations
            </button>
          </div>
          <div className={styles.toggle}>
            <button className={mode === "lab" ? styles.segOn : styles.seg} onClick={() => setMode("lab")}>
              Lab
            </button>
            <button className={mode === "auto" ? styles.segOn : styles.seg} onClick={() => setMode("auto")}>
              Auto
            </button>
            <button
              className={mode === "learn" ? styles.segOn : styles.seg}
              onClick={() => setMode("learn")}
            >
              Learn
            </button>
          </div>
        </div>
      </div>

      {simBase?.kind === "run" && simBase.run && (
        <p className={styles.baseBanner}>
          Judging picks from Results run <b>{simBase.label}</b>
          {simBase.run.n_overlap != null && simBase.run.n_run_cases != null
            ? ` · overlap ${simBase.run.n_overlap}/${simBase.run.n_run_cases} cases`
            : ""}
          {simBase.run.accuracy_pct != null
            ? ` · run accuracy ${simBase.run.accuracy_pct.toFixed(1)}%`
            : ""}
          . Gate signals (OCR / spatial / margin) are recomputed for each run prediction against
          MapKit candidates — not re-running the selector.
        </p>
      )}

      <div className={styles.snapBar}>
        <span className={styles.snapKey}>Saved operating points</span>
        {mode !== "learn" ? (
          <button
            type="button"
            className={styles.snapSave}
            disabled={snapBusy || n === 0}
            onClick={saveOperatingPoint}
            title="Persist the current τ / weights / hard gates + the KPIs and per-case decisions they produce"
          >
            ＋ Save current
          </button>
        ) : (
          <span className={styles.snapEmpty}>Apply best → Lab, then Save</span>
        )}
        {snaps.length === 0 && <span className={styles.snapEmpty}>none saved yet</span>}
        {snaps.map((s) => {
          const cvTip =
            s.kpis?.cvMeanCov != null
              ? ` · CV val ${Math.round((s.kpis.cvMeanCov ?? 0) * 100)}±${Math.round(
                  (s.kpis.cvStdCov ?? 0) * 100,
                )}%`
              : "";
          return (
            <span key={s.id} className={styles.snapChip}>
              <button
                type="button"
                className={styles.snapChipMain}
                disabled={snapBusy}
                onClick={() => loadSnapshot(s.id)}
                title={`${s.base === "run" ? `run ${s.run_name} v${s.run_version}` : "policy"} · ${s.preset} · eval ${s.eval_mode}${
                  s.budget != null ? ` · budget ${s.budget}%` : ""
                }${cvTip} · saved ${s.updated ?? s.created ?? ""} — click to load into Lab`}
              >
                <span className={styles.snapChipName}>{s.name}</span>
                <small>
                  cov {Math.round((s.kpis?.coverage ?? 0) * 100)}% · wrong {s.kpis?.wrong ?? 0}
                  {s.kpis?.cvMeanCov != null
                    ? ` · CV ${Math.round((s.kpis.cvMeanCov ?? 0) * 100)}±${Math.round(
                        (s.kpis.cvStdCov ?? 0) * 100,
                      )}`
                    : ""}
                </small>
              </button>
              <button
                type="button"
                className={styles.snapChipDel}
                disabled={snapBusy}
                onClick={() => deleteSnapshot(s.id, s.name)}
                title="Delete this saved operating point"
              >
                ✕
              </button>
            </span>
          );
        })}
        {snapMsg && <span className={styles.snapMsg}>{snapMsg}</span>}
      </div>

      <details className={styles.guide} open={false}>
        <summary>How to use this page · Lab / Auto / Learn · why no algorithm switch</summary>
        <div className={styles.guideBody}>
          <div className={styles.guideCols}>
            <div>
              <h3>What this is (and isn&apos;t)</h3>
              <ul>
                <li>
                  <b>Is:</b> a product policy layer on top of one base picker (
                  <code>mapkit_weighted</code> → <code>poi_confidence_policy.decide()</code>).
                </li>
                <li>
                  <b>Isn&apos;t:</b> a substitute for New run / Results. Accuracy of different
                  selectors lives there; here you only tune “show POI vs Near”.
                </li>
                <li>
                  <b>Workflow:</b> Datasets → New run (pick algorithm) → Results / Compare → then
                  open <b>Confidence gate</b> to decide how aggressive labeling can be.
                </li>
              </ul>
            </div>
            <div>
              <h3>Modes</h3>
              <ul>
                <li>
                  <b>Lab</b> — hand-tune τ, R, M_ref, D_ref, hard gates, weights. Start with preset{" "}
                  <code>faithful</code> (matches current <code>decide()</code>), then try{" "}
                  <code>explore</code>.
                </li>
                <li>
                  <b>Auto</b> — fix all knobs; sweep τ so wrong-labeled ≤ budget while maximizing
                  coverage. One-knob “operating point” on the full cohort (optimistic — use Learn
                  for held-out).
                </li>
                <li>
                  <b>Learn</b> — search weights on a train split, score on val, Apply best → Lab.
                  Use when you want density/dist/VLM weights, not just τ.
                </li>
              </ul>
            </div>
            <div>
              <h3>Base pick (Results)</h3>
              <ul>
                <li>
                  <b>Policy</b> — live <code>decide()</code> on mapkit-weighted (use to match the
                  product policy / AUTO ≡ labeled).
                </li>
                <li>
                  <b>Results run</b> — the pick is that run&apos;s <code>prediction</code> per
                  case; gate signals are recomputed against MapKit candidates. This is the product
                  question: “given this Result, when do we show POI vs Near?”
                </li>
                <li>
                  Choosing a run does <em>not</em> re-execute the selector — it reuses the saved
                  run JSON from Results.
                </li>
              </ul>
            </div>
          </div>
          <p className={styles.guideFoot}>
            Eval toggle <b>exact</b> vs <b>relations</b> only changes how KPI “correct” is counted
            (GT aliases) — never a gate input. Details:{" "}
            <code>docs/confidence-gate.md</code>.
          </p>
        </div>
      </details>

      {signals && signals.ocr_supported_pct < 15 && (
        <p className={styles.warnBanner}>
          OCR support is sparse on this cohort —{" "}
          <b>
            {signals.ocr_supported}/{signals.n}
          </b>{" "}
          cases ({signals.ocr_supported_pct.toFixed(0)}%: full {signals.ocr_full} · tokens{" "}
          {signals.ocr_tokens} · none {signals.ocr_none}). Faithful OCR paths barely fire; Learn pins
          w_o=0 for that reason. VLM corroborates {signals.vlm_support}/{signals.n}
          {signals.label_relations_n > 0
            ? ` · ${signals.label_relations_n} label relations loaded`
            : ""}
          {typeof signals.scene_labeled === "number"
            ? ` · scene labels ${signals.scene_labeled}/${signals.n} (${
                signals.scene_agree ?? 0
              } agree w/ pick)`
            : ""}
          .
        </p>
      )}
      {signals &&
        signals.ocr_supported_pct >= 15 &&
        typeof signals.scene_labeled === "number" &&
        signals.scene_labeled === 0 && (
          <p className={styles.warnBanner}>
            No photo scene labels on this cohort — the <code>w_cat</code> term is inert. Run{" "}
            <code>tools/rerun_scene_classify.py</code> to precompute{" "}
            <code>scene_labels.tsv</code>.
          </p>
        )}

      {mode === "learn" ? (
        <LearnView
          learn={learn}
          running={running}
          trainN={split.train.length}
          valN={split.val.length}
          trainEval={trainEval}
          valEval={valEval}
          valFrontier={valFrontier}
          learnBudget={learnBudget}
          lambda={lambda}
          valFrac={valFrac}
          speed={speed}
          cv={cv}
          snapBusy={snapBusy}
          onCrossVal={() =>
            setCv(crossValidate(cases, learn.best?.params ?? learn.params, learnBudget, 5, seed))
          }
          onSaveLearned={saveLearned}
          setRunning={setRunning}
          setLearnBudget={setLearnBudget}
          setLambda={setLambda}
          setValFrac={setValFrac}
          setSpeed={setSpeed}
          onStep={() => setLearn((s) => learnStep(s, split.train, split.val, cfg))}
          onReset={() => {
            setLearn(initLearn());
            setRunning(false);
          }}
          onResplit={() => setSeed((s) => s + 1)}
          onApply={() => {
            const best = learn.best?.params ?? learn.params;
            setP({ ...best });
            setPreset("explore");
            setShowWeights(true);
            setMode("lab");
          }}
        />
      ) : (
        <>
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
                  <label className={styles.sliderLabel}>
                    Gate strictness
                    {faithfulLocked && (
                      <span className={styles.lockHint}> · faithful: τ only (hard gates locked)</span>
                    )}
                  </label>
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
                  onChange={(e) => {
                    // τ alone stays on faithful (operating point); other knobs call touch().
                    setP(setNum(p, "tau", Number(e.target.value)));
                  }}
                />
                <div className={styles.ends}>
                  <span>← permissive · more coverage</span>
                  <span>strict · more blocked →</span>
                </div>
                {faithfulLocked && (
                  <p className={styles.strip}>
                    Faithful reproduces <code>decide()</code> via <b>hard gates</b> (spatial + decisive
                    evidence), not score alone. Weights / hard toggles are locked — switch to{" "}
                    <b>explore</b> to change them. At τ=1.0, labeled should match AUTO_PICK.
                  </p>
                )}
                <div className={styles.knobs}>
                  <label className={`${styles.knob} ${faithfulLocked ? styles.knobDisabled : ""}`}>
                    Radius R
                    <input
                      type="range"
                      min={20}
                      max={250}
                      step={10}
                      value={p.R}
                      disabled={faithfulLocked}
                      onChange={(e) => touch(setNum(p, "R", Number(e.target.value)))}
                    />
                    <b>{p.R} m</b>
                  </label>
                  <label className={`${styles.knob} ${faithfulLocked ? styles.knobDisabled : ""}`}>
                    M_ref
                    <input
                      type="range"
                      min={20}
                      max={150}
                      step={10}
                      value={p.mRef}
                      disabled={faithfulLocked}
                      onChange={(e) => touch(setNum(p, "mRef", Number(e.target.value)))}
                    />
                    <b>{p.mRef} m</b>
                  </label>
                  <label className={`${styles.knob} ${faithfulLocked ? styles.knobDisabled : ""}`}>
                    D_ref
                    <input
                      type="range"
                      min={20}
                      max={250}
                      step={10}
                      value={p.dRef}
                      disabled={faithfulLocked}
                      onChange={(e) => touch(setNum(p, "dRef", Number(e.target.value)))}
                    />
                    <b>{p.dRef} m</b>
                  </label>
                  <label
                    className={`${styles.knob} ${styles.knobToggle} ${faithfulLocked ? styles.knobDisabled : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={p.spatialStrict}
                      disabled={faithfulLocked}
                      onChange={(e) => touch({ ...p, spatialStrict: e.target.checked })}
                    />
                    spatial strict
                  </label>
                  <label
                    className={`${styles.knob} ${styles.knobToggle} ${faithfulLocked ? styles.knobDisabled : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={p.requireDecisiveEvidence}
                      disabled={faithfulLocked}
                      onChange={(e) =>
                        touch({ ...p, requireDecisiveEvidence: e.target.checked })
                      }
                    />
                    decisive evidence
                  </label>
                  <button
                    type="button"
                    className={styles.weightsToggle}
                    disabled={faithfulLocked}
                    title={
                      faithfulLocked
                        ? "Switch to explore to edit weights"
                        : "Show per-term weights"
                    }
                    onClick={() => setShowWeights((v) => !v)}
                  >
                    {showWeights && !faithfulLocked ? "Hide weights" : "Weights"}
                  </button>
                </div>
                {showWeights && !faithfulLocked && (
                  <div className={styles.weights}>
                    {(
                      [
                        ["wM", "w_m margin", 0, 2, 0.05],
                        ["wO", "w_o OCR", 0, 2, 0.05],
                        ["wS", "w_s spatial (soft)", 0, 2, 0.05],
                        ["wD", "w_d dist", 0, 2, 0.05],
                        ["wRho", "w_ρ density", -1, 2, 0.05],
                        ["wG", "w_g generic", 0, 2, 0.05],
                        ["wV", "w_v VLM cap", 0, 1, 0.05],
                        ["wCat", "w_cat scene cap", 0, 1, 0.05],
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
                    {!autoFit.feasible && (
                      <span className={styles.bad}> · infeasible</span>
                    )}
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
                {!autoFit.feasible && (
                  <p className={`${styles.strip} ${styles.bad}`}>
                    Budget {allowedWrong}% is infeasible: even the strictest τ still leaks{" "}
                    {autoFit.minWrongPct.toFixed(1)}% wrong-labeled. Showing strictest τ; raise the
                    budget or tighten hard gates / weights.
                  </p>
                )}
                <p className={styles.strip}>
                  Auto fits τ on this cohort’s GT ({correctMode}) — treat as an estimate; validate on
                  a held-out split (see Learn). Other knobs stay at the current Lab preset ({preset}
                  ).
                </p>
              </>
            )}
            <p className={styles.strip}>
              Signals precomputed for mapkit-weighted · τ &amp; weights re-aggregate instantly · hard
              filters: 0 cand · single cand without OCR
              {p.spatialStrict ? " · spatial strict" : ""}
              {p.requireDecisiveEvidence ? " · decisive evidence (OCR|large margin, non-ambiguous)" : ""}
              {" · eval="}
              {correctMode}
            </p>
          </div>

          <div className={styles.kpiRow}>
            <div className={styles.tile}>
              <span className={`${styles.bar} ${styles.barGood}`} />
              <span className={`${styles.tileLabel} ${styles.good}`}>LABELED · CORRECT</span>
              <span className={`${styles.tileNum} ${styles.good}`}>{stats.correct}</span>
              <span className={styles.tileSub}>
                {pct(stats.correct, n)} of cases · precision {pct(stats.correct, stats.labeledN)}{" "}
                among shown POI
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
              <span className={styles.tileSub}>{pct(stats.near, n)} · area shown instead of a POI</span>
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
            {isPolicyBase ? (
              <span
                className={agreementOk ? styles.agreeOk : styles.agreeBad}
                title={
                  agreementOk
                    ? "Gate labeled matches product decide() AUTO_PICK on every case"
                    : `${agreement.disagree.length} cases disagree — expected if explore / τ≠1 / hard gates off`
                }
              >
                {agreementOk ? "✓" : "⚠"} AUTO ≡ labeled{" "}
                <b>
                  {agreement.agree}/{agreement.n}
                </b>
                {!agreementOk && (
                  <span className={styles.agreeMeta}>
                    {" "}
                    (AUTO {agreement.autoN} · gate {agreement.labeledN})
                  </span>
                )}
              </span>
            ) : (
              <span className={styles.agreeMeta} title="AUTO≡labeled only applies to policy decide() base">
                base <b>Results run</b> · n gate {agreement.labeledN}
              </span>
            )}
          </div>
          {isPolicyBase && !agreementOk && agreement.disagree.length > 0 && (
            <p className={styles.agreeDetail}>
              Disagreements (gate vs <code>decide()</code>):{" "}
              {agreement.disagree.slice(0, 6).map((d, i) => (
                <span key={d.dataset + d.photo}>
                  {i > 0 ? " · " : ""}
                  {d.photo.length > 28 ? d.photo.slice(0, 28) + "…" : d.photo}
                  {d.auto ? " AUTO→Near" : " Near→POI"}
                </span>
              ))}
              {agreement.disagree.length > 6
                ? ` · +${agreement.disagree.length - 6} more`
                : ""}
              {faithfulLocked && Math.abs(active.tau - 1) > 1e-6
                ? " — at faithful, set τ=1.0 for full AUTO match."
                : !faithfulLocked
                  ? " — explore/Auto weights are not claimed to equal decide()."
                  : ""}
            </p>
          )}

          <div className={styles.chartsRow}>
            <div className={styles.chartPanel}>
              <div className={styles.chartHead}>
                <b>Tradeoff frontier</b>
                <span>τ sweep 0→{sMax.toFixed(1)}</span>
              </div>
              <p className={styles.chartCaption}>
                Each point is a τ setting. Y = precision among shown POI · X = coverage. Pick the
                knee.
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
                Hard filters first; else the largest missing term under τ. Higher wrong-share =
                cleaner cut.
              </p>
              <div className={styles.reasons}>
                {reasons.length === 0 && <p className={styles.chartCaption}>Nothing blocked at this τ.</p>}
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
                        className={`${styles.badge} ${
                          filter === "wrongPOI"
                            ? styles.badgePOI
                            : filter === "correctPOI"
                              ? styles.badgeGood
                              : styles.badgeNear
                        }`}
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
                      {c.scene_top1 && (
                        <span className={styles.metaChip} title={c.scene_labels || ""}>
                          scene {c.scene_top1}
                          {(c.scene_agreement ?? 0) >= 0.35 ? " ✓" : ""}
                        </span>
                      )}
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
                        {b.density > 1e-9 && <span>−ρ {b.density.toFixed(2)}</span>}
                        {b.density < -1e-9 && <span>+ρ {(-b.density).toFixed(2)}</span>}
                        {b.generic > 0 && <span>−g {b.generic.toFixed(2)}</span>}
                        {b.vlm > 0 && <span>v {b.vlm.toFixed(2)}</span>}
                        {b.scene > 1e-9 && <span>cat {b.scene.toFixed(2)}</span>}
                      </div>
                    )}
                  </div>
                );
              })}
              {gallery.length === 0 && (
                <p className={styles.chartCaption}>No cases in this bucket at τ {active.tau.toFixed(2)}.</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ==================================================================== */
/* Learn view — real-time coordinate-ascent weight search               */
/* ==================================================================== */

interface LearnViewProps {
  learn: LearnState;
  running: boolean;
  trainN: number;
  valN: number;
  trainEval: ReturnType<typeof evaluate>;
  valEval: ReturnType<typeof evaluate>;
  valFrontier: { coverage: number; precision: number }[];
  learnBudget: number;
  lambda: number;
  valFrac: number;
  speed: number;
  cv: CrossVal | null;
  snapBusy: boolean;
  onCrossVal: () => void;
  onSaveLearned: () => void;
  setRunning: (v: boolean | ((p: boolean) => boolean)) => void;
  setLearnBudget: (v: number) => void;
  setLambda: (v: number) => void;
  setValFrac: (v: number) => void;
  setSpeed: (v: number) => void;
  onStep: () => void;
  onReset: () => void;
  onResplit: () => void;
  onApply: () => void;
}

function LearnView(props: LearnViewProps) {
  const {
    learn,
    running,
    trainN,
    valN,
    trainEval,
    valEval,
    valFrontier,
    learnBudget,
    lambda,
    valFrac,
    speed,
    cv,
    snapBusy,
    onCrossVal,
    onSaveLearned,
    setRunning,
    setLearnBudget,
    setLambda,
    setValFrac,
    setSpeed,
    onStep,
    onReset,
    onResplit,
    onApply,
  } = props;

  const gap = trainEval.coverage - valEval.coverage;
  const overBudget = valEval.wrongPct > learnBudget + 1e-9;

  // Learning-curve chart geometry.
  const LW = 560,
    LH = 190,
    LPX = 40,
    LPY = 14,
    LBottom = LH - 26;
  const hist = learn.history;
  const maxI = Math.max(1, hist.length - 1);
  const lx = (i: number) => LPX + (i / maxI) * (LW - LPX - 14);
  const ly = (cov: number) => LPY + (1 - cov) * (LBottom - LPY);
  const linePath = (pick: (h: (typeof hist)[number]) => number) =>
    hist.map((h, i) => `${i ? "L" : "M"}${lx(i).toFixed(1)},${ly(pick(h)).toFixed(1)}`).join(" ");
  const bestIdx = learn.best ? learn.best.iter - 1 : -1;

  // Val frontier chart geometry (reuse the tradeoff layout).
  const W = 560,
    H = 190,
    PX = 46,
    PY = 14;
  const fx = (c: number) => PX + c * (W - PX - 14);
  const fy = (pr: number) => PY + (1 - pr) * (H - PY - 26);
  const fpath = valFrontier
    .map((pt, i) => `${i ? "L" : "M"}${fx(pt.coverage).toFixed(1)},${fy(pt.precision).toFixed(1)}`)
    .join(" ");

  return (
    <>
      <div className={styles.panel}>
        <div className={styles.panelHead}>
          <span className={styles.kicker}>LEARN — COORDINATE ASCENT ON A HELD-OUT SPLIT</span>
          <div className={styles.learnCtl}>
            <button
              type="button"
              className={styles.runBtn}
              disabled={learn.done}
              onClick={() => setRunning((v) => !v)}
            >
              {running ? "⏸ Pause" : learn.done ? "converged" : "▶ Run"}
            </button>
            <button type="button" className={styles.ghostBtn} disabled={running} onClick={onStep}>
              Step
            </button>
            <button type="button" className={styles.ghostBtn} onClick={onReset}>
              Reset
            </button>
            <button type="button" className={styles.ghostBtn} onClick={onResplit}>
              Re-split
            </button>
            <button
              type="button"
              className={styles.ghostBtn}
              disabled={!learn.best && learn.iter === 0}
              onClick={onCrossVal}
              title="k-fold cross-validate the learned weights — refit τ per fold, report val mean ± std"
            >
              Cross-validate
            </button>
            <button
              type="button"
              className={styles.applyBtn}
              disabled={!learn.best}
              onClick={onApply}
            >
              Apply best → Lab
            </button>
            <button
              type="button"
              className={styles.ghostBtn}
              disabled={(!learn.best && learn.iter === 0) || snapBusy}
              onClick={onSaveLearned}
              title="Save the learned best weights as an operating point (embeds the CV summary if run)"
            >
              💾 Save best
            </button>
          </div>
        </div>

        <p className={styles.chartCaption}>
          Weights start at the <code>explore</code> prior; OCR is pinned to 0 (dead signal) and
          <code> w_ρ</code> may go negative (crowding was protective). Each step probes one weight
          ±δ, keeps the move if it lifts <b>train</b> coverage at the wrong-budget τ (minus an L2
          pull), then refits τ. The <b>val</b> split only watches — the ★ checkpoint is the best
          val coverage within budget.
        </p>

        <div className={styles.knobs}>
          <label className={styles.knob}>
            Wrong budget
            <input
              type="range"
              min={0}
              max={10}
              step={0.5}
              value={learnBudget}
              onChange={(e) => setLearnBudget(Number(e.target.value))}
            />
            <b>{learnBudget}%</b>
          </label>
          <label className={styles.knob}>
            L2 λ (reg)
            <input
              type="range"
              min={0}
              max={0.3}
              step={0.01}
              value={lambda}
              onChange={(e) => setLambda(Number(e.target.value))}
            />
            <b>{lambda.toFixed(2)}</b>
          </label>
          <label className={styles.knob}>
            Val fraction
            <input
              type="range"
              min={0.2}
              max={0.5}
              step={0.05}
              value={valFrac}
              onChange={(e) => setValFrac(Number(e.target.value))}
            />
            <b>{Math.round(valFrac * 100)}%</b>
          </label>
          <label className={styles.knob}>
            Speed
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
            <b>{speed}/s</b>
          </label>
        </div>

        <p className={`${styles.strip} ${styles.logLine}`}>{learn.lastLog}</p>
        {learn.iter > 0 && !learn.trainFeasible && (
          <p className={`${styles.strip} ${styles.bad}`}>
            Train budget {learnBudget}% is infeasible under current weights (min leak{" "}
            {learn.minWrongPct.toFixed(1)}%). Search prefers feasible weight sets; raise the budget
            or accept that zero-leak is unreachable on this split.
          </p>
        )}
        {learn.history.length > 0 && !learn.best && (
          <p className={`${styles.strip} ${styles.bad}`}>
            No val checkpoint held the {learnBudget}% budget — the τ fit on train leaks more on the
            held-out split. This is the overfitting failure mode: loosen the budget, raise λ, or add
            data before trusting these weights.
          </p>
        )}

        {cv && (
          <div className={styles.cvBox}>
            <div className={styles.cvHead}>
              <b>{cv.k}-fold cross-validation</b>
              <span>
                of {learn.best ? "best" : "current"} weights · τ refit per fold ·{" "}
                {cv.feasibleFolds}/{cv.k} folds feasible @ {cv.budget}%
              </span>
            </div>
            <div className={styles.cvStats}>
              <span className={styles.cvStat}>
                val coverage{" "}
                <b>
                  {Math.round(cv.meanCov * 100)}
                  <span className={styles.cvPm}> ± {Math.round(cv.stdCov * 100)}</span>%
                </b>
              </span>
              <span className={styles.cvStat}>
                val wrong-leak{" "}
                <b className={cv.meanWrong > cv.budget + 1e-9 ? styles.bad : undefined}>
                  {cv.meanWrong.toFixed(1)}
                  <span className={styles.cvPm}> ± {cv.stdWrong.toFixed(1)}</span>%
                </b>
              </span>
            </div>
            <div className={styles.cvFolds}>
              {cv.folds.map((f) => (
                <span
                  key={f.fold}
                  className={styles.cvFold}
                  title={`fold ${f.fold + 1}: n=${f.n} · τ=${f.tau.toFixed(2)} · cov ${Math.round(
                    f.valCov * 100,
                  )}% · wrong ${f.valWrong.toFixed(1)}%${f.feasible ? "" : " · infeasible"}`}
                >
                  <span className={styles.cvFoldNum}>{Math.round(f.valCov * 100)}%</span>
                  <span
                    className={styles.cvFoldBar}
                    style={{ height: `${Math.max(2, Math.round(f.valCov * 100))}%` }}
                    data-bad={!f.feasible || f.valWrong > cv.budget + 1e-9 ? "1" : undefined}
                  />
                </span>
              ))}
            </div>
            <p className={styles.chartCaption}>
              Spread across folds is the honest generalization signal — a single split (above) can
              be lucky. Wide std or {"<"} {cv.k} feasible folds means these weights don&apos;t hold
              up; prefer the mean, not the best split. This mean rides along when you Save best.
            </p>
          </div>
        )}
      </div>

      {/* Live weight vector */}
      <div className={styles.chartPanel}>
        <div className={styles.chartHead}>
          <b>Weight vector</b>
          <span>iter {learn.iter} · δ {learn.step.toFixed(2)}</span>
        </div>
        <p className={styles.chartCaption}>
          The learned direction. The highlighted bar is the coordinate just probed. w_o = 0 (pinned)
          and w_g = {LEARN_BASE.wG.toFixed(2)} (fixed prior) are not searched. w_cat (photo scene)
          is searched with a small cap so it can only corroborate.
        </p>
        <div className={styles.wbars}>
          {LEARNABLE.map((coord) => {
            const v = learn.params[coord.key];
            const z = (0 - coord.min) / (coord.max - coord.min);
            const f = (v - coord.min) / (coord.max - coord.min);
            const lo = Math.min(z, f);
            const width = Math.abs(f - z);
            const on = learn.probing === coord.key;
            return (
              <div key={coord.key} className={`${styles.wbar} ${on ? styles.wbarOn : ""}`}>
                <span className={styles.wbarLabel}>{coord.label}</span>
                <div className={styles.wbarTrack}>
                  <span className={styles.wbarZero} style={{ left: `${z * 100}%` }} />
                  <span
                    className={v >= 0 ? styles.wbarPos : styles.wbarNeg}
                    style={{ left: `${lo * 100}%`, width: `${width * 100}%` }}
                  />
                </div>
                <span className={styles.wbarVal}>{v.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Train vs val KPIs */}
      <div className={styles.kpiRow}>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${styles.barGood}`} />
          <span className={`${styles.tileLabel} ${styles.good}`}>VAL · COVERAGE @ BUDGET</span>
          <span className={`${styles.tileNum} ${styles.good}`}>{pct(valEval.labeledN, valN)}</span>
          <span className={styles.tileSub}>
            held-out {valN} cases · precision {pct(valEval.correct, valEval.labeledN)} · this is the
            honest number
          </span>
        </div>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${overBudget ? styles.barBad : styles.barNeutral}`} />
          <span className={`${styles.tileLabel} ${overBudget ? styles.bad : ""}`}>
            VAL · WRONG LEAK
          </span>
          <span className={`${styles.tileNum} ${overBudget ? styles.bad : ""}`}>
            {valEval.wrongPct.toFixed(1)}%
          </span>
          <span className={styles.tileSub}>
            budget {learnBudget}% · {overBudget ? "τ fit on train leaks on val ↑" : "within budget"}
          </span>
        </div>
        <div className={styles.tile}>
          <span className={`${styles.bar} ${styles.barNeutral}`} />
          <span className={styles.tileLabel}>TRAIN − VAL GAP</span>
          <span className={styles.tileNum}>{(gap * 100).toFixed(0)}pt</span>
          <span className={styles.tileSub}>
            train cov {pct(trainEval.labeledN, trainN)} · a wide gap = overfitting the {trainN}-case
            train split
          </span>
        </div>
      </div>
      <div className={styles.summary}>
        <span>
          τ (train-fit) <b>{learn.params.tau.toFixed(2)}</b>
        </span>
        <span>
          best val cov <b>{learn.best ? pct(learn.best.valCov * valN, valN) : "—"}</b>
        </span>
        <span>
          best at iter <b>{learn.best ? learn.best.iter : "—"}</b>
        </span>
        <span>
          split <b>{trainN} / {valN}</b>
        </span>
        <span>
          status <b>{learn.done ? "converged" : running ? "running" : "paused"}</b>
        </span>
      </div>

      <div className={styles.chartsRow}>
        {/* Learning curve */}
        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <b>Learning curve</b>
            <span>coverage @ budget vs iteration</span>
          </div>
          <p className={styles.chartCaption}>
            Train (solid) is optimized; val (dashed) is the generalization check. When train keeps
            rising while val plateaus or dips, you are watching overfitting — the ★ marks the val
            peak.
          </p>
          <svg className={styles.chart} viewBox={`0 0 ${LW} ${LH}`} preserveAspectRatio="none">
            <line x1={LPX} y1={LPY} x2={LPX} y2={LBottom} className={styles.axis} />
            <line x1={LPX} y1={LBottom} x2={LW - 14} y2={LBottom} className={styles.axis} />
            {[0, 0.25, 0.5, 0.75, 1].map((g) => (
              <text key={g} x={LPX - 6} y={ly(g) + 3} className={styles.axLabel} textAnchor="end">
                {Math.round(g * 100)}
              </text>
            ))}
            {bestIdx >= 0 && (
              <line
                x1={lx(bestIdx)}
                y1={LPY}
                x2={lx(bestIdx)}
                y2={LBottom}
                className={styles.bestMark}
              />
            )}
            {hist.length > 1 && (
              <>
                <path d={linePath((h) => h.trainCov)} className={styles.curveTrain} fill="none" />
                <path d={linePath((h) => h.valCov)} className={styles.curveVal} fill="none" />
              </>
            )}
            {hist.length > 0 && (
              <>
                <circle cx={lx(hist.length - 1)} cy={ly(trainEval.coverage)} r={4} className={styles.ptTrain} />
                <circle cx={lx(hist.length - 1)} cy={ly(valEval.coverage)} r={4} className={styles.ptVal} />
              </>
            )}
            <text x={LW / 2} y={LH - 6} className={styles.axLabel} textAnchor="middle">
              iteration →
            </text>
          </svg>
          <div className={styles.legend}>
            <span className={styles.lgTrain}>train coverage</span>
            <span className={styles.lgVal}>val coverage</span>
            <span className={styles.lgBest}>★ best val</span>
          </div>
        </div>

        {/* Val frontier under current weights */}
        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <b>Val frontier</b>
            <span>current weights</span>
          </div>
          <p className={styles.chartCaption}>
            The precision/coverage curve on the held-out split under the current learned weights.
            Better weights push this curve toward the top-right — that is what τ alone can never do.
          </p>
          <svg className={styles.chart} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
            <line x1={PX} y1={PY} x2={PX} y2={H - 26} className={styles.axis} />
            <line x1={PX} y1={H - 26} x2={W - 14} y2={H - 26} className={styles.axis} />
            <path d={fpath} className={styles.curve} fill="none" />
            {valFrontier.map((pt, i) => (
              <circle key={i} cx={fx(pt.coverage)} cy={fy(pt.precision)} r={2.5} className={styles.pt} />
            ))}
            <circle cx={fx(valEval.coverage)} cy={fy(valEval.precision)} r={5.5} className={styles.cur} />
            <text x={W / 2} y={H - 6} className={styles.axLabel} textAnchor="middle">
              coverage →
            </text>
          </svg>
          <div className={styles.legend}>
            <span className={styles.lgCur}>τ = {learn.params.tau.toFixed(2)} (train-fit)</span>
            <span className={styles.lgPt}>swept τ on val</span>
          </div>
        </div>
      </div>
    </>
  );
}
