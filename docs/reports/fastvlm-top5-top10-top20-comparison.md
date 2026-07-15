# FastVLM Candidate-Set Size Comparison

## Summary

FastVLM-0.5B Stage 3 was run over the same 166 eligible rows with MapKit candidate limits of 5, 10, and 20. Increasing the candidate limit reduced accuracy.

| Algorithm | Correct | Accuracy | Change vs nearest |
|---|---:|---:|---:|
| Nearest MapKit | 63/166 | 38.0% | — |
| FastVLM Top-5 | 64/166 | 38.6% | +1 |
| FastVLM Top-10 | 59/166 | 35.5% | -4 |
| FastVLM Top-20 requested | 49/166 | 29.5% | -14 |

Top-5 remains the best tested FastVLM configuration.

## Important retrieval limitation

The requested limits do not mean every row had that many candidates. Candidate-list lengths in the current input were:

| Requested limit | Candidate-list length distribution |
|---|---|
| 5 | 0: 11 rows; 1: 86; 3: 45; 5: 24 |
| 10 | 0: 11; 1: 86; 3: 45; 6: 6; 9: 3; 10: 15 |
| 20 | 0: 11; 1: 86; 3: 45; 6: 6; 9: 3; 15: 15 |

The current candidate source contains at most 15 candidates for these eligible rows. Therefore, the “Top-20” run is operationally a **use-up-to-15-candidates run**, not a true 20-candidate evaluation.

More importantly, provider-canonical GT coverage was unchanged:

| Candidate limit | Rows containing exact GT |
|---|---:|
| Top-5 | 76/166 (45.8%) |
| Top-10 | 76/166 (45.8%) |
| Top-20 requested | 76/166 (45.8%) |

No GT appeared only at ranks 6–20. The expanded candidates provided no new exact-match opportunity and acted only as distractors in this dataset snapshot.

## Reranker behavior

| Decision | Top-5 | Top-10 | Top-20 requested |
|---|---:|---:|---:|
| VLM agreed with nearest | 87 | 90 | 80 |
| Nearest fallback | 48 | 40 | 40 |
| VLM override | 20 | 25 | 35 |
| No candidates | 11 | 11 | 11 |

Override quality relative to nearest:

| Override outcome | Top-5 | Top-10 | Top-20 requested |
|---|---:|---:|---:|
| Wrong → correct | 4 | 4 | 4 |
| Correct → wrong | 3 | 8 | 18 |
| Wrong → different wrong | 13 | 13 | 13 |
| Net effect | +1 | -4 | -14 |

The number of beneficial overrides stayed fixed at four, while harmful overrides rose from 3 to 8 and then 18.

## Pairwise changes

- Top-5 → Top-10: 5 row predictions changed, with 0 gains and 5 losses.
- Top-10 → Top-20 requested: 10 row predictions changed, with 0 gains and 10 losses.
- Top-5 → Top-20 requested: 15 row predictions changed, with 0 gains and 15 losses.

All losses were concentrated in repeated evaluation rows for three unique Liberty Burger photos:

- With Top-10, one photo changed from the correct `Liberty Burger` to `Merry Piglets Tex-Mex`; that photo occurs in five evaluated rows.
- With the larger candidate list, two additional photos changed from `Liberty Burger` to `Mostly Fun`; each occurs in five evaluated rows.

Only 24 rows, representing seven unique `(dataset, photo)` identities, had more than five candidates. The official metric is row-weighted, so repeated rows correctly contribute repeatedly under the current evaluation protocol, but the concentration should be considered when interpreting the size of the drop.

## Dataset results

| Dataset | N | Top-5 | Top-10 | Top-20 requested |
|---|---:|---:|---:|---:|
| `vancouver` | 7 | 2 (28.6%) | 2 (28.6%) | 2 (28.6%) |
| `linkedspaces` | 73 | 27 (37.0%) | 22 (30.1%) | 12 (16.4%) |
| `poi-dataset-20260708` | 86 | 35 (40.7%) | 35 (40.7%) | 35 (40.7%) |

Only `linkedspaces` changed because all rows with more than five candidates belong to that dataset.

## Conclusion

Expanding the candidate set does not help with the current retrieval snapshot. Exact GT coverage remains fixed at 76/166, while extra candidates increase FastVLM confusion and harmful overrides. Top-5 should remain the visual baseline.

A larger candidate limit should be retested only after retrieval is improved enough to place additional GTs at ranks 6–20. At that point, a hierarchical strategy may be preferable to presenting 20 flat choices to the 0.5B model—for example, score candidates in groups of five and then compare group winners.

## Artifacts

- Top-5 run: `poi-data/generated/runs/fastvlm-top5-reranker__v1.json`
- Top-10 run: `poi-data/generated/runs/fastvlm-top10-reranker__v1.json`
- Top-20 requested run: `poi-data/generated/runs/fastvlm-top20-reranker__v1.json`
- Top-10 details: `poi-data/fastvlm_top10_results.tsv`
- Top-20 details: `poi-data/fastvlm_top20_results.tsv`
- Top-10 cache: `poi-data/generated/fastvlm_top10_cache.jsonl`
- Top-20 cache: `poi-data/generated/fastvlm_top20_cache.jsonl`

Both new runs completed all 166 eligible rows with zero inference errors.
