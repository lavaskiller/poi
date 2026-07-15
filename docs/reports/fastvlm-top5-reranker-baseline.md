# FastVLM Top-5 POI Reranker Baseline

## Summary

FastVLM-0.5B Stage 3 was evaluated as a constrained visual reranker over the distance-sorted MapKit Top-5 candidates. The run covered all 166 currently eligible evaluation cases.

- Nearest MapKit baseline: **63/166 (38.0%)**
- FastVLM reranker with nearest fallback: **64/166 (38.6%)**
- Net change: **+1 correct case (+0.6 percentage points)**
- Inference errors: **0**
- Cases with no candidates: **11**

The initial visual reranker is operational and reproducible, but it does not materially outperform nearest-neighbor selection. Candidate retrieval coverage remains the principal bottleneck.

## Algorithm

For each eligible case:

1. Keep up to five MapKit candidates in distance order.
2. Pass only the image and candidate names to FastVLM-0.5B Stage 3.
3. Ask for one candidate number or `UNKNOWN`.
4. Accept a unique valid candidate number. Because the model often ignores number-only formatting, also accept a response containing exactly one normalized candidate name.
5. Fall back to the nearest candidate for `UNKNOWN`, ambiguous/unparseable output, missing images, or inference errors.
6. Return an empty string when no candidate exists.

Generation is deterministic (`do_sample=False`, one beam). The model is loaded once and inference results are cached in JSONL. Ground truth is not supplied during inference and is used only by the existing scoring function after predictions are complete.

## Overall result

| Algorithm | Correct | Eligible | Accuracy |
|---|---:|---:|---:|
| Nearest MapKit | 63 | 166 | 38.0% |
| FastVLM Top-5 reranker | 64 | 166 | 38.6% |
| Difference | +1 | — | +0.6 pp |

## Results by dataset

| Dataset | N | Nearest | FastVLM | Change |
|---|---:|---:|---:|---:|
| `vancouver` | 7 | 2 (28.6%) | 2 (28.6%) | 0 |
| `linkedspaces` | 73 | 26 (35.6%) | 27 (37.0%) | +1 |
| `poi-dataset-20260708` | 86 | 35 (40.7%) | 35 (40.7%) | 0 |

## Decision distribution

| Decision | Count |
|---|---:|
| VLM agreed with nearest | 87 |
| Nearest fallback | 48 |
| VLM overrode nearest | 20 |
| No candidates / abstain | 11 |

Among the 20 overrides:

- Beneficial overrides: **4**
- Harmful overrides: **3**
- Wrong-to-different-wrong overrides: **13**
- Net override gain: **+1**

### Beneficial overrides

| Photo | Nearest | FastVLM / GT |
|---|---|---|
| `...IMG_9783.jpg` | Tong Beauty Supply | Da Vien Coffee |
| `...IMG_6106.jpg` | Libertine Brewing Company | Libertine Coffee Bar |
| `...IMG_7939.jpg` | ARC Abatement | Empty Quiver Archery |
| `...IMG_7952.jpg` | ARC Abatement | Empty Quiver Archery |

### Harmful overrides

| Photo | Nearest / GT | FastVLM |
|---|---|---|
| `...IMG_2274.jpg` | Mai's Kitchen | Taste of Bangla |
| `...IMG_3940.jpg` | Junction Park | Vedder Painting |
| `...IMG_9349.jpg` | Topgolf | Topgolf - San Jose |

The third harmful override also illustrates canonical-name sensitivity in exact matching: the more specific candidate `Topgolf - San Jose` is scored wrong against the GT `Topgolf`.

## Runtime observations

Across the 155 cases with candidates, recorded per-case latency had an approximate median of **1.87 seconds** and p95 of **2.16 seconds** on MPS. The mean (**1.38 seconds**) is affected by cached entries and resumed execution, so it should not be treated as a clean end-to-end benchmark. Model startup cost is paid once.

A non-fatal `urllib3` warning was emitted because the environment uses LibreSSL 2.8.3; inference completed with zero errors.

## Artifacts

- Runner: `tools/run_fastvlm_baseline.py`
- Evaluation run: `poi-data/generated/runs/fastvlm-top5-reranker__v1.json`
- Prediction details: `poi-data/fastvlm_results.tsv`
- Resumable cache: `poi-data/generated/fastvlm_top5_cache.jsonl`

Run command:

```bash
PYTHONPATH="$PWD/poi-data/tools/ml-fastvlm" \
  poi-data/tools/fastvlm-venv/bin/python \
  tools/run_fastvlm_baseline.py
```

## Validation

- All 166 eligible cases completed.
- Existing exact scorer produced the final metrics.
- Inference errors: 0.
- Parser checks covered numeric selection, unique candidate-name selection, `UNKNOWN`, ambiguous/multiple selections, empty responses, and out-of-range numbers.
- `python3 -m py_compile tools/run_fastvlm_baseline.py` passed.
- `git diff --check` passed.

## Interpretation and next priority

FastVLM can recover some cases where the closest POI is not the photographed POI, but the current unconstrained-confidence override policy also damages nearly as many correct nearest predictions. Moreover, reranking cannot recover the 11 cases with no candidates or cases whose GT is absent from Top-5.

Recommended next steps:

1. **Improve candidate retrieval first:** expand or diversify MapKit retrieval using OCR/VLM-derived search terms and wider/local-search queries.
2. **Make overrides more conservative:** require agreement between independent visual prompts or corroboration from OCR before replacing rank 1.
3. **Evaluate on candidate-covered cases separately:** measure selection quality independently from retrieval misses.
4. **Handle canonical aliases:** retain exact scoring for comparability, but separately inspect semantically equivalent provider names such as `Topgolf` versus `Topgolf - San Jose`.
