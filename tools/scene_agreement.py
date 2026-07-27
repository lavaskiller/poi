#!/usr/bin/env python3
"""Photo scene ↔ MapKit pick agreement (a-priori gate signal).

``scene_labels`` come from on-device ``VNClassifyImageRequest``
(``tools/swift/scene_classify.swift`` → ``scene_labels.tsv``).

Agreement is continuous in [0, 1]:
  0  — no usable scene or no overlap with the pick
  1  — strong scene label maps to the pick's category (or name cue)

Never uses GT. Used only as a capped additive term (``w_cat``) in the
confidence gate — mirrors VLM corroboration discipline.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Vision identifier fragments (casefold substring) → MapKit-normalized categories
# and/or name tokens that count as agreement.
# Keep conservative: scene type is not identity evidence.
_SCENE_MAP: List[Tuple[str, Set[str], Set[str]]] = [
    # (scene_substr, categories, name_tokens)
    ("restaurant", {"restaurant", "cafe", "bakery", "brewery", "winery", "distillery"},
     {"restaurant", "diner", "bistro", "grill", "kitchen"}),
    ("cafe", {"cafe", "bakery", "restaurant"}, {"cafe", "coffee", "espresso"}),
    ("coffee", {"cafe", "bakery"}, {"coffee", "cafe", "espresso"}),
    ("bakery", {"bakery", "cafe"}, {"bakery", "pastry", "bread"}),
    ("storefront", {"store", "restaurant", "cafe", "foodmarket", "pharmacy", "bank"},
     {"shop", "store", "market"}),
    ("store", {"store", "foodmarket", "pharmacy"}, {"shop", "store", "market"}),
    ("supermarket", {"foodmarket", "store"}, {"supermarket", "grocery", "market"}),
    ("grocery", {"foodmarket", "store"}, {"grocery", "market", "supermarket"}),
    ("food", {"restaurant", "cafe", "bakery", "foodmarket"}, {"food", "restaurant", "cafe"}),
    ("bar", {"restaurant", "brewery"}, {"bar", "pub", "tavern"}),
    ("hotel", {"hotel"}, {"hotel", "inn", "lodge", "resort"}),
    ("museum", {"museum", "landmark"}, {"museum", "gallery"}),
    ("park", {"park", "nationalpark", "beach"}, {"park", "garden", "trail"}),
    ("garden", {"park", "nationalpark"}, {"garden", "park"}),
    ("beach", {"beach", "park"}, {"beach", "shore", "coast"}),
    ("mountain", {"nationalpark", "park", "landmark"}, {"mountain", "peak", "trail", "summit"}),
    ("trail", {"nationalpark", "park"}, {"trail", "hike", "path"}),
    ("forest", {"nationalpark", "park"}, {"forest", "woods", "trail"}),
    ("outdoor", {"park", "nationalpark", "beach", "landmark"}, set()),
    ("nature", {"park", "nationalpark", "beach"}, set()),
    ("landmark", {"landmark", "nationalmonument", "castle", "fortress", "museum"},
     {"monument", "tower", "bridge", "cathedral", "temple"}),
    ("building", {"landmark", "hotel", "museum", "conventioncenter"}, set()),
    ("church", {"landmark", "museum"}, {"church", "cathedral", "chapel", "temple"}),
    ("stadium", {"stadium"}, {"stadium", "arena"}),
    ("airport", {"airport"}, {"airport", "terminal"}),
    ("parking", {"parking"}, {"parking"}),  # usually a conflict signal for destination picks
    ("sign", set(), set()),  # weak identity — ignored for category boost
    ("text", set(), set()),
]


def parse_scene_labels(raw: str) -> List[Tuple[str, float]]:
    """Parse ``id:conf|id:conf`` from scene_labels.tsv."""
    out: List[Tuple[str, float]] = []
    for part in (raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            out.append((part.casefold(), 1.0))
            continue
        ident, _, conf_s = part.rpartition(":")
        try:
            conf = float(conf_s)
        except ValueError:
            conf = 0.0
        ident = ident.strip()
        if ident:
            out.append((ident.casefold(), max(0.0, min(1.0, conf))))
    return out


def _tokens(name: str) -> Set[str]:
    return set(re.findall(r"[^\W_]+", (name or "").casefold(), flags=re.UNICODE))


def scene_agreement(
    scene_labels: Sequence[Tuple[str, float]] | str,
    pick_category: str = "",
    pick_name: str = "",
    *,
    min_conf: float = 0.12,
) -> float:
    """Return [0, 1] agreement between photo scene and the selected pick.

    Uses the best-matching scene label above ``min_conf``. Matching is by
    MapKit ``normalized_category`` and/or meaningful name tokens. Empty scene
    or empty pick → 0.
    """
    if isinstance(scene_labels, str):
        pairs = parse_scene_labels(scene_labels)
    else:
        pairs = [(str(i).casefold(), float(c)) for i, c in scene_labels]
    if not pairs:
        return 0.0
    cat = (pick_category or "").casefold().strip()
    name_toks = _tokens(pick_name)
    if not cat and not name_toks:
        return 0.0

    best = 0.0
    for ident, conf in pairs:
        if conf < min_conf:
            continue
        for scene_key, categories, name_keys in _SCENE_MAP:
            if scene_key not in ident and ident not in scene_key:
                # allow multiword identifiers containing the key
                if scene_key not in ident.replace(" ", ""):
                    continue
            score = 0.0
            if cat and cat in categories:
                score = conf
            elif name_keys and (name_toks & name_keys):
                # name cue is weaker than category match
                score = conf * 0.75
            if score > best:
                best = score
    return max(0.0, min(1.0, best))


def scene_conflict(
    scene_labels: Sequence[Tuple[str, float]] | str,
    pick_category: str = "",
    pick_name: str = "",
    *,
    min_conf: float = 0.25,
) -> bool:
    """True when a confident scene maps to a *different* category family than the pick.

    Used as a soft diagnostic (not a hard pre-filter by default). Parking /
    restroom scenes against a destination category are a common conflict.
    """
    agree = scene_agreement(scene_labels, pick_category, pick_name, min_conf=0.08)
    if agree >= 0.35:
        return False
    if isinstance(scene_labels, str):
        pairs = parse_scene_labels(scene_labels)
    else:
        pairs = list(scene_labels)
    if not pairs or pairs[0][1] < min_conf:
        return False
    # Strong top-1 scene with near-zero agreement → conflict signal
    return agree < 0.12 and pairs[0][1] >= min_conf


def read_scene_tsv(path: str) -> Dict[str, Dict[str, Any]]:
    """Read scene_labels.tsv → photo → {top1, top1_conf, labels, pairs}."""
    import csv
    import os
    out: Dict[str, Dict[str, Any]] = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            labels = (row.get("scene_labels") or "").strip()
            top1 = (row.get("scene_top1") or "").strip()
            try:
                top1_conf = float(row.get("scene_top1_conf") or 0)
            except ValueError:
                top1_conf = 0.0
            pairs = parse_scene_labels(labels)
            if not pairs and top1:
                pairs = [(top1.casefold(), top1_conf or 0.0)]
            out[photo] = {
                "scene_top1": top1,
                "scene_top1_conf": top1_conf,
                "scene_labels": labels,
                "pairs": pairs,
            }
    return out
