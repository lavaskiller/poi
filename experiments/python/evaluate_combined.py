#!/usr/bin/env python3
"""Merge the Vancouver MapKit-harness results into eval_set_combined.csv, then compute
baseline metrics over BOTH datasets. Rows whose reliability could not be secured are left
BLANK and are EXCLUDED from the metric denominators (they are reported as 'held for meeting').

eval_class (derived):
  venue   -> has a securable GT venue keyword; retrieval rank is evaluated
  non_poi -> must-refuse row (transit / in-flight / street / blurry / private lodging)
  held    -> unconfirmed venue, BLANK, excluded from metrics (fill in the meeting)
"""
import csv, os
HERE=os.path.dirname(os.path.abspath(__file__))
COMB=os.path.join(HERE,"eval_set_combined.csv")
VAN=os.path.join(HERE,"vancouver_nearby_results.tsv")

# 1. merge vancouver harness results
res={}
if os.path.exists(VAN):
    for r in csv.DictReader(open(VAN),delimiter="\t"):
        res[r["photo"]]=r
rows=list(csv.DictReader(open(COMB)))
for r in rows:
    if r["dataset"]=="vancouver" and r["photo"] in res:
        h=res[r["photo"]]
        r["app_nearby_n_wide"]=h["wide_n"]; r["app_poi_rank"]=h["wide_rank"]
        r["app_poi_dist_m"]=h["wide_dist"]
        r["app_nearby_top1"]=(h["top3_wide"].split(" | ")[0] if h["top3_wide"] else "")
cols=list(rows[0].keys())
with open(COMB,"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)

def eval_class(r):
    if r["poi_match_keyword"].strip(): return "venue"
    if r["dataset"]=="vancouver": return "held"
    return "non_poi"

for r in rows: r["_cls"]=eval_class(r)

def show(title, rs): print(f"\n{title} (n={len(rs) if (rs:=rs) else 0})")

print("="*66)
print("COMBINED BASELINE EVALUATION  (blanks/held excluded from denominators)")
print("="*66)
for ds in ["union-city","vancouver","ALL"]:
    sub=[r for r in rows if ds=="ALL" or r["dataset"]==ds]
    venue=[r for r in sub if r["_cls"]=="venue"]
    nonpoi=[r for r in sub if r["_cls"]=="non_poi"]
    held=[r for r in sub if r["_cls"]=="held"]
    # only count venue rows that actually have a harness rank (non-blank)
    ranked=[r for r in venue if r["app_poi_rank"] not in ("","")]
    ranked=[r for r in venue if r["app_poi_rank"]!=""]
    retr=[r for r in ranked if r["app_poi_rank"]!="MISS"]
    gap=[r for r in ranked if r["app_poi_rank"]=="MISS"]
    print(f"\n### {ds}  (rows={len(sub)})")
    print(f"  venue rows evaluated : {len(ranked)}   (excluded/held: {len(held)})")
    if ranked:
        print(f"    retrievable by coords : {len(retr)}/{len(ranked)}  ({100*len(retr)/len(ranked):.0f}%)")
        print(f"    retrieval-gap (MISS)  : {len(gap)}/{len(ranked)}  ({100*len(gap)/len(ranked):.0f}%)  <- caption/OCR necessary")
    print(f"  non-POI (must-refuse) : {len(nonpoi)}")
    if nonpoi:
        cnts=[int(r["app_nearby_n_wide"]) for r in nonpoi if r["app_nearby_n_wide"].isdigit()]
        if cnts: print(f"    hallucination pressure: median {sorted(cnts)[len(cnts)//2]} POIs within 250m near these")
    print(f"  held (blank, fill in meeting): {len(held)}")

print("\n" + "-"*66)
print("HELD rows (reliability not securable now — fill GT in the meeting):")
for r in rows:
    if r["_cls"]=="held":
        print(f"  [{r['dataset']}] {r['photo'][:24]}  orig=\"{r['notes'].split('orig_gt=')[-1][:40]}\"")
