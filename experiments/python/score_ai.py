#!/usr/bin/env python3
"""Grade one or more model runs and compare. Usage:
     python3 score_ai.py label1=results1.tsv label2=results2.tsv ...
Held rows (no securable GT) are excluded. Prints per-run venue/non-POI grades + a compare table,
and lists the non-POI hallucinations for each run.
"""
import csv, json, re, os, sys
HERE=os.path.dirname(os.path.abspath(__file__))
rows={r["photo"]:r for r in csv.DictReader(open(os.path.join(HERE,"eval_set_combined.csv")))}
def cls(r):
    if r["poi_match_keyword"].strip(): return "venue"
    if r["dataset"]=="vancouver": return "held"
    return "non_poi"
def parse(raw):
    m=re.search(r"\{.*\}", raw, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except: return None
def named_venue(j):
    name=str(j.get("placeName","") or ""); gran=str(j.get("granularity","") or "").lower()
    return (gran=="venue") and not bool(j.get("isNonPOI",False)) and name.strip() and name.lower() not in ("none","unknown")
def grade(cl,kw,j):
    if j is None: return "unparsed"
    if cl=="non_poi": return "HALLUCINATION" if named_venue(j) else "CORRECT_REFUSE"
    if cl=="venue":
        name=str(j.get("placeName","") or ""); k=kw.lower()
        if k and (k in name.lower() or name.lower() in k): return "EXACT"
        return "WRONG_VENUE" if named_venue(j) else "AREA_OR_NONE"
    return "held"
def load(path):
    out={}
    for r in csv.DictReader(open(path),delimiter="\t"):
        out[r["photo"]]=(r["status"], parse(r["raw"]) if r["status"]=="ok" else None)
    return out

runs=[]
for a in sys.argv[1:]:
    label,path=a.split("=",1)
    runs.append((label, load(os.path.join(HERE,path))))

print(f"{'run':22} {'exact%':>7} {'wrong':>6} {'area':>5} {'HALLUC%':>8} {'refuse':>7} {'err':>4}")
print("-"*66)
comp={}
for label,data in runs:
    gv={}; gn={}; err=0
    for ph,r in rows.items():
        cl=cls(r)
        if cl=="held": continue
        st,j=data.get(ph,("missing",None))
        if st!="ok": err+=1; continue
        g=grade(cl,r["poi_match_keyword"],j)
        (gv if cl=="venue" else gn)[g]=(gv if cl=="venue" else gn).get(g,0)+1
    vt=sum(gv.values()); nt=sum(gn.values())
    ex=gv.get("EXACT",0); wr=gv.get("WRONG_VENUE",0); ar=gv.get("AREA_OR_NONE",0)
    ha=gn.get("HALLUCINATION",0); rf=gn.get("CORRECT_REFUSE",0)
    comp[label]=dict(exact=ex/vt if vt else 0, hall=ha/nt if nt else 0, vt=vt, nt=nt)
    print(f"{label:22} {100*ex/vt if vt else 0:6.0f}% {wr:6} {ar:5} {100*ha/nt if nt else 0:7.0f}% {rf:7} {err:4}")

# hallucination detail per run
for label,data in runs:
    hs=[]
    for ph,r in rows.items():
        if cls(r)!="non_poi": continue
        st,j=data.get(ph,("missing",None))
        if st=="ok" and grade("non_poi","",j)=="HALLUCINATION":
            hs.append((ph, r["input_place_name"], j.get("placeName","")))
    if hs:
        print(f"\n[{label}] {len(hs)} hallucinations:")
        for ph,gt,pred in hs[:20]:
            print(f"   {ph[:22]:22} {gt[:30]:30} -> '{pred}'")
