"""Category-aware MapKit POI selector.

Submission contract: ``predict(case)`` returns a provider-canonical candidate
name, or an empty string when no usable candidate exists.  The harness supplies
``nearby_candidates`` ordered by physical distance; new candidate snapshots also
carry category, MapKit identifier, and coordinates.

The reusable ``resolve(case)`` function exposes the richer single/ambiguous
result for an app or a future picker UI.  The scalar evaluation contract cannot
return a picker list, so ``predict`` selects the best candidate by default and
puts the decision in ``reason``. Set ABSTAIN_ON_AMBIGUOUS to True if ambiguous
cases should be left blank instead.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

ABSTAIN_ON_AMBIGUOUS = False
GENERAL_AMBIGUITY_GAP_M = 38.0
LANDMARK_AMBIGUITY_GAP_M = 36.0
AUXILIARY_MULTIPLIER = 1.45
ACCESS_POINT_MULTIPLIER = 3.0
PICKER_LIMIT = 20

# Effective distance = physical distance * category multiplier * name multiplier.
# These are initial MapKit counterparts of the Kakao policy and should be tuned
# on held-out non-Korea ground truth rather than treated as universal constants.
CATEGORY_MULTIPLIERS = {
    # destination-scale landmarks / attractions
    "landmark": 0.50,
    "nationalmonument": 0.50,
    "castle": 0.50,
    "fortress": 0.50,
    "amusementpark": 0.50,
    "aquarium": 0.50,
    "zoo": 0.50,
    "nationalpark": 0.50,
    "park": 0.55,
    "beach": 0.55,
    # culture / large venues
    "museum": 0.55,
    "theater": 0.55,
    "movietheater": 0.55,
    "musicvenue": 0.55,
    "planetarium": 0.55,
    "library": 0.60,
    "conventioncenter": 0.60,
    "stadium": 0.60,
    # lodging / transport / public facilities
    "hotel": 0.70,
    "campground": 0.70,
    "rvpark": 0.70,
    "airport": 0.75,
    "publictransport": 0.75,
    "police": 0.85,
    "firestation": 0.85,
    "postoffice": 0.85,
    "school": 0.85,
    "university": 0.85,
    # ordinary commercial POIs
    "bank": 1.15,
    "pharmacy": 1.20,
    "store": 1.30,
    "foodmarket": 1.30,
    "restaurant": 1.40,
    "bakery": 1.40,
    "brewery": 1.40,
    "winery": 1.40,
    "distillery": 1.40,
    "cafe": 1.50,
}

LANDMARK_CATEGORIES = {
    "landmark", "nationalmonument", "castle", "fortress", "amusementpark",
    "aquarium", "zoo", "nationalpark", "park", "beach", "museum", "theater",
    "movietheater", "musicvenue", "planetarium", "conventioncenter", "stadium",
}

# Categories that identify infrastructure rather than the likely photo subject.
EXCLUDED_CATEGORIES = {
    "parking", "restroom", "atm", "evcharger", "gasstation", "mailbox",
}

# Locale-aware name fallback for missing/coarse categories. Patterns are kept
# conservative to avoid substring errors such as matching "atm" in a word.
_STRONG_EXCLUSION_PATTERNS = [
    r"\bparking(?: lot| garage| structure| tower)?\b",
    r"\bcar park\b", r"\bparkhaus\b", r"\bestacionamiento\b",
    r"\b(restroom|toilets?|washroom)\b", r"\bbaños?\b", r"\btoilettes?\b",
    r"\b(atm|cash machine)\b", r"\bcajero automático\b",
    r"\b(ev|electric vehicle) charging(?: station)?\b", r"\bcharging station\b",
    r"\b(gas|petrol|lpg) station\b", r"\bstation-service\b", r"\bgasolinera\b",
    r"\b(bus stop|taxi stand|taxi rank)\b", r"\barrêt de bus\b",
    r"\b(parada de autobús|parada de taxi)\b",
    r"\b(mailbox|parcel locker|trash|recycling)\b",
    r"\b(management office|security office|guardhouse)\b",
]

_AUXILIARY_PATTERNS = [
    r"\b(ticket office|ticket booth|box office)\b",
    r"\b(platform|boarding|drop[- ]?off)\b",
    r"\b(visitor cent(?:er|re)|information cent(?:er|re)|tourist information)\b",
    r"\b(taquilla|andén|información turística)\b",
    r"\b(billetterie|quai|office de tourisme)\b",
]

# An entrance can be only a few metres from the camera while the destination's
# canonical POI coordinate is farther inside the property. Penalize access
# points more strongly, but keep them as picker fallbacks.
_ACCESS_POINT_PATTERNS = [
    r"\b(entrance|exit|main gate|rear gate|gate)\b",
    r"\b(entrada|salida|puerta)\b",
    r"\b(entrée|sortie)\b",
]

_STRONG_EXCLUSION_RE = re.compile("|".join(_STRONG_EXCLUSION_PATTERNS), re.IGNORECASE)
_AUXILIARY_RE = re.compile("|".join(_AUXILIARY_PATTERNS), re.IGNORECASE)
_ACCESS_POINT_RE = re.compile("|".join(_ACCESS_POINT_PATTERNS), re.IGNORECASE)


def _category(value: Any) -> str:
    """Normalize Swift raw values and friendly category names to one key."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9]", "", text)
    for prefix in ("mkpointofinterestcategory", "mkpoicategory", "pointofinterestcategory"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _normalized_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)


def _dedupe_key(candidate: Dict[str, Any]) -> tuple:
    place_id = str(candidate.get("provider_place_id") or "").strip()
    if place_id:
        return ("id", place_id)
    name = _normalized_name(candidate.get("name"))
    lat, lon = _number(candidate.get("lat")), _number(candidate.get("lon"))
    if lat is not None and lon is not None:
        return ("fallback", name, round(lat, 5), round(lon, 5), _category(candidate.get("category")))
    return ("legacy", name)


def _candidate_distance(candidate: Dict[str, Any], fallback_index: int) -> float:
    distance = _number(candidate.get("distance_m"))
    if distance is not None:
        return distance
    # Legacy/non-spatial inputs still preserve nearest-first rank. This fallback
    # only maintains that order; it is not presented as a measured distance.
    rank = _number(candidate.get("rank"))
    return (rank if rank is not None and rank >= 1 else fallback_index + 1) * 25.0


def rank_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter, deduplicate, score, and return candidates by effective distance."""
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for index, raw in enumerate(candidates or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        category = _category(raw.get("category"))
        if category in EXCLUDED_CATEGORIES or _STRONG_EXCLUSION_RE.search(name):
            continue

        distance = _candidate_distance(raw, index)
        category_multiplier = CATEGORY_MULTIPLIERS.get(category, 1.0)
        is_access_point = bool(_ACCESS_POINT_RE.search(name))
        auxiliary = is_access_point or bool(_AUXILIARY_RE.search(name))
        auxiliary_multiplier = (
            ACCESS_POINT_MULTIPLIER
            if is_access_point
            else AUXILIARY_MULTIPLIER if auxiliary else 1.0
        )
        effective = distance * category_multiplier * auxiliary_multiplier
        scored = dict(raw)
        scored.update({
            "name": name,
            "normalized_category": category,
            "physical_distance_m": distance,
            "category_multiplier": category_multiplier,
            "auxiliary_multiplier": auxiliary_multiplier,
            "effective_distance_m": effective,
            "is_auxiliary": auxiliary,
            "is_access_point": is_access_point,
            "original_index": index,
        })

        key = _dedupe_key(raw)
        previous = by_key.get(key)
        if previous is None or (
            scored["effective_distance_m"], scored["physical_distance_m"], index
        ) < (
            previous["effective_distance_m"], previous["physical_distance_m"],
            previous["original_index"],
        ):
            by_key[key] = scored

    return sorted(
        by_key.values(),
        key=lambda c: (c["effective_distance_m"], c["physical_distance_m"], c["original_index"]),
    )


def resolve(case: Dict[str, Any]) -> Dict[str, Any]:
    """Return a rich resolution suitable for single-result or picker UIs."""
    ranked = rank_candidates(case.get("nearby_candidates") or [])
    if not ranked:
        return {"decision": "none", "selected": None, "candidates": [], "gap_m": None}
    if len(ranked) == 1:
        return {"decision": "single", "selected": ranked[0],
                "candidates": ranked[:PICKER_LIMIT], "gap_m": None}

    first, second = ranked[0], ranked[1]
    both_landmarks = (
        first["normalized_category"] in LANDMARK_CATEGORIES
        and second["normalized_category"] in LANDMARK_CATEGORIES
    )
    if both_landmarks:
        # Effective-distance ordering can put a physically farther landmark
        # first, so compare their physical separation without a direction.
        gap = abs(second["physical_distance_m"] - first["physical_distance_m"])
        threshold = LANDMARK_AMBIGUITY_GAP_M
    else:
        gap = second["effective_distance_m"] - first["effective_distance_m"]
        threshold = GENERAL_AMBIGUITY_GAP_M
    decision = "ambiguous" if gap < threshold else "single"
    return {
        "decision": decision,
        "selected": first,
        "candidates": ranked[:PICKER_LIMIT],
        "gap_m": gap,
        "ambiguity_threshold_m": threshold,
    }


def predict(case: Dict[str, Any]):
    result = resolve(case)
    selected = result["selected"]
    if selected is None:
        return {"prediction": "", "reason": "no usable MapKit candidate"}
    if result["decision"] == "ambiguous" and ABSTAIN_ON_AMBIGUOUS:
        return {
            "prediction": "",
            "reason": "ambiguous: top candidates within %.1fm" % result["gap_m"],
        }
    return {
        "prediction": selected["name"],
        "reason": "%s; effective_distance=%.1fm; category=%s; gap=%s" % (
            result["decision"],
            selected["effective_distance_m"],
            selected["normalized_category"] or "unknown",
            "n/a" if result["gap_m"] is None else "%.1fm" % result["gap_m"],
        ),
    }
