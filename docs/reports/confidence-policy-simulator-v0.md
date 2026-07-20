# MVP 1 Confidence Policy Simulator v0

**Status:** implemented as a conservative, snapshot-specific policy.  This is an action policy, **not** a calibrated probability model.

## What shipped

- [`examples/poi_confidence_policy.py`](../../examples/poi_confidence_policy.py): reusable `AUTO_PICK` / `SHOW_PICKER` / `NONE` decision module with structured reason codes.
- [`tools/simulate_confidence_policy.py`](../../tools/simulate_confidence_policy.py): post-hoc, case-level simulator and JSON report writer.
- [`tests/test_confidence_policy.py`](../../tests/test_confidence_policy.py): policy gate coverage.

The policy uses the existing category-aware weighted MapKit resolver.  It does not expose GT to the policy; GT is used only after the decision to calculate metrics.

## v0 decision contract

| Action | Product behavior | Gate |
| --- | --- | --- |
| `AUTO_PICK` | Preselect one POI, retain change/undo | Valid direct-tap provider ID; **or** an unambiguous weighted result that agrees with the physically nearest usable result and has either strong OCR name evidence or a large weighted margin (60m). A one-candidate result needs strong OCR support. |
| `SHOW_PICKER` | Show Top-5 initially; allow expansion to the weighted resolver limit (20) | Usable candidates exist, but the auto gate is not met. |
| `NONE` | Do not guess; offer manual search, map selection, or place-none | No usable candidate after infrastructure filtering. |

Strong OCR support means the full normalized candidate name is visible, or every meaningful non-generic name token is present. A generic category word such as `Cafe` alone is deliberately not support.

FastVLM is recorded as a corroboration/conflict signal only. Its nearest fallback, agreement with a fallback, or VLM-only result cannot open the auto gate.

## Run the simulator

```bash
python3 tools/simulate_confidence_policy.py \
  --output poi-data/generated/confidence-policy-v0.json
```

Optional side inputs are detected at the normal private data root when present:

- `ls_ocr_text.tsv` with `photo`, `ocr_text`
- `fastvlm_results.tsv` with `photo`, `prediction`, `decision`

They can instead be supplied explicitly with `--ocr-tsv` and `--vlm-tsv`. The output records the evaluation-cohort SHA-256 and data-snapshot SHA-256, aggregate metrics, and case-level action/reason/candidate audit data. It remains under ignored `poi-data/` because it can contain private photo identifiers and labels.

## Initial private-snapshot observation

On the current 166-case eligible MapKit cohort, the v0 rules produced:

| Metric | Result |
| --- | ---: |
| Auto coverage | 2 / 166 (1.2%) |
| Auto precision | 2 / 2 (100.0%) |
| Wrong-auto rate | 0 / 166 (0.0%) |
| Picker rate | 146 / 166 (88.0%) |
| Picker recall@5, among picker cases | 74 / 146 (50.7%) |
| No-result rate | 18 / 166 (10.8%) |
| Nearest accuracy, same cohort | 63 / 166 (38.0%) |

This is **not** evidence that production auto precision is 100%: two auto cases are far too few to estimate reliability. It is evidence that the initial policy is intentionally conservative and that retrieval remains the bottleneck. The 50.7% picker recall is conditional on the policy's picker cases; it must not be compared directly to the all-case Top-5 retrieval coverage (76 / 166, 45.8%) without noting that denominator difference.

## Before widening AUTO_PICK

1. Recollect rich candidate lists beyond shallow historical top-3 snapshots.
2. Evaluate every proposed threshold on a held-out cohort, not the tuning snapshot.
3. Set an explicit minimum auto sample size and allowed wrong-auto budget.
4. Audit the full case report, especially all auto decisions and picker cases with GT absent.
5. Keep direct tap as a user-intent action, separately measured from inference automation.
