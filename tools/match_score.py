#!/usr/bin/env python3
"""Provider-aware POI candidate-retrieval metrics for the MVP dashboard.

MVP policy:
- South Korea rows are currently held out until Kakao Local canonical/candidate
  data is populated.
- Non-Korea candidate retrieval is evaluated against MapKit candidates.
- The primary matching rule is exact string equality between the provider
  canonical name and provider candidate name.
- provider_place_id is kept when present, but is nullable and never required.

Important: this module measures whether the provider candidate list contains the
human GT place and at what rank. It is not a visual/user-intent identification
accuracy evaluator; selection accuracy requires submitted algorithm predictions.

This module intentionally uses only the Python standard library so it runs in
this workspace without pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Honor POI_DATA_DIR so the CLI reaches a split-out data workspace, matching
# server.py. Falls back to the repo dir when unset (code+data colocated).
DATA_ROOT = os.environ.get("POI_DATA_DIR") or ROOT
CSV_PATH = os.path.join(DATA_ROOT, "eval_set_reconciled.csv")
_data_cfg = os.path.join(DATA_ROOT, "dashboard_config.json")
CONFIG_PATH = _data_cfg if os.path.exists(_data_cfg) else os.path.join(ROOT, "dashboard_config.json")
CANDIDATE_DIR = os.path.join(DATA_ROOT, "generated")
DEFAULT_CANDIDATE_FILES = [
    os.path.join(CANDIDATE_DIR, "mapkit_candidates.jsonl"),
    os.path.join(CANDIDATE_DIR, "kakao_local_candidates.jsonl"),
]

KR_NAMES = {"South Korea", "Korea", "Republic of Korea", "대한민국", "한국", "KR", "KOR"}


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_rows(path: str = CSV_PATH) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def canonical_country(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    ds = (row.get("dataset") or "").strip()
    by_ds = cfg.get("country_by_dataset") or {}
    if ds in by_ds:
        return by_ds[ds]
    raw = (row.get("country") or "").strip()
    return (cfg.get("country_normalize") or {}).get(raw, raw or "Unknown")


def provider_for_row(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    return "kakao_local" if canonical_country(row, cfg) in KR_NAMES else "mapkit"


def input_place_name(row: Dict[str, str]) -> str:
    return (row.get("input_place_name") or "").strip()


def gt_for_provider(row: Dict[str, str], provider: str) -> str:
    """Provider-canonical ground-truth name used for scoring.

    GT is split per provider: ``gt_mapkit`` for MapKit rows, ``gt_kakao`` for
    Kakao rows, populated by the provider name-resolution job. Until that job
    fills them, fall back to the raw ``input_place_name`` so existing metrics
    keep working.
    """
    col = "gt_kakao" if provider == "kakao_local" else "gt_mapkit"
    return (row.get(col) or "").strip() or input_place_name(row)


def confidence_tier(row: Dict[str, str], cfg: Dict[str, Any]) -> str:
    raw = (row.get("gt_confidence") or "").strip()
    return (cfg.get("confidence_rollup") or {}).get(raw, raw)


def exact_equal(a: str, b: str) -> bool:
    return (a or "").strip() == (b or "").strip()


def normalized_equal(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        s = (s or "").casefold().strip()
        s = re.sub(r"[\s\-_·•|/\\]+", " ", s)
        s = re.sub(r"[^\w\s가-힣ぁ-んァ-ン一-龯]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    return bool(norm(a) and norm(a) == norm(b))


def parse_top_candidates(top: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, part in enumerate((top or "").split(" | "), start=1):
        part = part.strip()
        if not part:
            continue
        name, _, dist = part.rpartition("@")
        out.append({
            "name": (name or part).strip(),
            "rank": idx,
            "distance_m": _num_or_none(dist.strip().replace("m", "")),
        })
    return out


def _num_or_none(v: str) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def convert_mapkit_tsv(tsv_path: str, out_path: str) -> int:
    """Convert the current MapKit TSV probe output to candidate JSONL.

    The current Swift probe does not expose a stable MapKit place ID, so
    provider_place_id is written as null.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    n = 0
    with open(tsv_path, encoding="utf-8", errors="replace", newline="") as f, open(out_path, "w", encoding="utf-8") as out:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            photo = (row.get("photo") or "").strip()
            if not photo:
                continue
            for cand in parse_top_candidates(row.get("top3_wide") or ""):
                rec = {
                    "photo": photo,
                    "provider": "mapkit",
                    "provider_place_id": None,
                    "name": cand["name"],
                    "lat": None,
                    "lon": None,
                    "address": "",
                    "category": "",
                    "rank": cand["rank"],
                    "distance_m": cand["distance_m"],
                    "source": os.path.basename(tsv_path),
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    return n


def load_candidates(paths: Iterable[str] = DEFAULT_CANDIDATE_FILES) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                photo = (rec.get("photo") or rec.get("case_id") or "").strip()
                provider = (rec.get("provider") or "").strip()
                if not photo or not provider:
                    continue
                try:
                    rec["rank"] = int(rec.get("rank") or 0)
                except Exception:
                    rec["rank"] = 0
                grouped[(provider, photo)].append(rec)
    for key in list(grouped):
        grouped[key].sort(key=lambda r: (r.get("rank") or 999999))
    return grouped


def _rank_from_candidates(gt: str, candidates: List[Dict[str, Any]], matcher: Callable[[str, str], bool]) -> Optional[int]:
    for idx, cand in enumerate(candidates, start=1):
        rank = int(cand.get("rank") or idx)
        if matcher(gt, cand.get("name") or ""):
            return rank
    return None


def _rank_from_legacy(row: Dict[str, str]) -> Optional[int | str]:
    rk = (row.get("app_poi_rank") or "").strip()
    if not rk:
        return None
    if rk == "MISS":
        return "MISS"
    if rk.isdigit():
        return int(rk)
    return None


def evaluate(dataset: str = "all", mode: str = "exact", rows: Optional[List[Dict[str, str]]] = None,
             candidates: Optional[Dict[Tuple[str, str], List[Dict[str, Any]]]] = None,
             cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    rows = rows if rows is not None else read_rows()
    candidates = candidates if candidates is not None else load_candidates()
    matcher = exact_equal if mode in ("exact", "raw") else normalized_equal

    counts = Counter()
    by_provider: Dict[str, Counter] = defaultdict(Counter)
    by_dataset: Dict[str, Counter] = defaultdict(Counter)
    cases: List[Dict[str, Any]] = []

    for row in rows:
        ds = (row.get("dataset") or "").strip()
        if dataset != "all" and ds != dataset:
            continue
        counts["rows"] += 1
        tier = confidence_tier(row, cfg)
        provider = provider_for_row(row, cfg)
        gt = gt_for_provider(row, provider)
        country = canonical_country(row, cfg)
        photo = (row.get("photo") or "").strip()

        if provider == "kakao_local":
            status = "excluded_korea_pending_kakao"
            counts[status] += 1
        elif tier == "non_poi":
            status = "excluded_non_poi"
            counts[status] += 1
        elif not gt:
            status = "excluded_no_gt"
            counts[status] += 1
        else:
            counts["eligible"] += 1
            cand = candidates.get((provider, photo), [])
            rank: Optional[int | str]
            legacy_rank = _rank_from_legacy(row) if provider == "mapkit" else None
            if legacy_rank is not None:
                # Backward-compatible source of truth for the current reconciled CSV.
                # It was produced by the MapKit probe and includes ranks beyond the
                # top3 preview stored in ls_nearby_results.tsv. Do not let the
                # lossy preview JSONL override this complete rank field.
                rank = legacy_rank
                source = "legacy_app_poi_rank"
            elif cand:
                rank = _rank_from_candidates(gt, cand, matcher)
                if rank is None:
                    rank = "MISS"
                source = "candidate_jsonl"
            else:
                rank = None
                source = "none"

            if rank is None:
                status = "no_provider_data"
                counts[status] += 1
            else:
                counts["evaluated"] += 1
                by_provider[provider]["evaluated"] += 1
                by_dataset[ds]["evaluated"] += 1
                if rank == "MISS":
                    status = "search_failure"
                    counts["miss"] += 1
                    counts[status] += 1
                    by_provider[provider]["miss"] += 1
                    by_dataset[ds]["miss"] += 1
                else:
                    r = int(rank)
                    status = "correct" if r == 1 else "selection_failure"
                    if r == 1:
                        counts["rank1"] += 1
                        by_provider[provider]["rank1"] += 1
                        by_dataset[ds]["rank1"] += 1
                    else:
                        counts["selection_failure"] += 1
                    if r <= 3:
                        counts["top3"] += 1
                        by_provider[provider]["top3"] += 1
                        by_dataset[ds]["top3"] += 1
                    if r <= 5:
                        counts["top5"] += 1
                        by_provider[provider]["top5"] += 1
                        by_dataset[ds]["top5"] += 1

        by_provider[provider]["rows"] += 1
        by_dataset[ds]["rows"] += 1
        if len(cases) < 500:
            cases.append({
                "dataset": ds,
                "photo": photo,
                "gt": gt,
                "country": country,
                "provider": provider,
                "status": status,
                "rank": None if 'rank' not in locals() else rank,
                "source": None if 'source' not in locals() else source,
            })
        # avoid leaking previous loop values into excluded rows
        if 'rank' in locals():
            del rank
        if 'source' in locals():
            del source

    n = counts["evaluated"]

    def rate(k: str) -> float:
        return (counts[k] / n) if n else 0.0

    def summarize(counter: Counter) -> Dict[str, Any]:
        en = counter["evaluated"]
        return {
            "rows": counter["rows"],
            "evaluated": en,
            "rank1": counter["rank1"],
            "top3": counter["top3"],
            "top5": counter["top5"],
            "miss": counter["miss"],
            "rank1_rate": counter["rank1"] / en if en else 0.0,
            "top3_rate": counter["top3"] / en if en else 0.0,
            "top5_rate": counter["top5"] / en if en else 0.0,
            "miss_rate": counter["miss"] / en if en else 0.0,
        }

    return {
        "dataset": dataset,
        "mode": "exact" if mode in ("raw", "exact") else "normalized",
        "matching_policy": {
            "primary": "same-provider exact string equality",
            "korea_provider": "kakao_local (held out until Kakao data is available)",
            "non_korea_provider": "mapkit",
            "provider_place_id": "nullable/fallback; not required for MVP scoring",
        },
        "counts": dict(counts),
        "n": n,
        "rank1": counts["rank1"],
        "top3": counts["top3"],
        "top5": counts["top5"],
        "miss": counts["miss"],
        "rank1_rate": rate("rank1"),
        "top3_rate": rate("top3"),
        "top5_rate": rate("top5"),
        "miss_rate": rate("miss"),
        "search_failure": counts["search_failure"],
        "selection_failure": counts["selection_failure"],
        "no_provider_data": counts["no_provider_data"],
        "excluded_non_poi": counts["excluded_non_poi"],
        "excluded_no_gt": counts["excluded_no_gt"],
        "excluded_korea_pending_kakao": counts["excluded_korea_pending_kakao"],
        "by_provider": {k: summarize(v) for k, v in sorted(by_provider.items())},
        "by_dataset": {k: summarize(v) for k, v in sorted(by_dataset.items())},
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Provider-aware POI candidate-retrieval metrics")
    ap.add_argument("--dataset", default="all")
    ap.add_argument("--mode", default="exact", choices=["exact", "raw", "normalized"])
    ap.add_argument("--csv", default=CSV_PATH)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--convert-mapkit-tsv", metavar="TSV")
    ap.add_argument("--out", default=os.path.join(CANDIDATE_DIR, "mapkit_candidates.jsonl"))
    args = ap.parse_args()

    if args.convert_mapkit_tsv:
        n = convert_mapkit_tsv(args.convert_mapkit_tsv, args.out)
        print(json.dumps({"ok": True, "written": n, "out": args.out}, ensure_ascii=False))
        return 0

    result = evaluate(dataset=args.dataset, mode=args.mode, rows=read_rows(args.csv))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"n={result['n']} rank1={result['rank1']} top3={result['top3']} top5={result['top5']} miss={result['miss']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
