"""MapKit baseline v2 — live OCR + cascade + free-text VLM ensemble.

Published seed metrics (~48% strict / ~68% canonical on the frozen cohort)
come from the loop70 ensemble:

  list_fit@K20  when it disagrees with access_ocr
  else photo–place FastVLM cascade (place_match) on weak / nearest-tied cases
  else access_ocr / weighted
  + structure refine
  + residual free-text VLM skill name recovery

Contract: ``predict(case) -> str | {prediction, reason}``. Empty prediction
abstains. No ground truth in case.

Harness import policy
---------------------
The eval harness does **not** put ``examples/`` on PYTHONPATH. Use::

    python3 tools/bundle_submission.py ensemble_v2

for a self-contained submission, or the curated seed ``script_text``.

Live FastVLM requirements
-------------------------
* Apple Silicon MPS + ``poi-data/tools/fastvlm-venv`` (torch) as the predict
  interpreter (harness auto-selects when present; or set ``POI_PREDICT_PYTHON``).
* Checkpoint under ``poi-data/tools/ml-fastvlm/checkpoints/…``.
* Case must include ``photo`` and preferably ``dataset`` (injected by harness)
  so the image path can be resolved.

``POI_VLM_MODE=off`` forces the deterministic core only (honest reason
``vlm_mode_off`` / core reason). Missing model/image does **not** silently
claim published accuracy — reason is ``vlm_unavailable`` / ``vlm_image_missing``.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Union

try:
    import mapkit_vlm_live as vlm
    import selector_access_ocr as ao
    import selector_list_fit as lf
    from mapkit_weighted import predict as weighted_predict
except ImportError as e:  # pragma: no cover - missing siblings / not bundled
    raise ImportError(
        "mapkit_baseline_v2 needs sibling modules (mapkit_vlm_live, "
        "selector_list_fit, selector_access_ocr, mapkit_weighted). The harness "
        "blocks repo-local outside imports — use "
        "`python3 tools/bundle_submission.py ensemble_v2` for a self-contained "
        f"submission. Underlying error: {e}"
    ) from e


DESCRIPTION = (
    "mapkit-baseline v2 = live loop70 ensemble: list_fit@K20 + photo-match "
    "FastVLM cascade + residual free-text VLM skill "
    "(rescored with reviewed label relations)."
)

# Cascade uses a shorter shortlist; residual free-text sees up to K=20.
CASCADE_K = 10
RESIDUAL_K = 20


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nearest(cands: List[Dict[str, Any]]) -> str:
    return ((cands[0].get("name") if cands else "") or "").strip()


def _core_pick(case: Dict[str, Any], cands: List[Dict[str, Any]]) -> Dict[str, str]:
    """Deterministic OCR / access / weighted core (no VLM)."""
    pred_lf = ""
    pred_acc = ""
    try:
        pred_lf = (lf.predict(case) or "").strip()
    except Exception:
        pred_lf = ""
    try:
        pred_acc = (ao.predict(case) or "").strip()
    except Exception:
        pred_acc = ""

    if pred_lf and pred_lf != pred_acc:
        return {"prediction": pred_lf, "reason": "list_fit", "pred_lf": pred_lf, "pred_acc": pred_acc}
    if pred_acc:
        return {"prediction": pred_acc, "reason": "access_ocr", "pred_lf": pred_lf, "pred_acc": pred_acc}
    if pred_lf:
        return {"prediction": pred_lf, "reason": "list_fit_only", "pred_lf": pred_lf, "pred_acc": pred_acc}
    try:
        w = (weighted_predict(case) or "").strip()
    except Exception:
        w = ""
    if w:
        return {"prediction": w, "reason": "weighted", "pred_lf": pred_lf, "pred_acc": pred_acc}
    return {
        "prediction": _nearest(cands),
        "reason": "nearest",
        "pred_lf": pred_lf,
        "pred_acc": pred_acc,
    }


def _should_cascade(pred_acc: str, nearest: str, cands: List[Dict[str, Any]]) -> bool:
    """Mirror photo-match miss_only: VLM when cheap selector stays on nearest."""
    if not cands:
        return False
    if not pred_acc:
        return True
    return _norm(pred_acc) == _norm(nearest)


def _should_residual(pred: str, nearest: str, reason: str) -> bool:
    """Residual free-text when still weak after cascade / structure refine."""
    if reason == "list_fit":
        # Strong OCR / structure list_fit already overrode access — skip residual.
        return False
    if not pred:
        return True
    return _norm(pred) == _norm(nearest)


def predict(case: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
    """Live ensemble: deterministic core + FastVLM cascade + free-text residual.

    Returns a dict with ``prediction`` and ``reason`` so the harness / UI can
    show whether VLM ran. (String-only return is still accepted by the runner.)
    """
    candidates: List[Dict[str, Any]] = list(case.get("nearby_candidates") or [])
    if not candidates:
        return {"prediction": "", "reason": "no_candidates"}

    core = _core_pick(case, candidates)
    pred = core["prediction"]
    reason = core["reason"]
    pred_acc = core["pred_acc"]
    nearest = _nearest(candidates)
    vlm_notes: List[str] = []

    # --- Stage A: list_fit disagreement wins without VLM ---
    if reason == "list_fit":
        return {"prediction": pred, "reason": reason}

    # --- Stage B: place_match cascade on weak cases ---
    if _should_cascade(pred_acc, nearest, candidates):
        cas_cands = candidates[:CASCADE_K]
        out = vlm.infer(case, cas_cands, style="place_match")
        if out.get("ok") and (out.get("prediction") or "").strip():
            cas_pred = (out["prediction"] or "").strip()
            if cas_pred and _norm(cas_pred) != _norm(pred_acc or pred):
                pred, reason = cas_pred, "vlm_cascade"
            elif cas_pred:
                pred, reason = cas_pred, "vlm_cascade_agree"
            vlm_notes.append(out.get("reason") or "vlm_cascade")
        else:
            note = out.get("reason") or "vlm_cascade_failed"
            vlm_notes.append(note)
            # Honest degrade: keep core, surface missing VLM in reason.
            if note in (
                "vlm_unavailable",
                "vlm_image_missing",
                "vlm_cache_missing",
                "vlm_mode_off",
            ):
                reason = f"{reason}+{note}"

    # --- Stage C: structure refine (same as stitch_loop70) ---
    if reason != "list_fit" and pred:
        try:
            refined = lf._refine_structure(candidates, pred)
        except Exception:
            refined = pred
        if refined and refined != pred:
            pred, reason = refined, "structure_refine"

    # --- Stage D: residual free-text skill recovery ---
    if _should_residual(pred, nearest, reason):
        res_cands = candidates[:RESIDUAL_K]
        out = vlm.infer(case, res_cands, style="skill")
        raw = out.get("raw_output") or ""
        name = ""
        if out.get("ok") or raw:
            name = (out.get("prediction") or "").strip()
            if not name and raw:
                name = vlm.recover_name(raw, candidates)
        if name and _norm(name) != _norm(pred) and len(_norm(name)) >= 5:
            # Only accept if name maps to a real candidate (canonical spelling).
            for c in candidates:
                if _norm(c.get("name") or "") == _norm(name):
                    name = (c.get("name") or "").strip()
                    break
            else:
                # recover_name already returns candidate names when successful
                if _norm(name) not in {_norm(c.get("name") or "") for c in candidates}:
                    name = ""
            if name:
                pred, reason = name, "vlm_freetext_recover"
                vlm_notes.append(out.get("reason") or "vlm_residual")
        else:
            note = out.get("reason") or "vlm_residual_noop"
            vlm_notes.append(note)
            if note in (
                "vlm_unavailable",
                "vlm_image_missing",
                "vlm_cache_missing",
                "vlm_mode_off",
            ) and "+" not in reason:
                reason = f"{reason}+{note}"

    return {"prediction": pred, "reason": reason}
