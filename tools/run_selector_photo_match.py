#!/usr/bin/env python3
"""PWE-13 photo–place matcher: cascade access_ocr + FastVLM place_match.

Framing (not distance-first):
  For each MapKit top-K candidate, ask whether the photo could have been taken
  at that place; pick the one that most clearly matches the image.

Pipeline:
  1) examples.selector_access_ocr — cheap OCR / access-label rules
  2) If still on nearest-like weak signal (optional modes), FastVLM with the
     ``place_match`` prompt re-ranks the same top-K using the photo only.

Use the FastVLM venv (torch+MPS), e.g.:
  poi-data/tools/fastvlm-venv/bin/python tools/run_selector_photo_match.py

Modes:
  --vlm-on always     VLM on every case with candidates
  --vlm-on miss_only  VLM only when access_ocr equals nearest (no cheap win)
  --vlm-on never      access_ocr only (debug)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
import unicodedata
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "tools", ROOT / "examples"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import match_score as ms
import run_algorithm as ra
from run_vlm_topk_rerank import (
    FastVLM,
    build_prompt,
    cache_key,
    load_cache,
    parse_selection,
    photo_path,
)
import selector_access_ocr as access_ocr


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nearest(cands: List[Dict[str, Any]]) -> str:
    return (cands[0].get("name") if cands else "") or ""


def should_call_vlm(mode: str, access_pred: str, nearest_pred: str, cands: List[Dict[str, Any]]) -> bool:
    if not cands:
        return False
    if mode == "never":
        return False
    if mode == "always":
        return True
    # miss_only: VLM when cheap selector did not move off nearest
    return _norm(access_pred) == _norm(nearest_pred)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=str(ROOT / "poi-data"))
    p.add_argument("--model-repo", default=str(ROOT / "poi-data/tools/ml-fastvlm"))
    p.add_argument(
        "--model-path",
        default=str(ROOT / "poi-data/tools/ml-fastvlm/checkpoints/llava-fastvithd_0.5b_stage3"),
    )
    p.add_argument("--candidate-limit", type=int, default=5)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--vlm-on", choices=["always", "miss_only", "never"], default="miss_only")
    p.add_argument("--prompt-style", default="place_match")
    p.add_argument("--cache", default=None)
    p.add_argument("--run-name", default="selector-photo-match")
    p.add_argument(
        "--only-gt-in-topk",
        action="store_true",
        help="Score/run only cases where GT is already in the top-K list (PWE-13 pool)",
    )
    p.add_argument(
        "--only-access-miss",
        action="store_true",
        help="Only cases where access_ocr is wrong but GT is in top-K (photo-match stress set)",
    )
    p.add_argument(
        "--full-cascade-report",
        action="store_true",
        help="After a filtered VLM run, also score a virtual full-166 cascade "
        "(access_ocr default, VLM overrides only on filtered keys)",
    )
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    model_repo, model_path = Path(args.model_repo), Path(args.model_path)
    cfg = ms.load_config(str(data_dir / "dashboard_config.json"))
    rows = ms.read_rows(str(data_dir / "eval_set_reconciled.csv"))
    cand_paths = [ms.active_mapkit_candidate_file(str(data_dir))]
    candidates_data = ms.load_candidates(cand_paths)
    all_cases = ra.build_cases(
        rows,
        cfg,
        candidates_data,
        "all",
        ["image", "nearby_candidates", "ocr_text"],
        args.candidate_limit,
    )
    cases = list(all_cases)

    if args.only_gt_in_topk or args.only_access_miss:
        filtered = []
        for case in cases:
            cands = case["input"].get("nearby_candidates") or []
            g = _norm(case["_gt"])
            if not g or g not in {_norm(c.get("name")) for c in cands}:
                continue
            if args.only_access_miss:
                pred = access_ocr.predict(case["input"])
                if pred and _norm(pred) == g:
                    continue
            filtered.append(case)
        cases = filtered

    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("no cases to run")

    style = args.prompt_style
    cache_path = Path(
        args.cache
        or (
            data_dir
            / "generated"
            / f"photo_match_{style}_k{args.candidate_limit}_{args.vlm_on}_cache.jsonl"
        )
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)

    model: Optional[FastVLM] = None
    preds: List[Dict[str, Any]] = []
    decisions: List[str] = []
    vlm_calls = 0

    for pos, case in enumerate(cases, 1):
        inp = case["input"]
        cands = inp.get("nearby_candidates") or []
        nearest = _nearest(cands)
        access_pred = access_ocr.predict(inp) if cands else ""
        decision = "access_ocr"
        prediction = access_pred
        raw_out = ""
        error = ""
        latency_ms = 0

        if should_call_vlm(args.vlm_on, access_pred, nearest, cands):
            key = cache_key(case, cands, model_path, prompt_style=style)
            item = cache.get(key)
            if item is None:
                image = photo_path(data_dir, cfg, case["_dataset"], case["_photo"])
                t0 = time.monotonic()
                if image is None:
                    decision, prediction = "missing_image_keep_access", access_pred or nearest
                else:
                    try:
                        if model is None:
                            print("loading FastVLM…", flush=True)
                            model = FastVLM(model_repo, model_path)
                        raw_out = model.infer(image, build_prompt(cands, style=style))
                        selected = parse_selection(raw_out, cands)
                        if selected is None:
                            decision = "vlm_unparsed_keep_access"
                            prediction = access_pred or nearest
                        else:
                            prediction = (cands[selected].get("name") or "").strip()
                            decision = (
                                "vlm_place_match"
                                if _norm(prediction) != _norm(access_pred)
                                else "vlm_agrees_access"
                            )
                        vlm_calls += 1
                    except Exception as exc:
                        error = repr(exc)
                        decision, prediction = "vlm_error_keep_access", access_pred or nearest
                latency_ms = round((time.monotonic() - t0) * 1000)
                item = {
                    "key": key,
                    "dataset": case["_dataset"],
                    "photo": case["_photo"],
                    "prompt_style": style,
                    "prediction": prediction,
                    "access_pred": access_pred,
                    "nearest": nearest,
                    "decision": decision,
                    "raw_output": raw_out,
                    "latency_ms": latency_ms,
                    "error": error,
                }
                with cache_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                cache[key] = item
            else:
                prediction = item.get("prediction") or access_pred or nearest
                decision = item.get("decision") or "cache_hit"
                raw_out = item.get("raw_output") or ""
                if decision.startswith("vlm"):
                    vlm_calls += 1

        preds.append({"prediction": prediction, "reason": decision, "error": None})
        decisions.append(decision)
        print(
            f"[{pos}/{len(cases)}] {case['_photo']}: {decision} -> {prediction!r}",
            flush=True,
        )

    scored = ra._score(cases, preds, "exact")
    # top5-in-list conditional (when running full 166, still report PWE-13 slice)
    top5_correct = top5_n = 0
    for case, pred in zip(cases, preds):
        cands = case["input"].get("nearby_candidates") or []
        g = _norm(case["_gt"])
        if g not in {_norm(c.get("name")) for c in cands}:
            continue
        top5_n += 1
        if _norm(pred.get("prediction")) == g:
            top5_correct += 1

    metrics = {k: v for k, v in scored.items() if k != "cases"}
    metrics["top5_in_list_n"] = top5_n
    metrics["top5_in_list_correct"] = top5_correct
    metrics["top5_in_list_acc"] = round(100 * top5_correct / top5_n, 1) if top5_n else None
    metrics["vlm_calls"] = vlm_calls
    metrics["vlm_on"] = args.vlm_on
    metrics["prompt_style"] = style

    # Optional: stitch VLM overrides onto full cohort for cascade estimate.
    if args.full_cascade_report and args.only_access_miss:
        override = {
            (c["_dataset"], c["_photo"]): (p.get("prediction") or "")
            for c, p in zip(cases, preds)
        }
        casc_preds = []
        for case in all_cases:
            key = (case["_dataset"], case["_photo"])
            if key in override and override[key]:
                casc_preds.append({"prediction": override[key], "reason": "vlm_override", "error": None})
            else:
                pred = access_ocr.predict(case["input"])
                casc_preds.append({"prediction": pred, "reason": "access_ocr", "error": None})
        casc = ra._score(all_cases, casc_preds, "exact")
        metrics["cascade_full_n"] = casc["n_eligible"]
        metrics["cascade_full_correct"] = casc["correct"]
        metrics["cascade_full_abstained"] = casc["abstained"]
        metrics["cascade_full_accuracy_pct"] = casc["accuracy_pct"]
        # top5 pool under cascade
        t5c = t5n = 0
        for case, pred in zip(all_cases, casc_preds):
            cands = case["input"].get("nearby_candidates") or []
            g = _norm(case["_gt"])
            if g not in {_norm(c.get("name")) for c in cands}:
                continue
            t5n += 1
            if _norm(pred.get("prediction")) == g:
                t5c += 1
        metrics["cascade_top5_correct"] = t5c
        metrics["cascade_top5_n"] = t5n
        metrics["cascade_top5_acc"] = round(100 * t5c / t5n, 1) if t5n else None

    safe = ra._safe_name(args.run_name)
    runs_dir = data_dir / "generated/runs"
    version = ra._pick_version(str(runs_dir), safe, "new")
    scope_bits = []
    if args.only_access_miss:
        scope_bits.append("access_miss")
    if args.only_gt_in_topk:
        scope_bits.append("gt_in_topk")
    if args.limit is not None:
        scope_bits.append(f"first-{args.limit}")
    scope = "+".join(scope_bits) if scope_bits else "all"
    record = {
        "name": args.run_name,
        "safe_name": safe,
        "version": version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "mode": "exact",
        "params": ["image", "nearby_candidates", "ocr_text"],
        "candidate_limit": args.candidate_limit,
        "lang": "fastvlm-mps-photo-match",
        "prompt_style": style,
        "vlm_on": args.vlm_on,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_set_sha256": ra.evaluation_set_sha256(cases),
        "data_snapshot_sha256": ra.data_snapshot_sha256(
            [
                str(data_dir / "eval_set_reconciled.csv"),
                str(data_dir / "dashboard_config.json"),
                *cand_paths,
            ]
        ),
        "script_text": Path(__file__).read_text(encoding="utf-8"),
        "metrics": metrics,
        "cases": scored["cases"],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{safe}__v{version}.json"
    run_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "run": str(run_path),
                "metrics": metrics,
                "cache": str(cache_path),
                "decisions": dict(sorted({d: decisions.count(d) for d in set(decisions)}.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
