# Reports

## Daily reports

Daily reports are the project activity record. There must be one file for every
calendar day from the first report through the current day, including days with
no committed activity.

- [Daily report index](daily/README.md)
- Continuity check:

  ```bash
  python3 tools/check_daily_reports.py --from 2026-07-09
  ```

  The command defaults to the local calendar date for `--through`. In CI or a
  historical review, pass `--through YYYY-MM-DD` explicitly.

## Report retention

`docs/reports/` contains the active index, daily record, and the current
[confidence-policy note](confidence-policy-simulator-v0.md). Superseded
snapshot experiments, duplicate translations, plans, and generated exploration
artifacts are deleted rather than retained in the working tree. Use Git history
to recover a prior committed document when genuinely needed.

For current product behavior, use the [API contract](../API.md), [functional
specification](../functional-spec.md), and [project README](../../README.md).
