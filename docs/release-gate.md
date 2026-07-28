# Frozen split + release gate

Turns an eval run into a *trustworthy release decision* instead of a single
leaderboard number. Two pieces:

- `tools/eval_split.py` — a frozen, group-aware train/validation/**test** split.
- `tools/release_gate.py` — a scorecard on the sealed test split, checked
  against a committed baseline. Non-zero exit blocks a merge in CI.

## Why group-aware

The dataset has the classic leakage traps: the same place shot repeatedly, a
burst of consecutive photos, the same user re-walking a route. If those rows
land on both sides of the split, "improvements" can be the model memorizing a
place rather than generalizing.

The split assigns by **group**, never by individual row. The group key is
`dataset | username | geocell@3dp(lat,lon)` (~110 m cell). An entire group is
hashed to one split, so a place/session can never straddle train and test.

## Why a policy, not a checked-in id list

Photo filenames and capture GPS are private (the whole `poi-data/` tree is
gitignored for that reason). Committing a per-photo split table would leak them.

Instead we freeze a **policy** — salt, ratios, group definition, eligibility
rule, and the source-CSV SHA-256 — in `eval/splits/split.v1.policy.json`.
Membership is a pure deterministic function of `(csv, policy)`, so pinning the
policy + CSV hash freezes the exact split without exposing any id. It
re-materializes identically anywhere.

```bash
python3 tools/eval_split.py freeze        # (re)write the tracked policy
python3 tools/eval_split.py verify        # re-derive; assert no drift + no straddle
python3 tools/eval_split.py materialize --out poi-data/generated/splits/split.v1.json
```

`verify` fails (exit 1) if any group spans splits, the per-split counts drift
from the committed policy, or the source CSV changed since freezing.

## The scorecard

`release_gate.py score` restricts a run to the frozen **test** split and reports:

| metric | meaning |
|---|---|
| `accuracy_exact` / `accuracy_canonical` | identification accuracy (strict / alias-aware) |
| `coverage` | fraction the selector actually answers (1 − abstention) |
| `wrong_leak_rate` | answered-**and**-wrong = a wrong POI shown to a user |
| `p95_latency_ms` | tail latency on the host |
| per-slice `accuracy_canonical` | dataset / category / OCR / candidate-count / country |

Promotion is **not** accuracy alone. A headline win that raises `wrong_leak_rate`,
drops `coverage`, or regresses a slice below its floor fails the gate.

## Baseline workflow

The baseline is **not** committed with invented numbers. Derive it from a
known-good run (run JSONs live under the gitignored `poi-data/generated/runs/`):

```bash
# 1. produce a baseline from a run you trust
python3 tools/release_gate.py emit-baseline \
    --run poi-data/generated/runs/mapkit-baseline-v2__v7.json \
    --out eval/baselines/baseline.v1.json

# 2. review, then commit eval/baselines/baseline.v1.json

# 3. every later run is gated against it
python3 tools/release_gate.py score \
    --run poi-data/generated/runs/<candidate>__vN.json
```

Without a baseline file the gate degrades to **report-only** (exit 0), so CI
stays green until a baseline is intentionally committed. Tolerances
(`accuracy_exact` ±0.02, `accuracy_canonical` ±0.02, slice ±0.05) and
`slice_min_n` (default 5, so tiny slices don't fail on noise) live in the
baseline file and are overridable.
