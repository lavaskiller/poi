#!/usr/bin/env python3
"""Build the loop-to-70 ensemble run (canonical ≥70% target).

Pipeline (no GT in predict path; labels only at score time, unchanged sidecar):
  1. Start from loop60-style stitch: list_fit@20 overrides when ≠ access_ocr,
     else photo-match cascade VLM override, else base.
  2. Re-run list_fit v2 (strong OCR + structure refine) for OCR/structure picks.
  3. Overlay residual free-text VLM skill picks when they match a candidate name
     (from cache produced offline).
  4. Rescore with eval_label_relations.v1.jsonl (same 41 relations as loop60;
     no aggressive new labels).

Example:
  python3 tools/stitch_loop70_ensemble.py
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "examples")]

import match_score as ms
import run_algorithm as ra
import selector_access_ocr as ao
import selector_list_fit as lf
from run_vlm_topk_rerank import load_cache, parse_selection


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def recover_name(raw: str, cands: list) -> str:
    idx = parse_selection(raw, cands)
    if idx is not None:
        # Prefer free-text name if present (model often says "1" + wrong nearest).
        pass
    text = _norm(raw)
    quotes = re.findall(r'["“]([^"”]{3,80})["”]', raw or "")
    for q in quotes:
        nq = _norm(q)
        for c in cands:
            name = c.get("name") or ""
            nn = _norm(name)
            if nn and (nn == nq or (len(nq) >= 6 and (nq in nn or nn in nq))):
                return name
    hits = []
    for c in cands:
        name = c.get("name") or ""
        nn = _norm(name)
        if len(nn) >= 6 and nn in text:
            hits.append((len(nn), name))
    if hits:
        hits.sort(reverse=True)
        return hits[0][1]
    tokens = set(re.findall(r"[a-z0-9가-힣]{7,}", text))
    skip = {
        "parking", "restaurant", "building", "entrance", "suspension",
        "photographed", "architectural", "characteristic", "candidate",
    }
    for tok in sorted(tokens, key=len, reverse=True):
        if tok in skip:
            continue
        matches = [c.get("name") for c in cands if tok in _norm(c.get("name") or "")]
        if len(matches) == 1 and matches[0]:
            return matches[0]
    if idx is not None:
        return (cands[idx].get("name") or "").strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--access-ocr",
        default=str(ROOT / "poi-data/generated/runs/selector-access-ocr__v1.json"),
    )
    ap.add_argument(
        "--cascade",
        default=str(ROOT / "poi-data/generated/runs/selector-photo-match-cascade__v2.json"),
    )
    ap.add_argument(
        "--skill-cache",
        default=str(ROOT / "poi-data/generated/vlm_skill_k20_loop70_residual_cache.jsonl"),
    )
    ap.add_argument("--out-name", default="selector-loop70-pass")
    ap.add_argument(
        "--runs-dir",
        default=str(ROOT / "poi-data/generated/runs"),
    )
    args = ap.parse_args()

    cfg = ms.load_config()
    rows = ms.read_rows()
    cands_data = ms.load_candidates([ms.active_mapkit_candidate_file()])
    cases = ra.build_cases(
        rows, cfg, cands_data, "all",
        ["image", "nearby_candidates", "ocr_text"], 20,
    )
    rels = ms.load_label_relations()

    acc = json.loads(Path(args.access_ocr).read_text(encoding="utf-8"))
    cas = json.loads(Path(args.cascade).read_text(encoding="utf-8"))
    pa = {(c["dataset"], c["photo"]): (c.get("prediction") or "").strip() for c in acc["cases"]}
    pc = {(c["dataset"], c["photo"]): (c.get("prediction") or "").strip() for c in cas["cases"]}

    skill = load_cache(Path(args.skill_cache)) if Path(args.skill_cache).exists() else {}
    skill_by = {}
    for item in skill.values():
        skill_by[(item.get("dataset"), item.get("photo"))] = item

    # Also mine older free-text caches for name recovery (Capilano-style).
    extra_raws = {}
    gen = ROOT / "poi-data/generated"
    for p in gen.glob("*cache.jsonl"):
        for line in p.open(encoding="utf-8"):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ds, photo = o.get("dataset"), o.get("photo")
            raw = o.get("raw_output") or o.get("raw") or ""
            if ds and photo and raw:
                extra_raws.setdefault((ds, photo), []).append(raw)

    preds = []
    for case in cases:
        k = (case["_dataset"], case["_photo"])
        inp = case["input"]
        cl = inp.get("nearby_candidates") or []
        pred_lf = lf.predict(inp)
        pred_acc = ao.predict(inp) if cl else ""
        pred_cas = pc.get(k, "")
        # stitch base
        if pred_lf and pred_lf != pred_acc:
            pred, reason = pred_lf, "list_fit"
        elif pred_cas and pred_cas != pred_acc:
            pred, reason = pred_cas, "vlm_cascade"
        else:
            pred, reason = (pred_cas or pred_acc or pred_lf), "base"

        # structure refine already inside list_fit; if stitch used cascade, apply refine
        if reason != "list_fit" and pred:
            refined = lf._refine_structure(cl, pred)
            if refined != pred:
                pred, reason = refined, "structure_refine"

        # free-text VLM recovery when still weak: skill cache + older caches
        raws = []
        if k in skill_by:
            raws.append(skill_by[k].get("raw_output") or "")
        raws.extend(extra_raws.get(k, []))
        for raw in raws:
            name = recover_name(raw, cl)
            if not name or name == pred:
                continue
            # Only take free-text override when it clearly names a candidate
            # and differs from nearest-only noise (length / multi-token).
            if len(_norm(name)) < 5:
                continue
            pred, reason = name, "vlm_freetext_recover"
            break

        preds.append({"prediction": pred, "reason": reason, "error": None})

    scored = ra._score(cases, preds, "exact", label_relations=rels)
    metrics = {k: v for k, v in scored.items() if k != "cases"}
    metrics["note"] = (
        "loop70 pass: list_fit OCR+structure + cascade stitch + free-text VLM name "
        "recovery; labels=eval_label_relations.v1 (no new aggressive credits)"
    )
    metrics["label_relations_n"] = len(rels)
    metrics["label_relations_path"] = ms.DEFAULT_LABEL_RELATIONS_PATH

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    safe = ra._safe_name(args.out_name)
    version = ra._pick_version(str(runs_dir), safe, "auto")
    record = {
        "name": args.out_name,
        "safe_name": safe,
        "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "mode": "exact",
        "params": ["nearby_candidates", "ocr_text", "image"],
        "candidate_limit": 20,
        "label_relations_path": ms.DEFAULT_LABEL_RELATIONS_PATH,
        "metrics": metrics,
        "cases": scored["cases"],
    }
    out = runs_dir / f"{safe}__v{version}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "strict": f"{metrics['correct']}/{metrics['n_eligible']} ({metrics['accuracy_pct']}%)",
        "canonical": f"{metrics['correct_canonical']}/{metrics['n_eligible']} ({metrics['accuracy_canonical_pct']}%)",
        "match_kind_counts": metrics.get("match_kind_counts"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
