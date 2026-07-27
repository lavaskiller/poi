/**
 * Lightweight pure-function checks for gateModel (run via tsc + manual assert,
 * or a future vitest harness). Kept importable so CI can grow into real tests.
 */
import {
  FAITHFUL,
  EXPLORE,
  breakdown,
  crossValidate,
  fitTau,
  hardBlockReason,
  isFaithfulCore,
  labeled,
  policyAgreement,
  scoreCeiling,
  type Params,
} from "./gateModel";
import type { ConfSimCase } from "./api";

function baseCase(over: Partial<ConfSimCase> = {}): ConfSimCase {
  return {
    dataset: "t",
    photo: "p.jpg",
    pred: "Place",
    gt: "Place",
    correct: true,
    correct_exact: true,
    correct_relations: true,
    action: "SHOW_PICKER",
    margin_m: 80,
    decision: "single",
    n_cand: 3,
    cand_dists: [10, 40, 90],
    app_poi_dist_m: 10,
    ocr_strength: "none",
    ocr_supported: false,
    generic_name: false,
    spatial_agreement: true,
    spatial_conflict: false,
    single_candidate: false,
    no_candidates: false,
    vlm_support: false,
    reason_codes: [],
    image: "",
    ...over,
  };
}

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(msg);
}

// spatialStrict alone does not require OCR / large margin
{
  const p: Params = { ...EXPLORE, spatialStrict: true, requireDecisiveEvidence: false };
  const c = baseCase({ margin_m: 20, decision: "ambiguous", ocr_strength: "none" });
  assert(hardBlockReason(c, p) === null, "spatial-only strict should not block ambiguous");
  assert(labeled(c, { ...p, tau: 0 }) === true, "should label at tau 0 without decisive gate");
}

// requireDecisiveEvidence blocks ambiguous / no-OCR-no-margin
{
  const p: Params = { ...FAITHFUL };
  assert(
    hardBlockReason(baseCase({ decision: "ambiguous", margin_m: 20 }), p) === "AMBIGUOUS_MARGIN",
    "decisive: ambiguous",
  );
  assert(
    hardBlockReason(
      baseCase({ decision: "single", margin_m: 30, ocr_strength: "none", vlm_support: true }),
      p,
    ) === "NO_STRONG_OCR",
    "decisive: VLM alone cannot open",
  );
  assert(
    hardBlockReason(
      baseCase({ decision: "single", margin_m: 80, ocr_strength: "none" }),
      p,
    ) === null,
    "decisive: large margin opens",
  );
}

// fitTau feasible flag
{
  const p: Params = { ...FAITHFUL, tau: 1 };
  // Max score so cases remain labeled even at τ = sMax (otherwise strict τ
  // blocks everyone and a 0% budget looks "feasible" by covering nothing).
  const wrongs = [
    baseCase({
      photo: "w1",
      correct: false,
      correct_exact: false,
      correct_relations: false,
      margin_m: 100,
      ocr_strength: "full",
      ocr_supported: true,
      vlm_support: true,
    }),
    baseCase({
      photo: "w2",
      correct: false,
      correct_exact: false,
      correct_relations: false,
      margin_m: 100,
      ocr_strength: "full",
      ocr_supported: true,
      vlm_support: true,
    }),
    baseCase({
      photo: "w3",
      correct: false,
      correct_exact: false,
      correct_relations: false,
      margin_m: 100,
      ocr_strength: "full",
      ocr_supported: true,
      vlm_support: true,
    }),
  ];
  const sMax = scoreCeiling(wrongs, p);
  const infeas = fitTau(wrongs, p, 0, sMax); // 0% budget, but 100% wrong if all labeled
  assert(infeas.feasible === false, "0% budget infeasible when all labeled are wrong");
  assert(infeas.minWrongPct > 0, "minWrongPct > 0");

  const goods = [
    baseCase({
      photo: "g1",
      correct: true,
      margin_m: 100,
      ocr_strength: "full",
      ocr_supported: true,
    }),
    baseCase({
      photo: "g2",
      correct: true,
      margin_m: 100,
      ocr_strength: "full",
      ocr_supported: true,
    }),
  ];
  const feas = fitTau(goods, p, 0, scoreCeiling(goods, p));
  assert(feas.feasible === true, "0% budget feasible when no wrongs");
}

// density sign: negative wRho boosts total
{
  const c = baseCase({ cand_dists: [5, 10, 15, 20] }); // n_R high within R=80
  const pos = breakdown(c, { ...EXPLORE, wRho: 0.5 });
  const neg = breakdown(c, { ...EXPLORE, wRho: -0.5 });
  assert(neg.total > pos.total, "negative wRho should raise score via -density");
}

// isFaithfulCore + policyAgreement
{
  assert(isFaithfulCore(FAITHFUL) === true, "FAITHFUL is core");
  assert(isFaithfulCore(EXPLORE) === false, "EXPLORE is not core");
  const auto = baseCase({
    action: "AUTO_PICK",
    margin_m: 100,
    decision: "single",
    ocr_strength: "none",
    spatial_agreement: true,
    spatial_conflict: false,
  });
  const picker = baseCase({
    photo: "p2.jpg",
    action: "SHOW_PICKER",
    margin_m: 10,
    decision: "ambiguous",
    ocr_strength: "none",
  });
  const agr = policyAgreement([auto, picker], { ...FAITHFUL, tau: 1 });
  assert(agr.agree === 2, "AUTO≡labeled and PICKER≡Near at faithful τ=1");
  assert(agr.disagree.length === 0, "no disagreements");
  // Score-only (no hard): ambiguous high-score path can disagree
  const scoreOnly: Params = {
    ...FAITHFUL,
    spatialStrict: false,
    requireDecisiveEvidence: false,
    tau: 0,
  };
  assert(isFaithfulCore(scoreOnly) === false, "score-only not core");
}

// scene term: capped corroboration, cannot open the faithful gate alone
{
  const c = baseCase({ scene_agreement: 1 });
  // faithful pins wCat = 0, so scene never moves the faithful score.
  assert(breakdown(c, FAITHFUL).scene === 0, "faithful ignores scene (w_cat=0)");
  // explore adds a capped positive term.
  const b = breakdown(c, EXPLORE);
  assert(Math.abs(b.scene - EXPLORE.wCat) < 1e-9, "scene term = w_cat at full agreement");
  const half = breakdown(baseCase({ scene_agreement: 0.5 }), EXPLORE);
  assert(half.scene > 0 && half.scene < EXPLORE.wCat, "scene scales with agreement");
  // cap: agreement is clamped to [0,1], so scene never exceeds w_cat.
  const over = breakdown(baseCase({ scene_agreement: 5 }), { ...EXPLORE, wCat: 0.3 });
  assert(over.scene <= 0.3 + 1e-9, "scene capped at w_cat");
  // scene alone cannot open the faithful hard gate (VLM-alike discipline).
  const lone = baseCase({
    decision: "single",
    margin_m: 30,
    ocr_strength: "none",
    scene_agreement: 1,
  });
  assert(
    hardBlockReason(lone, { ...FAITHFUL, wCat: 0.3 }) === "NO_STRONG_OCR",
    "scene alone cannot open the decisive gate",
  );
}

// faithful core includes w_cat lock
{
  assert(isFaithfulCore({ ...FAITHFUL, wCat: 0.3 }) === false, "raised w_cat breaks faithful core");
}

// crossValidate: partitions all cases, refits τ per fold, reports mean/std
{
  const cases: ConfSimCase[] = [];
  for (let i = 0; i < 40; i++) {
    cases.push(
      baseCase({
        photo: `cv${i}.jpg`,
        correct: i % 3 !== 0, // ~1/3 wrong
        correct_exact: i % 3 !== 0,
        correct_relations: i % 3 !== 0,
        margin_m: 100,
        ocr_strength: "full",
        ocr_supported: true,
      }),
    );
  }
  const cv = crossValidate(cases, { ...EXPLORE, tau: 1 }, 5, 5, 0);
  assert(cv.k === 5 && cv.folds.length === 5, "5 folds produced");
  const held = cv.folds.reduce((s, f) => s + f.n, 0);
  assert(held === cases.length, "every case is held out exactly once across folds");
  assert(cv.meanCov >= 0 && cv.meanCov <= 1, "mean coverage in [0,1]");
  assert(cv.stdCov >= 0 && cv.stdWrong >= 0, "std non-negative");
  assert(cv.feasibleFolds >= 0 && cv.feasibleFolds <= cv.k, "feasibleFolds within [0,k]");
  // Deterministic: same seed → identical partition/metrics.
  const cv2 = crossValidate(cases, { ...EXPLORE, tau: 1 }, 5, 5, 0);
  assert(cv2.meanCov === cv.meanCov && cv2.stdCov === cv.stdCov, "cross-val is deterministic");
}

console.log("gateModel.test.ts: all assertions passed");
