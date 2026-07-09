#!/usr/bin/env python3
"""
Offline baseline evaluation of the current POI-selection algorithm (KS2-32).

Models the ranking behavior of `kakaoScorePlacesForMapTap` / `resolveMapTapPOI`:
    effective_distance = raw_distance(m) * category_multiplier
    predicted place = argmin(effective_distance)   # rank-1 auto-pick

IMPORTANT (honesty caveats):
  * The real app pulls candidate POIs live from Kakao Local (Korea) or MapKit
    (elsewhere). Offline we cannot query those, so we use the DISTINCT GT places
    in eval_set.csv as the candidate universe. This isolates the *ranking* logic;
    it does NOT reproduce candidate-retrieval recall.
  * GT here is synthetic (labeler=synthetic-claude). Numbers are a pipeline
    smoke-test, not a real user-selection match rate.
"""
import csv, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "eval_set.csv")

# Category multipliers — mirrors PlaceSearchViewModel.categoryPriorityMultiplier.
# App uses Kakao codes; we map our simplified eval categories onto them.
#   attraction -> AT4 (0.50), park ~ CT1/green (0.60), urban/default -> 1.00
CAT_MULT = {"attraction": 0.50, "park": 0.60, "urban": 1.00}

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def parse_coord(s):
    lat, lon = s.split(";")
    return float(lat), float(lon)

rows = []
with open(CSV, newline="") as f:
    for r in csv.DictReader(f):
        rows.append(r)

# Candidate universe = distinct GT places.
candidates = {}
for r in rows:
    candidates[r["gt_place_name"]] = (parse_coord(r["gt_place_coord"]), r["category"])
cand_list = [(name, coord, cat) for name, (coord, cat) in candidates.items()]

print(f"Eval set: {len(rows)} photos | candidate POIs: {len(cand_list)}")
print("-" * 78)

def predict(cap_lat, cap_lon, use_category):
    best, best_eff, best_raw = None, float("inf"), None
    for name, (clat, clon), cat in cand_list:
        raw = haversine_m(cap_lat, cap_lon, clat, clon)
        eff = raw * (CAT_MULT.get(cat, 1.0) if use_category else 1.0)
        if eff < best_eff:
            best, best_eff, best_raw = name, eff, raw
    return best, best_raw

def run(use_category):
    hits, fails = 0, []
    for r in rows:
        cap = (float(r["capture_lat"]), float(r["capture_lon"]))
        pred, raw = predict(cap[0], cap[1], use_category)
        gt = r["gt_place_name"]
        if pred == gt:
            hits += 1
        else:
            fails.append((r["photo"], gt, pred, raw))
    return hits, fails

for label, use_cat in [("distance-only", False), ("distance x category-mult", True)]:
    hits, fails = run(use_cat)
    print(f"\n[{label}]  rank-1 match rate = {hits}/{len(rows)} = {hits/len(rows)*100:.1f}%")
    if fails:
        print(f"  failures ({len(fails)}):")
        for photo, gt, pred, raw in fails:
            print(f"    {photo}: GT='{gt}'  ->  predicted='{pred}'  (nearest {raw:.0f} m)")

# Per-cluster (by GT) breakdown for the category-aware run.
print("\n" + "-" * 78)
print("Per-GT-place breakdown (distance x category-mult):")
by_place = {}
for r in rows:
    cap = (float(r["capture_lat"]), float(r["capture_lon"]))
    pred, _ = predict(cap[0], cap[1], True)
    gt = r["gt_place_name"]
    d = by_place.setdefault(gt, [0, 0])
    d[1] += 1
    if pred == gt:
        d[0] += 1
for gt, (ok, tot) in by_place.items():
    print(f"  {ok}/{tot}  {gt}")
