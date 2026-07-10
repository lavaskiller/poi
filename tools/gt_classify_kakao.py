#!/usr/bin/env python3
"""Classify ``gt_kakao`` by whether ``input_place_name`` is written the Kakao way.

Mirror of ``gt_classify_mapkit.py`` for South Korea rows, but candidates come
from the Kakao Local keyword-search REST API (pure stdlib HTTP — no Swift/macOS).
All classification policy lives in ``gt_classify_common``.

Result values: ``NON_KR`` (non-Korea rows), the verbatim input (exact Kakao
match), ``SIM_KAKAO`` (normalized match), ``NON_KAKAO`` (else), empty (out of
scope).

Auth: set ``KAKAO_REST_API_KEY`` to a Kakao Developers REST API key.

Usage:
  KAKAO_REST_API_KEY=... POI_DATA_DIR=/path python3 tools/gt_classify_kakao.py
  POI_DATA_DIR=/path python3 tools/gt_classify_kakao.py --dry-run   # no key needed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import match_score as ms  # noqa: E402
import gt_classify_common as common  # noqa: E402

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_RADIUS_M = 20000          # Kakao keyword-search max radius
KAKAO_SIZE = 15                 # candidates per page (max 15)
PACE_S = 0.05                   # polite delay between requests
RETRY_WAITS = [1.0, 3.0, 6.0]   # backoff on 429 / transient network error


def _api_key() -> str:
    key = (os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    if not key:
        raise SystemExit("KAKAO_REST_API_KEY is not set (Kakao Developers REST API key required)")
    return key


def kakao_keyword_search(query: str, lat: str, lon: str, key: str) -> List[str]:
    """Return Kakao place_name candidates near (lat,lon) in accuracy order.

    Raises SystemExit on auth failure (401) so a bad key fails the whole job
    rather than silently misclassifying every row as NON_KAKAO. Transient errors
    (429/5xx/network) are retried; if still failing, returns [] for this row.
    """
    params = {
        "query": query,
        "x": lon,        # Kakao expects x=longitude, y=latitude
        "y": lat,
        "radius": KAKAO_RADIUS_M,
        "sort": "accuracy",
        "size": KAKAO_SIZE,
        "page": 1,
    }
    url = KAKAO_KEYWORD_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            docs = data.get("documents") or []
            return [(d.get("place_name") or "").strip() for d in docs if (d.get("place_name") or "").strip()]
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("Kakao API auth failed (401): check KAKAO_REST_API_KEY")
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < len(RETRY_WAITS):
                    sys.stderr.write(f"  kakao {e.code} on {query!r}, backoff {RETRY_WAITS[attempt]}s\n")
                    time.sleep(RETRY_WAITS[attempt])
                    continue
            sys.stderr.write(f"  kakao HTTP {e.code} on {query!r}: giving up (-> no candidates)\n")
            return []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < len(RETRY_WAITS):
                sys.stderr.write(f"  kakao net err on {query!r}: {e}; backoff {RETRY_WAITS[attempt]}s\n")
                time.sleep(RETRY_WAITS[attempt])
                continue
            sys.stderr.write(f"  kakao net err on {query!r}: giving up (-> no candidates)\n")
            return []
    return []


def make_fetch(key: str):
    def fetch(targets) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for n, (idx, row) in enumerate(targets, start=1):
            names = kakao_keyword_search(
                ms.input_place_name(row),
                (row.get("capture_lat") or "").strip(),
                (row.get("capture_lon") or "").strip(),
                key,
            )
            out[str(idx)] = names
            if n % 10 == 0:
                print(f"[kakao_local] {n}/{len(targets)} queried")
            time.sleep(PACE_S)
        return out
    return fetch


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify gt_kakao (NON_KR / verbatim / SIM_KAKAO / NON_KAKAO)")
    ap.add_argument("--csv", default=ms.CSV_PATH)
    ap.add_argument("--dry-run", action="store_true", help="count targets only; no key/API needed")
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--only-empty", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        common.run_classification(common.KAKAO, lambda t: {}, args.csv, dry_run=True,
                                  dataset=args.dataset, only_empty=args.only_empty)
        return 0

    fetch = make_fetch(_api_key())
    common.run_classification(common.KAKAO, fetch, args.csv, dry_run=False,
                              dataset=args.dataset, only_empty=args.only_empty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
