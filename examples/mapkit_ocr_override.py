"""MapKit baseline v1 — Bloggo weighted rank + unique OCR name override.

Default pick is the category-weighted MapKit selector (``mapkit_weighted``).
An OCR override fires only when exactly one usable candidate has direct,
distinctive name support in on-device OCR text.

Contract: ``predict(case) -> str`` (predicted place name), or ``""`` to abstain.
``case`` never contains ground truth.

Requires sibling modules:
  - examples/mapkit_weighted.py
  - examples/poi_confidence_policy.py
"""
from __future__ import annotations

from typing import Any, Dict, List

from mapkit_weighted import resolve as bloggo_resolve
from poi_confidence_policy import ocr_name_support

RULE_VERSION = "unique-direct-ocr-name-support-v1-exploratory"


def supported_candidates(ranked: List[Dict[str, Any]], ocr_text: str) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for candidate in ranked:
        support = ocr_name_support(candidate.get("name"), ocr_text)
        if support["supported"]:
            evidence.append({"candidate": candidate, **support})
    full = [item for item in evidence if item["strength"] == "full_name"]
    return full if full else evidence


def decide(raw_candidates: List[Dict[str, Any]], ocr_text: str) -> Dict[str, Any]:
    resolution = bloggo_resolve({"nearby_candidates": raw_candidates})
    ranked, base = resolution["candidates"], resolution["selected"]
    if base is None:
        return {
            "prediction": "",
            "decision": "no_usable_bloggo_candidate",
            "resolution": resolution,
            "evidence": [],
            "override": None,
        }
    evidence = supported_candidates(ranked, ocr_text)
    if len(evidence) != 1:
        decision = (
            "ambiguous_ocr_name_support_bloggo_fallback"
            if len(evidence) > 1
            else "no_unique_ocr_name_support_bloggo_fallback"
        )
        return {
            "prediction": str(base.get("name") or "").strip(),
            "decision": decision,
            "resolution": resolution,
            "evidence": evidence,
            "override": None,
        }
    supported = evidence[0]
    candidate = supported["candidate"]
    if (
        candidate.get("provider_place_id") == base.get("provider_place_id")
        and candidate.get("name") == base.get("name")
    ):
        return {
            "prediction": str(base.get("name") or "").strip(),
            "decision": "ocr_confirms_bloggo",
            "resolution": resolution,
            "evidence": evidence,
            "override": None,
        }
    return {
        "prediction": str(candidate.get("name") or "").strip(),
        "decision": "unique_ocr_name_override",
        "resolution": resolution,
        "evidence": evidence,
        "override": candidate,
    }


def predict(case):
    """Submission entrypoint used by the eval harness."""
    candidates = case.get("nearby_candidates") or []
    ocr_text = case.get("ocr_text") or ""
    return decide(candidates, ocr_text)["prediction"]
