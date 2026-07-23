"""MapKit baseline v2 — OCR + cascade + free-text VLM ensemble (seed reference).

This is the highest published seed baseline (~48% strict / ~68% canonical on the
frozen 166-eligible cohort). The full offline ensemble is built by
``tools/stitch_loop70_ensemble.py`` (list_fit + photo-match cascade + residual
free-text VLM skill picks) and rescored with ``eval_label_relations.v1.jsonl``.

What this file provides:
  * A **self-contained deterministic core** that runs under the UI harness:
    list_fit when it disagrees with access_ocr, else access_ocr, else weighted.
  * Documentation of the offline residual VLM stage that lifts the frozen seed
    result to the published numbers (requires FastVLM caches not shipped here).

Contract: ``predict(case) -> str``, or ``""`` to abstain. No ground truth in case.

Requires sibling modules:
  - examples/selector_list_fit.py
  - examples/selector_access_ocr.py
  - examples/mapkit_weighted.py  (via access_ocr / list_fit)
"""
from __future__ import annotations

from typing import Any, Dict

try:
    import selector_access_ocr as ao
    import selector_list_fit as lf
except ImportError:  # harness may run from a temp dir without siblings
    ao = None  # type: ignore
    lf = None  # type: ignore

try:
    from mapkit_weighted import predict as weighted_predict
except ImportError:
    weighted_predict = None  # type: ignore


DESCRIPTION = (
    "mapkit-baseline v2 = loop70 ensemble: list_fit@K20 + photo-match cascade "
    "+ residual free-text VLM skill, rescored with reviewed label relations."
)


def predict(case: Dict[str, Any]) -> str:
    """Deterministic core of the ensemble (no live VLM).

    Offline residual free-text VLM overrides are baked into the seed run JSON
    (``mapkit-baseline__v2.json``). Re-running this script alone will typically
    land below the published seed accuracy.
    """
    candidates = case.get("nearby_candidates") or []
    if not candidates:
        return ""

    pred_lf = ""
    pred_acc = ""
    if lf is not None:
        try:
            pred_lf = (lf.predict(case) or "").strip()
        except Exception:
            pred_lf = ""
    if ao is not None:
        try:
            pred_acc = (ao.predict(case) or "").strip()
        except Exception:
            pred_acc = ""

    if pred_lf and pred_lf != pred_acc:
        return pred_lf
    if pred_acc:
        return pred_acc
    if pred_lf:
        return pred_lf
    if weighted_predict is not None:
        try:
            return (weighted_predict(case) or "").strip()
        except Exception:
            pass
    return (candidates[0].get("name") or "").strip()
