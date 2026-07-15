# MapKit nearest vs weighted — 최신 데이터 v2 동일 조건 비교

## 결론

최신 UI 데이터 362행을 로드한 상태에서 두 알고리즘을 UI의 동일한 실행 조건으로 다시 실행했다. 실제 채점 가능한 MapKit canonical GT 표본은 166건이며, 두 알고리즘의 전체 정확도는 모두 **63/166, 37.95%**였다. weighted는 정답 수를 바꾸지 않으면서 기반시설성 오답 7건을 추가로 기권했다.

## UI 실행 실패 원인과 수정

실패는 `baseline_nearest.py`의 `predict()` 로직 때문이 아니었다.

1. 2026-07-14 15:58에 시작된 서버는 다중 데이터셋 scope 지원 코드가 반영되기 전 모듈을 메모리에 유지하고 있었다. UI가 보내는 scope `linkedspaces,poi-dataset-20260708,union-city,vancouver`를 하나의 데이터셋 이름으로 해석해 다음 422를 반환했다.
   - `no eligible eval cases for scope ...`
2. 서버 재시작 후에는 최신 run metadata 코드가 선택적 후보 파일 `kakao_local_candidates.jsonl`까지 무조건 해시하려 해 500이 발생했다.
   - `[Errno 2] No such file or directory: .../kakao_local_candidates.jsonl`
3. `tools/run_algorithm.py::data_snapshot_sha256()`가 없는 선택적 provider 파일을 `<missing>` 상태로 snapshot identity에 포함하도록 수정했다. 파일 부재는 기록하되 알고리즘 실행을 중단하지 않는다.
4. 누락 파일 상태의 결정성과, 이후 파일이 생겼을 때 hash가 달라지는지를 확인하는 회귀 테스트를 추가했다.

수정 후 동일 `/api/run` 요청은 HTTP 200으로 완료됐다.

## 최신 데이터 362행과 평가 표본 166건의 관계

UI의 362행 전체를 scope에 포함했지만, run harness는 MapKit canonical GT로 실제 채점 가능한 행만 평가한다.

| 구분 | 행 수 |
|---|---:|
| UI 전체 행 | 362 |
| MapKit canonical GT 평가 대상 | 166 |
| non-canonical / 미해결 GT | 166 |
| Kakao holdout | 26 |
| `non_poi` 제외 | 4 |

따라서 166은 오래된 CSV를 사용해서 생긴 수량이 아니라, **최신 362행 snapshot에 현재 채점 eligibility를 적용한 결과**다. UI의 “GT label 354행”은 confidence/label 존재 여부를 넓게 집계한 coverage 지표이고, provider-canonical scoring eligibility와는 다르다.

평가 대상의 데이터셋별 구성:

- `linkedspaces`: 73
- `poi-dataset-20260708`: 86
- `vancouver`: 7
- `union-city`: 0 (`non_poi` 4, 나머지 non-canonical)

## v2 실행 조건

두 run에 다음 조건을 동일하게 적용했다.

- 데이터 snapshot: 최신 `poi-data/eval_set_reconciled.csv` 362행
- UI scope: `linkedspaces,poi-dataset-20260708,union-city,vancouver`
- mode: `exact`
- params: `nearby_candidates`
- candidate limit: `5` (기존 baseline v1과 동일)
- candidate source: `poi-data/generated/mapkit_candidates.jsonl`
- evaluation cohort SHA-256: `488056acc6d4a1c8b73a1ea82627603adeebc62430a9d96a7d4f0603e81afc5c`
- data snapshot SHA-256: `65fe1974d6954d4c41efafe07e17433886e3633cd1096782a0a16179fa7e0d41`

생성된 결과:

- nearest: `poi-data/generated/runs/baseline-nearest__v2.json`
- weighted: `poi-data/generated/runs/weighted-same-dataset__v2.json`

`baseline-nearest`는 저장소에 있던 v1에서 automatic next version으로 v2가 생성됐다. weighted는 앞선 동일 데이터셋 비교에서 사용한 논리 이름 `weighted-same-dataset`의 v2로 저장했다. 해당 weighted v1은 임시 비교 디렉터리에만 생성됐고 현재 persisted runs 디렉터리에는 없으므로, 이번에는 UI의 명시적 `v2` 저장 모드로 v2를 만들었다.

## 결과

| 지표 | nearest v2 | weighted v2 | 차이 |
|---|---:|---:|---:|
| 평가 대상 | 166 | 166 | 0 |
| 정답 | 63 | 63 | 0 |
| 전체 정확도 | 37.95% | 37.95% | 0.00%p |
| 기권 | 11 | 18 | +7 |
| 오류 | 0 | 0 | 0 |
| 비기권 정답률 | 40.65% | 42.57% | +1.92%p |

### 데이터셋별

| 데이터셋 | 대상 | nearest | weighted |
|---|---:|---:|---:|
| linkedspaces | 73 | 26 / 35.62% | 26 / 35.62% |
| poi-dataset-20260708 | 86 | 35 / 40.70% | 35 / 40.70% |
| vancouver | 7 | 2 / 28.57% | 2 / 28.57% |

### 정답 전이

- 두 알고리즘 모두 정답: 63
- nearest만 정답: 0
- weighted만 정답: 0
- 두 알고리즘 모두 오답: 103

두 run의 `(dataset, photo, GT)` 순서 166건이 완전히 같고, evaluation cohort hash와 data snapshot hash도 동일함을 assert했다.

## 달라진 예측

166건 중 9건에서 예측 문자열이 달랐지만 정답 여부 전이는 없었다.

- 7건: nearest의 `Restroom`/`Washroom`을 weighted가 제거하고 기권
- 1건: `Aiso Street Parking Garage` → `Metro Bike Share` (GT `Rice & Nori`, 둘 다 오답)
- 1건: `Gate G8` → `Tomokazu` (GT `San Francisco International Airport`, 둘 다 오답)

weighted는 명백한 기반시설 예측을 줄였지만, 현재 후보군에 실제 목적지 후보가 없어 전체 정확도 상승으로 이어지지는 않았다.

## 중요한 제한

현재 `mapkit_candidates.jsonl`은 537행의 legacy snapshot이며 다음 rich metadata가 모두 비어 있다.

- category: 0/537
- provider place ID: 0/537
- 후보 좌표: 0/537

그러므로 이번 결과는 최신 **평가 CSV 362행 및 UI eligibility**를 반영한 공정한 v2 비교이지만, category-aware weighted ranking의 완전한 효과를 측정한 결과는 아니다. category 보정의 성능을 평가하려면 362행에 대한 rich MapKit 후보 재수집을 완료한 뒤 두 알고리즘을 같은 새 snapshot으로 다시 실행해야 한다.

## 검증

- `/api/run` baseline v2: HTTP 200
- `/api/run` weighted v2: HTTP 200
- `python3 -m unittest discover -s tests -v`: 13개 테스트 통과
- 두 run의 scope, mode, params, candidate limit, cohort hash, snapshot hash 및 case key 동일성 확인
