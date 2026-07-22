#!/usr/bin/env python3
"""Provider-agnostic core for the GT name-classification jobs.

Both the MapKit and Kakao jobs answer the same question per row: *is
``input_place_name`` written the way this provider names the place?* The only
per-provider differences are (a) which column is written, (b) how candidate
place names are fetched, and (c) the sentinel tokens. This module holds
everything else so the two jobs stay identical in policy.

Classification, for a row this provider OWNS (country-based ``provider_for_row``)
and that is a POI with an input name:
  * an **exact** candidate match (``match_score.exact_equal``)
        -> copy ``input_place_name`` verbatim (already a provider name);
  * else a **normalized** match (``match_score.normalized_equal``)  -> sim_token;
  * else (or no candidates)                                          -> non_token.
Rows this provider does NOT own get ``other_marker``; ``non_poi`` rows and rows
without an input name are out of scope and cleared to empty.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402

Targets = List[Tuple[int, Dict[str, str]]]
FetchFn = Callable[[Targets], Dict[str, List[str]]]


@dataclass(frozen=True)
class ProviderCfg:
    column: str        # CSV column this job writes ("gt_mapkit" | "gt_kakao")
    owns: str          # provider_for_row value this job owns ("mapkit" | "kakao_local")
    other_marker: str  # stamped on rows this job does NOT own ("KOR" | "NON_KR")
    sim_token: str     # normalized-only match  ("SIM_MAPKIT" | "SIM_KAKAO")
    non_token: str     # no match / no candidates ("NON_MAPKIT" | "NON_KAKAO")


MAPKIT = ProviderCfg("gt_mapkit", "mapkit", "KOR", "SIM_MAPKIT", "NON_MAPKIT")
KAKAO = ProviderCfg("gt_kakao", "kakao_local", "NON_KR", "SIM_KAKAO", "NON_KAKAO")


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def sanitize(s: str) -> str:
    return (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def is_probe_target(row: Dict[str, str], cfg: dict, pcfg: ProviderCfg) -> bool:
    """Rows this provider owns that are POIs with an input name and coords."""
    if ms.provider_for_row(row, cfg) != pcfg.owns:
        return False
    if ms.confidence_tier(row, cfg) == "non_poi":
        return False
    if not ms.input_place_name(row):
        return False
    return bool((row.get("capture_lat") or "").strip() and (row.get("capture_lon") or "").strip())


def probe_targets(rows: List[Dict[str, str]], cfg: dict, pcfg: ProviderCfg) -> Targets:
    return [(i, r) for i, r in enumerate(rows) if is_probe_target(r, cfg, pcfg)]


def classify_input(input_name: str, candidates: List[str],
                   sim_token: str, non_token: str) -> Tuple[str, Optional[str]]:
    for c in candidates:
        if ms.exact_equal(input_name, c):
            return input_name, c
    for c in candidates:
        if ms.normalized_equal(input_name, c):
            return sim_token, c
    return non_token, None


def classify_rows(rows: List[Dict[str, str]], cfg: dict, pcfg: ProviderCfg,
                  cand_by_rid: Dict[str, List[str]], in_scope=None) -> Dict[str, int]:
    stats: Counter = Counter()
    for idx, row in enumerate(rows):
        if in_scope is not None and not in_scope(idx, row):
            continue  # leave out-of-scope cells untouched (dataset/only_empty scoping)
        if ms.provider_for_row(row, cfg) != pcfg.owns:
            row[pcfg.column] = pcfg.other_marker
            stats["other_marker"] += 1
            continue
        if ms.confidence_tier(row, cfg) == "non_poi" or not ms.input_place_name(row):
            row[pcfg.column] = ""
            stats["cleared"] += 1
            continue
        value, _matched = classify_input(
            ms.input_place_name(row), cand_by_rid.get(str(idx), []),
            pcfg.sim_token, pcfg.non_token)
        row[pcfg.column] = value
        if value == pcfg.sim_token:
            stats["sim"] += 1
        elif value == pcfg.non_token:
            stats["non"] += 1
        else:
            stats["exact_copied"] += 1
    return stats


def read_csv(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


@contextmanager
def csv_write_lock(path: str):
    """Cross-process lock for the short read/merge/replace commit transaction."""
    # Shared implementation so run saves / overrides use the same protocol.
    from file_ops import file_lock
    with file_lock(path):
        yield


def write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    """Atomic CSV rewrite (temp + replace). Callers should hold ``csv_write_lock``."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".csv", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def backup_csv(path: str) -> str:
    dst = f"{path}.bak-{now_stamp()}"
    with open(path, "rb") as src, open(dst, "wb") as out:
        out.write(src.read())
    return dst


def run_classification(pcfg: ProviderCfg, fetch: FetchFn, csv_path: str,
                       dry_run: bool = False, emit_result: bool = True,
                       dataset: Optional[str] = None, only_empty: bool = False) -> Dict:
    """Full driver: read CSV, fetch candidates for owned rows, classify, write.

    ``fetch`` is the provider-specific candidate source: it takes the target rows
    and returns ``{str(row_index): [candidate names]}``.

    ``dataset``/``only_empty`` scope the run: only rows in ``dataset`` (all if
    None) and — when ``only_empty`` — only rows whose provider GT cell is still
    empty are (re)classified; every other cell is left exactly as-is.
    """
    cfg = ms.load_config()
    fieldnames, rows = read_csv(csv_path)
    if pcfg.column not in fieldnames:
        raise SystemExit(f"CSV has no {pcfg.column} column")

    def in_scope(_idx, row):
        if dataset and (row.get("dataset") or "").strip() != dataset:
            return False
        if only_empty and (row.get(pcfg.column) or "").strip():
            return False
        return True

    targets = [(i, r) for (i, r) in probe_targets(rows, cfg, pcfg) if in_scope(i, r)]
    scope_note = (f" dataset={dataset}" if dataset else "") + (" only_empty" if only_empty else "")
    print(f"[{pcfg.owns}] probe targets: {len(targets)} / total_rows={len(rows)}{scope_note}")
    if dry_run:
        result = {"ok": True, "provider": pcfg.owns, "dry_run": True, "targets": len(targets)}
        if emit_result:
            print("RESULT " + json.dumps(result, ensure_ascii=False))
        return result

    cand_by_rid = fetch(targets)
    print(f"[{pcfg.owns}] candidate rows fetched: {len(cand_by_rid)}")

    # Fetching candidates is slow.  Commit under a lock and re-read the latest
    # CSV inside it, so a concurrent OCR/nearby worker's columns survive.
    with csv_write_lock(csv_path):
        fieldnames, rows = read_csv(csv_path)
        backup = backup_csv(csv_path)
        stats = classify_rows(rows, cfg, pcfg, cand_by_rid, in_scope)
        write_csv(csv_path, fieldnames, rows)
    print(f"[{pcfg.owns}] backup: {backup}")
    print(f"[{pcfg.owns}] wrote {csv_path}")
    print(f"  {pcfg.other_marker}={stats.get('other_marker', 0)} "
          f"exact_copied={stats.get('exact_copied', 0)} "
          f"{pcfg.sim_token}={stats.get('sim', 0)} "
          f"{pcfg.non_token}={stats.get('non', 0)} "
          f"cleared={stats.get('cleared', 0)}")

    result = {
        "ok": True,
        "provider": pcfg.owns,
        "column": pcfg.column,
        "targets": len(targets),
        "backup": backup,
        "counts": {
            pcfg.other_marker: stats.get("other_marker", 0),
            "exact_copied": stats.get("exact_copied", 0),
            pcfg.sim_token: stats.get("sim", 0),
            pcfg.non_token: stats.get("non", 0),
            "cleared": stats.get("cleared", 0),
        },
    }
    if emit_result:
        print("RESULT " + json.dumps(result, ensure_ascii=False))
    return result
