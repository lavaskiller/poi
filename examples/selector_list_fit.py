"""List-fit selector: photo/OCR evidence over raw distance, top-K friendly.

Uses only signals available at predict time (candidates + OCR). Does not read GT.

Rules (in order):
1) Strong OCR support for any candidate in the provided list (full name / multi-token).
2) Skip generic access nodes (restroom, parking, washroom, stop, fountain, …) when
   a non-generic candidate exists within a distance band.
3) Access-point demote (Gift Shop / Stop / Donation → core name if present).
4) Soft distance: among remaining, prefer closer non-generic.

Designed for candidate_limit 10–20 so rank-6..K GTs can surface.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


GENERIC_RE = re.compile(
    r"^(restroom|toilet|parking|washroom|drinking fountain|fountain|ev charging|"
    r"parking lot|map|courtesy phone|designated smoking area)$",
    re.I,
)
ACCESS_RE = re.compile(
    r"(stop|parking|restroom|toilet|entrance|exit|shuttle|gift shop|donation|drop spot|washroom)",
    re.I,
)
# Bus-stop style labels that share a road/POI token with the real place (Capilano Rd Stop).
STREET_STOP_RE = re.compile(
    r"\b(rd|road|ave|av|blvd|block|st)\b.*\bstop\b|\bstop\b.*\b(rd|road|ave|av|blvd|block|st)\b",
    re.I,
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fuzzy_token_hit(tok: str, ocr_words: set) -> bool:
    """Light typo tolerance for long tokens (suspenston≈suspension). No short fuzzy."""
    if tok in ocr_words:
        return True
    if len(tok) < 6:
        return False
    for w in ocr_words:
        if abs(len(w) - len(tok)) > 2 or not w or w[0] != tok[0]:
            continue
        matches = sum(a == b for a, b in zip(w, tok))
        if matches >= max(5, int(0.75 * max(len(w), len(tok)))):
            return True
    return False


def _ocr_pick(cands: List[Dict[str, Any]], ocr_text: str, min_score: int = 5) -> Optional[str]:
    """OCR→candidate match.

    Conservative boosts (loop-to-70):
    - Distinctive long tokens (len≥7) in OCR strongly support that name
      (e.g. CAPILANO on a plaque → Capilano Suspension Bridge Park, not Dog Bar).
    - Fuzzy only for long tokens (OCR typos like SUSPENSTON).
    - Access / street-stop labels need a higher bar so shared road tokens do not win.
    High confidence threshold when flipping away from rank-1 to avoid regressions.
    """
    ocr = _norm(ocr_text)
    if not ocr or not cands:
        return None
    ocr_words = set(ocr.split())
    scored = []
    for i, c in enumerate(cands):
        name = c.get("name") or ""
        n = _norm(name)
        if not n:
            continue
        score = 0
        if len(n) >= 5 and n in ocr:
            score += 14
        ntoks = [t for t in n.split() if len(t) >= 3]
        if ntoks:
            hits = 0
            for t in ntoks:
                if t in ocr or _fuzzy_token_hit(t, ocr_words):
                    hits += 1
                    score += 2
                    if len(t) >= 7:
                        score += 5  # distinctive place token
                    elif len(t) >= 6:
                        score += 2
            if hits == len(ntoks) and len(ntoks) >= 2:
                score += 6
        # penalize pure access labels even if OCR hits "stop" / road name
        if ACCESS_RE.search(name) and score < 16:
            score -= 4
        if STREET_STOP_RE.search(name):
            score -= 3
        scored.append((score, -i, name))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < min_score:
        return None
    best_name, best_score = scored[0][2], scored[0][0]
    second = scored[1][0] if len(scored) > 1 else 0
    rank1 = cands[0].get("name") or ""
    # Flipping off nearest requires a clear OCR margin (anti-regression).
    if best_name != rank1:
        if best_score < 10:
            return None
        if best_score - second < 3 and best_score < 14:
            return None
    elif best_score - second < 2 and best_score < 10:
        return None
    return best_name


def _is_generic(name: str) -> bool:
    n = _norm(name)
    if GENERIC_RE.match(n or ""):
        return True
    if n in {"restroom", "parking", "washroom", "map"}:
        return True
    return False


def _demote_access(cands: List[Dict[str, Any]]) -> str:
    if not cands:
        return ""
    # drop pure generics from consideration when alternatives exist
    usable = [c for c in cands if not _is_generic(c.get("name") or "")]
    pool = usable if usable else cands

    r1 = pool[0]
    name1 = r1.get("name") or ""
    n1 = _norm(name1)
    d1 = float(r1.get("distance_m") or 0)

    if ACCESS_RE.search(name1) or any(x in n1 for x in ("stop", "gift shop", "donation", "drop spot")):
        for c in pool[1:]:
            name = c.get("name") or ""
            n = _norm(name)
            d = float(c.get("distance_m") or 1e9)
            if not n or ACCESS_RE.search(name) or _is_generic(name):
                continue
            if (n in n1 or n1.startswith(n) or n1 in n) and len(n) >= 4 and d <= d1 + 120:
                return name
        for c in pool[1:]:
            name = c.get("name") or ""
            d = float(c.get("distance_m") or 1e9)
            if ACCESS_RE.search(name) or _is_generic(name):
                continue
            if d <= max(d1 * 2.5, d1 + 50):
                return name
    return (pool[0].get("name") if pool else "") or ""


# Indoor service kiosks that often sit *inside* a larger named place (grocery, etc.).
# Prefer the supermarket/grocery anchor when OCR did not already lock a name.
MICRO_KIOSK_RE = re.compile(
    r"^(vigo|western union|coinstar|blue rhino|libertyx|bitcoin|chargepoint|"
    r"usps collection box)$",
    re.I,
)


def _refine_structure(cands: List[Dict[str, Any]], current: str) -> str:
    """Conservative structure refinements after OCR / access demote (loop-to-70).

    No GT. Only fires on clear structural patterns:
    1) Micro-kiosk rank → nearby supermarket/grocery name in top-15.
    2) Trail/hike pick → Point/Museum when a rare proper stem (≥6 chars) appears
       on ≥4 candidates (e.g. many Yavapai* nodes around a viewpoint).
    """
    cur = (current or "").strip()
    if not cur or not cands:
        return cur

    if MICRO_KIOSK_RE.match(cur):
        for c in cands[:15]:
            name = c.get("name") or ""
            n = _norm(name)
            if "supermarket" in n or re.search(r"\b(grocery|foods market)\b", n):
                return name

    ncur = _norm(cur)
    if "trail" in ncur or "hike" in ncur:
        from collections import Counter

        cnt: Counter = Counter()
        for c in cands:
            for t in _norm(c.get("name") or "").split():
                if len(t) >= 6:
                    cnt[t] += 1
        skip = {
            "trail", "museum", "parking", "geology", "restroom", "portal",
            "visitor", "center", "scenic", "overlook",
        }
        stems = [t for t, n in cnt.items() if n >= 4 and t not in skip]
        if stems:
            stem = max(stems, key=lambda t: (cnt[t], len(t)))
            best_name = None
            best_key = 1e18
            for c in cands:
                name = c.get("name") or ""
                n = _norm(name)
                if stem not in n:
                    continue
                if any(x in n for x in ("stop", "parking", "lot")):
                    continue
                d = float(c.get("distance_m") or 1e9)
                pen = -40 if "point" in n else (-20 if "museum" in n else 0)
                if d + pen < best_key:
                    best_key = d + pen
                    best_name = name
            if best_name:
                return best_name

    return cur


def predict(case: Dict[str, Any]) -> str:
    cands = case.get("nearby_candidates") or []
    if not cands:
        return ""
    ocr_hit = _ocr_pick(cands, case.get("ocr_text") or "")
    if ocr_hit:
        # OCR is high-precision; do not second-guess with structure rules.
        return ocr_hit
    base = _demote_access(cands)
    return _refine_structure(cands, base)
