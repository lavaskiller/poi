# Release baselines

Committed threshold files consumed by `tools/release_gate.py score`.

A baseline is **derived from a real, trusted run**, never hand-written with
guessed numbers:

```bash
python3 tools/release_gate.py emit-baseline \
    --run poi-data/generated/runs/<known-good>__vN.json \
    --out eval/baselines/baseline.v1.json
```

Review the emitted floors, then commit the file. Until one is committed the gate
runs in report-only mode (exit 0) so CI stays green.

Each baseline records `generated_from_run`, the split it targets, overall floors
(exact/canonical accuracy, coverage, wrong-leak ceiling, p95 ceiling), per-slice
canonical floors, tolerances, and `slice_min_n`. See `docs/release-gate.md`.
