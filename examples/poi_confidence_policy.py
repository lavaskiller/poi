"""Conservative action-tier policy for a MapKit POI suggestion.

This module turns the category-aware weighted resolver into an explicit product
action.  It intentionally returns an *action tier*, not a model probability:

* ``AUTO_PICK`` — preselect one candidate, while still offering change/undo.
* ``SHOW_PICKER`` — show the ranked candidates (initially Top-5).
* ``NONE`` — do not guess; offer search, map selection, or place-none.

The thresholds are experimental calibration knobs.  They are deliberately
conservative: a VLM result can corroborate a spatial/OCR result but never makes
an auto-pick by itself, and a one-candidate snapshot is not auto-picked merely
because it has one candidate.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

# The examples directory is intentionally not a Python package. Make this
# sibling import work both when the file is submitted to the harness and when
# the policy is loaded by the simulator through importlib.
_EXAMPLES_DIR = str(Path(__file__).resolve().parent)
if _EXAMPLES_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLES_DIR)
from mapkit_weighted import PICKER_LIMIT, rank_candidates, resolve

AUTO_PICK = "AUTO_PICK"
SHOW_PICKER = "SHOW_PICKER"
NONE = "NONE"

# These are policy thresholds, not estimated probabilities. Recalibrate on a
# held-out cohort before changing production behavior.
AUTO_MARGIN_M = 60.0
PICKER_INITIAL_LIMIT = 5
MIN_OCR_TOKEN_LENGTH = 3

# A category/name token such as "cafe" or "park" does not identify one POI.
GENERIC_NAME_TOKENS = {
    "and", "bar", "cafe", "café", "center", "centre", "coffee", "hotel",
    "market", "museum", "park", "restaurant", "shop", "store", "the",
}


def _normalise(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)


def _tokens(value: Any) -> Set[str]:
    return set(re.findall(r"[^\W_]+", _normalise(value), flags=re.UNICODE))


def _meaningful_name_tokens(name: Any) -> Set[str]:
    return {
        token for token in _tokens(name)
        if len(token) >= MIN_OCR_TOKEN_LENGTH and token not in GENERIC_NAME_TOKENS
    }


def ocr_name_support(name: Any, ocr_text: Any) -> Dict[str, Any]:
    """Return conservative OCR support for a candidate name.

    A full normalised-name substring is strong support. Otherwise all meaningful
    name tokens must be visible in OCR; a single generic category word is not
    sufficient. This avoids treating e.g. ``Cafe`` in OCR as proof of a
    particular cafe.
    """
    normal_name = _normalise(name)
    normal_ocr = _normalise(ocr_text)
    if not normal_name or not normal_ocr:
        return {"supported": False, "strength": "none", "matched_tokens": []}
    meaningful = _meaningful_name_tokens(name)
    # A full match of only a generic type label ("Cafe", "Park", ...) does
    # not identify a place. It cannot be treated as OCR corroboration.
    if normal_name in normal_ocr and meaningful:
        return {"supported": True, "strength": "full_name", "matched_tokens": sorted(_tokens(normal_name))}
    name_tokens = meaningful
    matched = sorted(name_tokens & _tokens(ocr_text))
    if name_tokens and len(matched) == len(name_tokens):
        return {"supported": True, "strength": "all_meaningful_tokens", "matched_tokens": matched}
    return {"supported": False, "strength": "none", "matched_tokens": matched}


def _same_name(a: Any, b: Any) -> bool:
    return bool(_normalise(a) and _normalise(a) == _normalise(b))


def _physical_nearest(ranked: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    items = list(ranked)
    if not items:
        return None
    return min(items, key=lambda item: (
        item.get("physical_distance_m") is None,
        item.get("physical_distance_m") if item.get("physical_distance_m") is not None else float("inf"),
        item.get("original_index", 0),
    ))


def _valid_direct_tap(case: Dict[str, Any], ranked: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resolve an explicitly tapped provider ID, if it is in the usable list."""
    tapped_id = str(case.get("direct_tap_provider_id") or "").strip()
    if not tapped_id:
        return None
    for candidate in ranked:
        if str(candidate.get("provider_place_id") or "").strip() == tapped_id:
            return candidate
    return None


def decide(case: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a product action plus structured reason codes.

    Optional inputs used for corroboration:
    ``ocr_text``, ``vlm_prediction``, ``vlm_decision``, and
    ``direct_tap_provider_id``.  The VLM decision must be ``vlm_override`` or
    ``vlm_agrees_nearest`` to count as an actual model selection; nearest
    fallbacks never count as visual evidence.
    """
    resolution = resolve(case)
    ranked = resolution["candidates"]
    selected = resolution["selected"]
    if not selected:
        return {
            "action": NONE, "selected": None, "candidates": [],
            "reason_codes": ["NO_USABLE_CANDIDATES"], "resolution": resolution,
        }

    tapped = _valid_direct_tap(case, ranked)
    if tapped:
        return {
            "action": AUTO_PICK, "selected": tapped, "candidates": ranked[:PICKER_LIMIT],
            "reason_codes": ["DIRECT_TAP_PROVIDER_ID"], "resolution": resolution,
        }

    nearest = _physical_nearest(ranked)
    spatial_agreement = bool(nearest and _same_name(selected.get("name"), nearest.get("name")))
    ocr = ocr_name_support(selected.get("name"), case.get("ocr_text"))
    vlm_prediction = case.get("vlm_prediction")
    vlm_decision = str(case.get("vlm_decision") or "").strip()
    vlm_support = (
        _same_name(selected.get("name"), vlm_prediction)
        and vlm_decision in {"vlm_override", "vlm_agrees_nearest"}
    )
    margin = resolution.get("gap_m")
    large_margin = isinstance(margin, (int, float)) and margin >= AUTO_MARGIN_M

    # A one-result candidate list lacks a margin. It needs text evidence, even
    # if a VLM also emits the same fallback candidate.
    if len(ranked) == 1:
        if ocr["supported"]:
            return {
                "action": AUTO_PICK, "selected": selected, "candidates": ranked[:PICKER_LIMIT],
                "reason_codes": ["SINGLE_CANDIDATE", "OCR_NAME_SUPPORT", ocr["strength"]],
                "resolution": resolution,
            }
        return {
            "action": SHOW_PICKER, "selected": selected, "candidates": ranked[:PICKER_LIMIT],
            "reason_codes": ["SINGLE_CANDIDATE_UNCORROBORATED"], "resolution": resolution,
        }

    # Auto requires a decisive weighted resolution, agreement with the physical
    # nearest candidate, and either OCR evidence or a large calibrated margin.
    # VLM may be recorded as an extra support code, but cannot satisfy this gate.
    if resolution["decision"] == "single" and spatial_agreement and (ocr["supported"] or large_margin):
        reasons = ["WEIGHTED_NEAREST_AGREE"]
        if large_margin:
            reasons.append("LARGE_MARGIN")
        if ocr["supported"]:
            reasons.extend(["OCR_NAME_SUPPORT", ocr["strength"]])
        if vlm_support:
            reasons.append("VLM_CORROBORATES")
        return {
            "action": AUTO_PICK, "selected": selected, "candidates": ranked[:PICKER_LIMIT],
            "reason_codes": reasons, "resolution": resolution,
        }

    reasons = []
    if resolution["decision"] == "ambiguous":
        reasons.append("AMBIGUOUS_MARGIN")
    if not spatial_agreement:
        reasons.append("WEIGHTED_NEAREST_CONFLICT")
    if vlm_prediction and not vlm_support:
        reasons.append("VLM_CONFLICT_OR_FALLBACK")
    if not ocr["supported"]:
        reasons.append("NO_STRONG_OCR_SUPPORT")
    if not reasons:
        reasons.append("INSUFFICIENT_AUTO_EVIDENCE")
    return {
        "action": SHOW_PICKER, "selected": selected, "candidates": ranked[:PICKER_LIMIT],
        "reason_codes": reasons, "resolution": resolution,
    }
