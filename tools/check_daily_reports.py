#!/usr/bin/env python3
"""Verify that docs/reports/daily contains one report for each calendar day.

The check deliberately validates filenames and the date heading only. A day with
no repository activity must still have a report stating that fact; a missing file
is never inferred to mean "no work".
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

DATE_RE = re.compile(r"^# Daily report — (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Check daily-report continuity")
    parser.add_argument("--from", dest="start", required=True, type=parse_date,
                        help="first required date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--through", dest="end", type=parse_date, default=dt.date.today(),
                        help="last required date, inclusive (default: today)")
    parser.add_argument("--dir", default="docs/reports/daily",
                        help="daily report directory relative to repository root")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--through must be on or after --from")

    directory = Path(args.dir)
    missing: list[str] = []
    invalid: list[str] = []
    current = args.start
    while current <= args.end:
        stamp = current.isoformat()
        path = directory / f"{stamp}.md"
        if not path.is_file():
            missing.append(stamp)
        else:
            match = DATE_RE.search(path.read_text(encoding="utf-8"))
            if not match or match.group(1) != stamp:
                invalid.append(f"{path}: expected heading '# Daily report — {stamp}'")
        current += dt.timedelta(days=1)

    if missing or invalid:
        if missing:
            print("Missing daily reports: " + ", ".join(missing), file=sys.stderr)
        for issue in invalid:
            print("Invalid daily report: " + issue, file=sys.stderr)
        return 1
    print(f"Daily reports complete: {args.start.isoformat()} through {args.end.isoformat()} ({args.end.toordinal() - args.start.toordinal() + 1} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
