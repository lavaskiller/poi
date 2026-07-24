"""MapKit baseline v2 — fully live OCR + FastVLM ensemble.

Pipeline (no GT, no cherry-picked residual list, no published prediction caches):

  1. list_fit when it disagrees with access_ocr
  2. else if access_ocr is weak (equals nearest): live FastVLM skill@K
     — accept only high-confidence parses (number / unique full name);
       UNKNOWN or ambiguous → keep access_ocr
  3. structure refine

Contract: ``predict(case) -> str | {prediction, reason}``. Empty prediction
abstains. No ground truth in case.

Reproducibility
---------------
Same code + same model weights + same candidates + same image → same decision.
Write-through JSONL under ``POI_VLM_CACHE`` is pure memoization of live calls
(cache key includes model, prompt, candidates, photo) — not a curated residual
subset. Delete the cache file to force full re-inference.

Harness import policy: repo ``examples/`` is not on PYTHONPATH. Bundle with::

    python3 tools/bundle_submission.py ensemble_v2

Live FastVLM needs MPS + ``poi-data/tools/fastvlm-venv`` (or ``POI_PREDICT_PYTHON``).
``POI_VLM_MODE=off`` → deterministic core only (honest reason suffix).
Default ``live`` **requires** FastVLM (MPS + checkpoint + venv); missing env
fails the whole run instead of silently scoring OCR-only as an ensemble.
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
    "mapkit-baseline v2 = fully live ensemble: list_fit@K20 + FastVLM skill@K5 "
    "on every weak (access≈nearest) case; short non-hedged answers only. "
    "Requires FastVLM unless POI_VLM_MODE=off."
)

# Fail once per process if live VLM was requested but the host cannot run it.
_vlm_env_checked = False

# VLM shortlist size. K=5 matches photo-match stress runs; longer lists dilute
# FastVLM-0.5B and increase false overrides.
VLM_K = 5
VLM_STYLE = "skill"  # allows UNKNOWN → keep core (no forced bad pick)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nearest(cands: List[Dict[str, Any]]) -> str:
    return ((cands[0].get("name") if cands else "") or "").strip()


def _canonical_candidate(name: str, cands: List[Dict[str, Any]]) -> str:
    """Map a free-text / parsed name onto the candidate list spelling."""
    n = _norm(name)
    if not n:
        return ""
    for c in cands:
        cn = (c.get("name") or "").strip()
        if _norm(cn) == n:
            return cn
    return ""


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
        return {
            "prediction": pred_lf,
            "reason": "list_fit",
            "pred_lf": pred_lf,
            "pred_acc": pred_acc,
        }
    if pred_acc:
        return {
            "prediction": pred_acc,
            "reason": "access_ocr",
            "pred_lf": pred_lf,
            "pred_acc": pred_acc,
        }
    if pred_lf:
        return {
            "prediction": pred_lf,
            "reason": "list_fit_only",
            "pred_lf": pred_lf,
            "pred_acc": pred_acc,
        }
    try:
        w = (weighted_predict(case) or "").strip()
    except Exception:
        w = ""
    if w:
        return {
            "prediction": w,
            "reason": "weighted",
            "pred_lf": pred_lf,
            "pred_acc": pred_acc,
        }
    return {
        "prediction": _nearest(cands),
        "reason": "nearest",
        "pred_lf": pred_lf,
        "pred_acc": pred_acc,
    }


def _should_call_vlm(pred_acc: str, nearest: str, cands: List[Dict[str, Any]]) -> bool:
    """Call VLM only when the cheap selector did not leave nearest.

    Deterministic, GT-free, applied uniformly to every case — not a curated
    residual photo list.
    """
    if not cands:
        return False
    if not pred_acc:
        return True
    return _norm(pred_acc) == _norm(nearest)


# Long free-text answers from FastVLM-0.5B often hedge then invent a name
# ("not clearly visible… however closest is X") — net-negative on the cohort.
_HEDGE_RE = re.compile(
    r"not clearly|however|closest match|appears to be|likely|"
    r"based on the context|without a visible|not clearly supported",
    re.I,
)
# Confident skill answers are short (e.g. ``3`` or ``2.``). Cap length so
# rambling free-text cannot override via a lucky embedded number.
_MAX_CONFIDENT_RAW_LEN = 16


def _high_confidence_vlm_name(
    raw: str,
    cands: List[Dict[str, Any]],
    current: str,
) -> str:
    """Accept VLM override only for short, non-hedged, unambiguous picks.

    Applied uniformly to every weak case (access≈nearest) — not a curated
    residual list. Empirically, short number answers net-help; long free-text
    recoveries net-hurt on this model.
    """
    if not raw or not cands:
        return ""
    text = raw.strip()
    if not text or re.search(r"\bUNKNOWN\b", text, flags=re.IGNORECASE):
        return ""
    if _HEDGE_RE.search(text):
        return ""
    if len(text) > _MAX_CONFIDENT_RAW_LEN:
        return ""
    idx = vlm.parse_selection(text, cands)
    if idx is None:
        return ""
    name = (cands[idx].get("name") or "").strip()
    if name and _norm(name) != _norm(current):
        return name
    return ""


def _ensure_vlm_environment() -> None:
    """Fail the run up front when live FastVLM was requested but cannot run.

    Without this, missing venv/checkpoint silently degrades to OCR-only while
    still saving a ``mapkit-baseline`` accuracy as if the ensemble ran.
    """
    global _vlm_env_checked
    if _vlm_env_checked:
        return
    _vlm_env_checked = True
    vlm.require_live_ready()


def predict(case: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
    """Fully live ensemble: core + uniform weak-case FastVLM.

    Returns ``{prediction, reason}`` for harness visibility.
    Raises ``RuntimeError`` when ``POI_VLM_MODE`` is live (default) but FastVLM
    is not provisioned, or when a required VLM call cannot run (no image, etc.).
    """
    _ensure_vlm_environment()

    candidates: List[Dict[str, Any]] = list(case.get("nearby_candidates") or [])
    if not candidates:
        return {"prediction": "", "reason": "no_candidates"}

    core = _core_pick(case, candidates)
    pred = core["prediction"]
    reason = core["reason"]
    pred_acc = core["pred_acc"]
    nearest = _nearest(candidates)

    # Strong OCR / list_fit disagreement: do not second-guess with VLM.
    if reason == "list_fit":
        return {"prediction": pred, "reason": reason}

    if _should_call_vlm(pred_acc, nearest, candidates):
        vlm_cands = candidates[:VLM_K]
        out = vlm.infer(case, vlm_cands, style=VLM_STYLE)
        note = out.get("reason") or ""
        # Explicit offline mode: keep core and tag reason (allowed degradation).
        if note == "vlm_mode_off":
            reason = f"{reason}+{note}"
        elif note in (
            "vlm_unavailable",
            "vlm_image_missing",
            "vlm_cache_missing",
            "vlm_error",
        ):
            detail = out.get("error") or note
            photo = (case.get("photo") or "").strip()
            raise RuntimeError(
                f"mapkit-baseline v2 FastVLM call failed ({note}"
                + (f" on {photo}" if photo else "")
                + f"): {detail}. "
                "Fix FastVLM provisioning or set POI_VLM_MODE=off for "
                "deterministic core only (not a live ensemble score)."
            )
        else:
            raw = out.get("raw_output") or ""
            # Prefer parse on shortlist; fall back to full list for name match only.
            name = _high_confidence_vlm_name(raw, vlm_cands, pred)
            if not name and raw:
                name = _high_confidence_vlm_name(raw, candidates, pred)
            name = _canonical_candidate(name, candidates) if name else ""
            if name and _norm(name) != _norm(pred):
                pred, reason = name, "vlm_skill"
            elif note == "vlm_cache_hit" and out.get("ok"):
                # Cache hit that agrees with core or failed parse — keep core.
                reason = reason
            # else: UNKNOWN / ambiguous → keep access_ocr (no forced override)

    if pred:
        try:
            refined = lf._refine_structure(candidates, pred)
        except Exception:
            refined = pred
        if refined and refined != pred:
            pred, reason = refined, "structure_refine"

    return {"prediction": pred, "reason": reason}
