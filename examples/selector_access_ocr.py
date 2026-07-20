"""PWE-13 selector: demote access-point rank-1 + OCR override when strong.

Designed for the subset where GT is already in the top-5 MapKit candidates.
Baseline nearest scores 63/100 on that pool; this script targets cheap wins
without a vision model:

1. If OCR text strongly matches a candidate name (substring / multi-token),
   pick that candidate.
2. Else if rank-1 looks like an access point (Stop, Gift Shop, Donation, …)
   and a nearby non-access candidate is a name-core or close in distance,
   prefer that candidate (Banff Gondola Stop → Banff Gondola).
3. Else fall back to nearest.

Contract: predict(case) -> str place name, or "".
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


ACCESS_RE = re.compile(
    r"(stop|parking|restroom|toilet|entrance|exit|shuttle|gift shop|donation|drop spot)",
    re.I,
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nearest(cands: List[Dict[str, Any]]) -> str:
    return (cands[0].get("name") if cands else "") or ""


def _ocr_pick(case: Dict[str, Any], min_score: int = 5) -> Optional[str]:
    cands = case.get("nearby_candidates") or []
    if not cands:
        return None
    ocr = _norm(case.get("ocr_text") or "")
    if not ocr:
        return None

    scored = []
    for i, c in enumerate(cands):
        name = c.get("name") or ""
        n = _norm(name)
        if not n:
            continue
        score = 0
        if len(n) >= 5 and n in ocr:
            score += 10
        ntoks = [t for t in n.split() if len(t) >= 3]
        if ntoks:
            hits = sum(1 for t in ntoks if t in ocr)
            score += hits * 2
            if hits == len(ntoks) and len(ntoks) >= 2:
                score += 5
            for t in ntoks:
                if len(t) >= 6 and t in ocr:
                    score += 1
        scored.append((score, -i, name))

    scored.sort(reverse=True)
    if not scored or scored[0][0] < min_score:
        return None

    best_name = scored[0][2]
    rank1 = cands[0].get("name")
    if best_name != rank1:
        second = scored[1][0] if len(scored) > 1 else 0
        # Avoid weak OCR flipping a correct nearest (e.g. short token noise).
        if scored[0][0] - second < 2 and scored[0][0] < 8:
            return None
    return best_name


def _demote_access(cands: List[Dict[str, Any]]) -> str:
    if not cands:
        return ""
    r1 = cands[0]
    name1 = r1.get("name") or ""
    n1 = _norm(name1)
    d1 = float(r1.get("distance_m") or 0)

    is_access = bool(ACCESS_RE.search(name1)) or any(
        x in n1 for x in ("stop", "parking", "gift shop", "donation", "drop spot")
    )
    if not is_access:
        return _nearest(cands)

    # Prefer a later candidate that is the "core" name of the access point.
    for c in cands[1:]:
        name = c.get("name") or ""
        n = _norm(name)
        d = float(c.get("distance_m") or 1e9)
        if not n or ACCESS_RE.search(name):
            continue
        if (n in n1 or n1.startswith(n)) and len(n) >= 4 and d <= d1 + 100:
            return name

    # Else first non-access within a close distance band.
    for c in cands[1:]:
        name = c.get("name") or ""
        d = float(c.get("distance_m") or 1e9)
        if ACCESS_RE.search(name):
            continue
        if d <= max(d1 * 2.0, d1 + 40):
            return name

    return _nearest(cands)


def predict(case: Dict[str, Any]) -> str:
    cands = case.get("nearby_candidates") or []
    if not cands:
        return ""
    ocr_hit = _ocr_pick(case)
    if ocr_hit:
        return ocr_hit
    return _demote_access(cands)
