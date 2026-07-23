"""Baseline submission: predict the nearest MapKit candidate.

This is the trivial "just pick the closest point of interest" algorithm. Its
identification accuracy is the natural floor every real algorithm should beat,
and it makes the identification-accuracy chart show a real bar
before any custom algorithm is submitted.

Contract: define predict(case) -> str (the predicted place name), or "" to
abstain. `case` only exposes the input signals selected in the UI; it never
contains the ground-truth answer.
"""


def predict(case):
    # nearby_candidates arrives pre-sorted by rank (nearest first).
    candidates = case.get("nearby_candidates") or []
    if not candidates:
        return ""
    return candidates[0].get("name") or ""
