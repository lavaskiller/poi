#!/usr/bin/env python3
"""Merge extracted signals (OCR + MapKit baseline) into eval_set_reconciled.csv.
Non-destructive: only fills EMPTY cells, never overwrites existing (hand-curated) values.
Matches by `photo` filename. Idempotent — safe to re-run."""
import csv, sys

CSV = "eval_set_reconciled.csv"

# ---- load OCR text (both sets), keyed by photo ----
ocr = {}
for path in ("ls_ocr_text.tsv", "ocr_text.tsv"):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if c and c[0]:
                    ocr[c[0]] = c[1] if len(c) > 1 else ""
    except FileNotFoundError:
        pass

# ---- load MapKit baseline (linkedspaces), keyed by photo ----
# cols: photo strict_n strict_rank strict_dist wide_n wide_rank wide_dist retries top3_wide
base = {}
with open("ls_nearby_results.tsv", encoding="utf-8", errors="replace") as f:
    next(f, None)
    for line in f:
        c = line.rstrip("\n").split("\t")
        if not c or not c[0]:
            continue
        top3 = c[8] if len(c) > 8 else ""
        top1 = top3.split("@")[0].strip() if top3 else ""
        base[c[0]] = {"rank": c[5], "n": c[4], "dist": c[6], "top1": top1}

rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
fields = list(rows[0].keys())

filled_ocr = filled_base = 0
for r in rows:
    p = r["photo"]
    # OCR -> caption_ondevice (only if we have text and cell is empty)
    if p in ocr and ocr[p].strip() and not (r.get("caption_ondevice") or "").strip():
        r["caption_ondevice"] = ocr[p]
        filled_ocr += 1
    # MapKit baseline -> app_* (only if cell empty)
    if p in base and not (r.get("app_poi_rank") or "").strip():
        b = base[p]
        r["app_poi_rank"] = b["rank"]
        r["app_nearby_n_wide"] = b["n"]
        r["app_poi_dist_m"] = b["dist"]
        r["app_nearby_top1"] = b["top1"]
        filled_base += 1

with open(CSV, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

print(f"OCR text filled:      {filled_ocr} rows")
print(f"MapKit baseline filled: {filled_base} rows")
print(f"CSV rewritten: {CSV} ({len(rows)} rows, {len(fields)} cols)")
