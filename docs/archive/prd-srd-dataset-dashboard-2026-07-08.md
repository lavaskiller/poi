# POI 평가 도구 — 제품/시스템 명세

> 상태: draft v0.4 · 2026-07-08  
> 대상: Bloggo POI 식별 개선 / KS2-32, KS2-34  
> 기준 구현: `mvp-eval-ui.html`, `dataset-overview.html`, `server.py`, `dashboard_config.json`, `eval_set_reconciled.csv`

---

## 개요

이 문서는 Bloggo의 POI 식별 성능을 평가하기 위한 로컬 도구의 제품/시스템 명세다. 평가의 원천 기준은 사용자가 실제로 최종 선택한 장소이며, 매칭 기준명은 지역별 provider에 맞춘다. 한국 외 지역은 MapKit 명칭을 기준으로, 한국은 Kakao Local 명칭을 기준으로 평가한다.

이 도구가 분리해서 측정해야 하는 핵심 문제는 두 가지다.

| 구분 | 질문 | 개선 방향 |
|---|---|---|
| 후보 검색 | 지역별 기준 provider의 정답 장소가 주변 POI 후보 리스트 안에 들어오는가? | 한국 외: MapKit, 한국: Kakao Local 기준의 provider/검색 반경/후보 생성 로직 개선 |
| 후보 선택 | 정답이 후보 안에 있을 때 앱/알고리즘이 올바른 후보를 고르는가? | OCR, VLM, LLM, 시간, 카테고리, 텍스트 신호를 이용한 ranking/selection 개선 |

두 문제를 분리하지 않으면 개선 방향을 잘못 잡는다. 후보 리스트에 정답이 없으면 OCR/LLM 기반 선택 알고리즘으로는 해결할 수 없고, 반대로 후보 안에 정답이 있는데 가까운 다른 장소를 고르는 경우는 검색 API 교체보다 선택 신호 개선이 우선이다.

따라서 본 도구의 핵심 역할은 `검색 실패`와 `선택 실패`를 구분하고, raw/normalized 매칭 기준에서 각각의 지표를 재현 가능하게 산출하는 것이다.

---

## 1. 배경

현재 Bloggo의 POI 선택은 대략 이런 흐름이다.

1. 사진 또는 탭 좌표가 있다.
2. 좌표 주변 POI를 검색한다.
3. 가까운 순서의 후보 리스트를 만든다.
4. 사용자가 최종 장소를 고른다.

문제는 지금까지 성능을 볼 때 “대충 맞는 것 같다/아닌 것 같다”에 가까웠다는 점이다.

- 후보 리스트를 눈으로 확인했다.
- 이름이 조금 다르면 수동으로 맞다고 판단했다.
- 어떤 행은 포함하고 어떤 행은 제외했는지 매번 달랐다.
- raw 이름 기준으로는 실패인데, 실제로는 `®`, `&`, 지점명, 표기 차이 때문에 실패처럼 보이는 케이스가 있었다.

그래서 개선을 해도 “정말 좋아졌는지” 말하기 어려웠다.

이 도구는 그 상태를 끝내기 위한 것이다.

---

## 2. 제품 목표

### 2.1 1차 목표

현재 앱의 지역별 POI 후보/선택 성능을 신뢰 가능한 숫자로 만든다. 한국 외 데이터는 MapKit 기준으로, 한국 데이터는 Kakao Local 기준으로 평가한다.

핵심 지표는 다음과 같다.

| 지표 | 의미 | 앱 UX에서의 의미 |
|---|---|---|
| rank-1 | 정답 장소가 첫 번째 후보 | 사용자가 거의 노력하지 않아도 맞음 |
| top-3 | 정답 장소가 상위 3개 안 | 조금만 보면 고를 수 있음 |
| top-5 | 정답 장소가 상위 5개 안 | 리스트 안에서 찾을 가능성 있음 |
| top-10 | 정답 장소가 상위 10개 안 | 후보 검색은 성공했지만 UI/선택 알고리즘 보조가 필요함 |
| MISS | 정답 장소가 후보 안에 없음 | 후보 검색 자체 실패, 수동 검색 필요 |
| within-Xm count | 사진 좌표 기준 X미터 안에 있는 후보 수 | 주변 POI 밀도. 선택 난이도/혼잡도 |
| within-Xm hit | provider 기준 정답 장소가 X미터 안에 있는지 | 거리 기반 retrieval의 물리적 가능성 |

### 2.2 2차 목표

1차 목표가 “정답 장소가 후보 리스트 안에 들어오는가”를 확인하는 것이라면, 2차 목표는 **그 후보 리스트 안에서 어떤 장소를 선택할지 알고리즘으로 시도하고 비교하는 것**이다.

즉, 같은 eval set과 같은 후보 리스트를 두고, 선택 전략만 바꿨을 때 rank-1 정확도와 selection failure가 얼마나 개선되는지 본다.

비교 대상 예:

- nearest-only: 가장 가까운 후보를 선택
- OCR 텍스트 기반 선택
- OCR + LLM 기반 선택
- FastVLM / VLM caption 기반 선택
- OCR/VLM/시간/카테고리 신호를 조합한 ranking

후보 API 교체, 예를 들어 MapKit vs Google Places vs Kakao Local 비교는 별도 retrieval/provider 평가로 본다. 이는 “후보 안에서 무엇을 고를지”가 아니라 “정답이 후보 안에 들어오게 할 수 있는지”의 문제다.

### 2.3 하지 않을 것

이 도구는 POI 라벨 편집기가 아니다.

- UI에서 GT를 직접 수정하지 않는다.
- 사용자가 고른 원본 장소명을 잃어버리지 않는다. 단, 평가용 기준명은 지역별 provider 명칭으로 별도 보관한다.
- 숫자를 좋게 보이게 하려고 애매한 케이스를 조용히 제외하지 않는다.
- mock 수치를 실제 결과처럼 말하지 않는다.

---

## 3. 핵심 원칙

### 3.1 사용자가 고른 장소가 기준이다

평가의 원천 기준은 사용자의 최종 선택이다. 다만 실제 후보 검색/랭킹 평가는 지역별 provider의 장소명 체계에 맞춰 수행한다.

```text
user_selected_place_name = 사용자가 실제로 고른 원본 장소명
eval_place_name         = 평가에 사용할 provider 기준 장소명
```

`user_selected_place_name`은 보존한다. 이 값은 사용자가 어떤 장소를 의도했는지에 대한 원본 기록이다.

`eval_place_name`은 평가용 canonical name이다. 지역별 기준 provider는 다음과 같다.

| 지역 | 평가 기준 provider | 비고 |
|---|---|---|
| 한국 외 | MapKit | 현재 앱의 기본 후보 체계와 맞춤 |
| 한국 | Kakao Local | 한국 POI 품질/표기 기준을 Kakao에 맞춤 |

즉, 사용자가 고른 장소를 먼저 확정하고, 그 장소에 대응되는 provider 기준명을 별도 컬럼으로 관리한다. 원본 사용자 선택값을 덮어쓰지 않고, 평가 시에는 `eval_place_name`과 후보명을 비교한다.

### 3.2 검색과 선택을 분리한다

실패는 최소 두 종류다.

| 실패 | 정의 | 고치는 방법 |
|---|---|---|
| 검색 실패 | provider 기준 정답 장소가 후보 리스트에 없음 | 후보 API, 검색 반경, 지역별 provider 개선 |
| 선택 실패 | provider 기준 정답은 후보에 있는데 다른 후보를 고름 | OCR/VLM/LLM/시간/카테고리 신호 개선 |

이 구분이 이 도구의 가장 중요한 판단 축이다.

### 3.3 raw와 normalized를 같이 본다

raw exact match만 보면 이름 표기 차이 때문에 실패가 부풀려진다.

예:

```text
Din Tai Fung®  vs  Din Tai Fung
Joe & The Juice  vs  Joe and the Juice
Ladurée  vs  Laduree
```

그래서 모든 평가는 두 층으로 봐야 한다.

| 모드 | 의미 |
|---|---|
| raw | provider 기준 원문 이름 기준 매칭 |
| normalized | 동일한 정규화 규칙을 적용한 토큰 기반 매칭 |

normalized는 숫자를 좋게 만들기 위한 장치가 아니라, **가짜 MISS를 분리하기 위한 장치**다.

### 3.4 분모를 숨기지 않는다

모든 성능 수치는 다음과 함께 표시한다.

- n
- 제외된 행 수와 이유
- scope
- raw/norm 기준
- user_selected만인지, hand-labeled 포함인지

예:

```text
실사용자 GT n=190 · provider 기준: 한국 외 MapKit / 한국 Kakao · no_gt 4 · non_poi 6 · 기준: normalized
```

### 3.5 모르는 값은 보이게 한다

새 dataset, 새 confidence 값, 새 CSV 컬럼이 config에 없으면 화면에서 경고한다.

이 원칙은 이미 `/api/overview`와 `dataset-overview.html`에 구현되어 있다.

---

## 4. 현재 데이터셋

### 4.1 파일

```text
eval_set_reconciled.csv   # 평가셋 본체
dashboard_config.json     # 라벨/색/역할/rollup/config
```

### 4.2 현재 수치

현재 `eval_set_reconciled.csv` 기준:

| 항목 | 값 |
|---|---:|
| 전체 행 | 280 |
| 사진 있는 행 | 268 |
| canonical user_selected | 233 |
| 국가 수 | 8 |
| config warning | 0 |

Dataset 구성:

| dataset | count | 성격 |
|---|---:|---|
| `linkedspaces` | 228 | 실사용자 방문 export |
| `union-city` | 33 | 개인 블로그/코너케이스 |
| `vancouver` | 19 | 개인 블로그/코너케이스 |

신뢰 등급 rollup:

| canonical tier | 현재 의미 |
|---|---|
| `user_selected` | 실제 사용자 선택 기반. headline metric의 핵심 분모 |
| `confident` | 사람이 붙인 라벨 중 비교적 신뢰 가능한 케이스. 회귀/QA용 |
| `non_poi` | POI가 아닌 케이스. venue match와 별도 취급 |
| `unresolved` | 애매하거나 미해결. headline metric 제외 |

---

## 5. 도구의 화면 구조

목업 `mvp-eval-ui.html`은 최종 도구의 정보 구조를 네 탭으로 잡고 있다.

```text
① 개요
② 평가 실행
③ 평가 결과
④ 데이터셋 추가
```

이 순서는 사용 흐름이기도 하다.

1. 지금 데이터가 어떤 상태인지 본다.
2. 새 방법을 같은 입력 계약으로 돌린다.
3. baseline과 비교하고 실패 이유를 본다.
4. 부족하면 새 데이터를 붙인다.

---

## 6. ① 개요

### 6.1 목적

“이 eval set을 믿고 봐도 되는가?”를 먼저 확인하는 화면이다.

성능 숫자를 보기 전에 다음을 확인해야 한다.

- 어떤 출처의 데이터인가?
- 실제 사용자 선택은 몇 개인가?
- 손라벨/비POI/미해결은 얼마나 섞였나?
- 사진/좌표/OCR/후보검색 신호가 얼마나 채워졌나?
- 새 컬럼이나 새 값이 config에서 빠져 있지는 않은가?

### 6.2 구현 상태

`dataset-overview.html`은 이 기능을 live로 구현하고 있다.

API:

```http
GET /api/overview
```

서버는 매 요청마다 다음을 읽는다.

```text
eval_set_reconciled.csv
dashboard_config.json
```

### 6.3 표시 항목

#### KPI

- 총 행
- 실사용자 GT 수
- 사진 있는 행
- 국가 수

#### 출처 provenance

- dataset key
- label
- owner
- source_type
- count

#### GT 신뢰도

Raw `gt_confidence`를 config의 `confidence_rollup`으로 canonical tier에 묶는다.

#### 지역/카테고리 분포

- country rollup
- category top-N

#### 한 행의 구조

컬럼을 다음 역할로 나눠 보여준다.

| 역할 | 예시 |
|---|---|
| 입력신호 | photo, lat/lon, timestamp, OCR, nearby candidates |
| 정답 | gt_place_name, gt_confidence |
| 베이스라인 | app_poi_rank, app_nearby_top1 |
| 메타 | dataset, photo, notes, username |

#### 파이프라인 상태

각 신호에 대해 두 숫자를 구분한다.

| 값 | 의미 |
|---|---|
| extracted | 외부 결과 파일 등으로 추출된 행 수 |
| merged | CSV에 실제 반영된 행 수 |

상태 판정:

```text
wait = extracted == 0
done = merged >= extracted
run  = 그 외
```

---

## 7. ② 평가 실행

### 7.1 목적

새 POI 예측 방법을 같은 eval set에 실행한다.

중요한 점은 “스크립트를 올린다”가 아니라, **무슨 입력을 써서 예측했는지 계약으로 남긴다**는 것이다.

같은 알고리즘이라도 다음 입력을 쓰면 의미가 달라진다.

- 좌표만 사용
- 좌표 + 후보 top-5 사용
- 좌표 + 후보 top-5 + OCR 사용
- 이미지 + VLM caption 사용
- category 사용 — 단, category는 GT 유래라 실사용 알고리즘 입력으로는 부적절

따라서 실행마다 입력 config를 저장해야 한다.

### 7.2 현재 상태

`mvp-eval-ui.html`에 UI 목업은 구현되어 있다. 실제 harness는 아직 없다.

현재 목업 기능:

- 테스트 이름 입력
- 자동 버저닝 표시
- 저장 모드 선택
- scope 선택
- 입력 파라미터 선택
- top-K 후보 선택
- predict 계약 snippet 생성
- 파일 첨부 UI
- 최근 실행 테이블 mock

### 7.3 입력 파라미터

| key | 이름 | 추출 방법 | 기본값 | 비고 |
|---|---|---|---|---|
| `image` | 이미지 | 원본 jpg | off | VLM/이미지 모델용 |
| `lat,lon` | 좌표 | EXIF GPS | on | 기본 위치 신호 |
| `timestamp` | 촬영 시각 | EXIF DateTimeOriginal | off | 시간 기반 disambiguation |
| `ocr_text` | OCR 텍스트 | Vision OCR | on | 간판/메뉴/영수증 신호 |
| `vlm_caption` | VLM 설명 | FastVLM-0.5B | off | 아직 본격 사용 전 |
| `nearby_candidates` | 주변 후보 | 지역별 기준 provider: 한국 외 MapKit, 한국 Kakao Local | on | top-K 선택 가능 |
| `city,country,address` | 역지오코딩 | Apple CLGeocoder | off | 지역 context |
| `category` | 카테고리 | GT 라벨 | off | GT 유래. 실사용 입력 금지에 가까움 |

### 7.4 top-K 후보 입력

`nearby_candidates`는 후보를 몇 개까지 넘길지 선택한다.

```text
top 3
top 5
top 10
전체
```

UI는 가능하면 각 K에서 GT가 후보 안에 존재하는 비율도 보여준다.

```text
top 5 · GT 28%
```

이 숫자는 알고리즘 성능이 아니라 검색 상한선이다.

### 7.5 predict 계약

Python 기준:

```python
def predict(case):
    lat, lon = case["lat"], case["lon"]
    ocr = case["ocr_text"]
    cands = case["nearby_candidates"]

    return {
        "prediction": "Place Name",
        "reason": "why this place was selected"
    }
```

반환값은 문자열 또는 객체를 허용한다.

```python
"Place Name"
```

또는

```python
{"prediction": "Place Name", "reason": "..."}
```

기타 언어는 다음 계약을 따른다.

```text
stdin  = JSON case
stdout = prediction string 또는 JSON
```

### 7.6 실행 결과 저장

향후 실행 결과는 CSV에 직접 섞기보다 run 단위로 남기는 편이 낫다.

```text
runs/
└── ocr-match/
    └── v1/
        ├── config.json
        ├── script.py
        ├── predictions.tsv
        ├── scores.json
        └── errors.log
```

이렇게 해야 어떤 입력/스크립트/버전으로 나온 숫자인지 추적할 수 있다.

---

## 8. ③ 평가 결과

### 8.1 목적

평가 결과 화면은 숫자를 예쁘게 보여주는 곳이 아니다.

이 화면은 다음 판단을 하게 해줘야 한다.

1. 지역별 기준 provider 후보 검색의 상한선은 어디인가?
2. nearest-only baseline은 어디까지 맞추는가?
3. OCR/LLM/VLM을 넣으면 selection failure가 줄어드는가?
4. 남은 실패는 검색 API를 바꿔야 해결되는가?
5. raw 실패 중 normalized로 회복되는 “이름 표기 문제”는 얼마나 되는가?

### 8.2 현재 상태

`mvp-eval-ui.html`의 평가 결과 탭은 현재 혼합 상태다.

| 기능 | 상태 |
|---|---|
| scope selector | UI 구현 |
| raw/norm toggle | UI 구현 |
| rank/top-k/MISS 카드 | mock 데이터 |
| retrieval curve | mock 데이터 |
| 알고리즘별 bar chart | mock 데이터 |
| case analysis | `/api/records?dataset=linkedspaces`로 부분 live |

즉, 화면 구조는 잡혀 있지만 성능 수치의 핵심은 아직 실제 평가 엔진에 연결되지 않았다.

### 8.3 헤드라인 지표

각 scope/mode에 대해 다음을 보여준다.

| 카드 | 정의 |
|---|---|
| rank-1 | GT가 1번 후보 |
| top-3 | GT rank ≤ 3 |
| top-5 | GT rank ≤ 5 |
| top-10 | GT rank ≤ 10 |
| MISS | 후보 리스트 안에 GT 없음 |
| within-Xm count | 사진 좌표 기준 X미터 안의 후보 개수 |
| within-Xm hit | provider 기준 GT가 X미터 안에 존재하는지 |

각 카드는 count와 percent를 같이 표시한다. `within-Xm` 계열은 X를 25m/50m/100m/200m처럼 고정 bucket으로 제공하되, UI에서는 기본적으로 50m와 100m를 먼저 노출한다.

```text
rank-1
30 / 190
15.8%
```

### 8.4 retrieval curve

검색 성능을 보는 그래프다.

```text
x = N: 1, 2, 3, 5, 10
y = GT가 top-N 후보 안에 존재하는 비율
```

이 선이 낮으면 알고리즘 문제가 아니라 후보 검색 문제다.

예를 들어 top-10에서도 35%라면, 어떤 selection 알고리즘도 그 API만으로는 35%를 넘기 어렵다.

### 8.5 selection accuracy

알고리즘별 최종 예측 정확도다.

```text
x = run / algorithm
y = prediction == GT 비율
```

이 그래프는 top-N 곡선과 다르다.

- retrieval curve: 검색 API가 정답을 후보 안에 넣었는가?
- selection accuracy: 알고리즘이 최종적으로 무엇을 골랐는가?

### 8.6 케이스 분석

케이스 분석은 숫자가 왜 그런지 확인하는 화면이다.

Outcome bucket:

| outcome | 뜻 | 판정 |
|---|---|---|
| `correct` | 정답 | rank == 1 |
| `selection` | 식별 실패 | rank가 2 이상 |
| `retrieval` | 검색 실패 | rank == MISS |
| `non_poi` | POI 아님 | canonical confidence가 non_poi |
| `deferred` | 평가 미실행 | rank 없음 |
| `no_gt` | GT 없음 | gt_place_name 없음 |

상세 화면은 다음을 보여준다.

- 사진
- GT
- 앱 baseline 예측
- 후보 top3
- GT 후보 하이라이트
- 앱 선택 후보 하이라이트
- OCR 텍스트
- 좌표
- 카테고리

### 8.7 필요한 API

현재 가장 중요한 미구현 API는 이것이다.

```http
GET /api/matchrate?dataset=<all|key>&mode=<raw|norm>&method=<baseline|run>
```

응답 예:

```json
{
  "dataset": "linkedspaces",
  "mode": "norm",
  "method": "baseline",
  "n": 190,
  "provider_scope": {"non_kr": "mapkit", "kr": "kakao_local"},
  "excluded": {
    "provider_not_run": 0,
    "no_gt": 4,
    "non_poi": 6,
    "unresolved": 8
  },
  "rate": {
    "rank1": {"count": 30, "pct": 15.8},
    "top3": {"count": 45, "pct": 23.7},
    "top5": {"count": 53, "pct": 27.9},
    "top10": {"count": 61, "pct": 32.1},
    "miss": {"count": 122, "pct": 64.2}
  },
  "curve": [
    {"k": 1, "count": 30, "pct": 15.8},
    {"k": 2, "count": 38, "pct": 20.0},
    {"k": 3, "count": 45, "pct": 23.7},
    {"k": 5, "count": 53, "pct": 27.9},
    {"k": 10, "count": 61, "pct": 32.1}
  ],
  "radius": [
    {"meters": 25, "candidate_count_avg": 3.2, "hit_count": 28, "hit_pct": 14.7},
    {"meters": 50, "candidate_count_avg": 8.6, "hit_count": 43, "hit_pct": 22.6},
    {"meters": 100, "candidate_count_avg": 21.4, "hit_count": 58, "hit_pct": 30.5},
    {"meters": 200, "candidate_count_avg": 46.9, "hit_count": 71, "hit_pct": 37.4}
  ],
  "flips": {
    "raw_miss": 129,
    "norm_miss": 99,
    "recovered": 30
  }
}
```

---

## 9. ④ 데이터셋 추가

### 9.1 목적

데이터셋을 늘리는 비용을 낮춘다.

사람이 해야 할 일은 최소한으로 줄인다.

```text
사람: 사진 + GT 장소명
도구: 좌표, 시각, OCR, geocode, 후보검색, rank, confidence, flags
```

### 9.2 현재 상태

`mvp-eval-ui.html`에는 flow가 목업/가이드로 구현되어 있다. 실제 ingest script는 아직 없다.

### 9.3 절차

#### Step 1. source 등록

`dashboard_config.json > sources`에 항목을 추가한다.

필수 필드:

```text
key
owner
source_type
label
color
default_confidence
```

#### Step 2. 템플릿 ZIP 업로드

데이터 추가의 1차 입력 형식은 템플릿 기반 ZIP 패키지로 통일한다. 도구는 빈 템플릿을 제공하고, 사용자는 같은 구조를 유지한 채 이미지와 GT만 채워 업로드한다.

```text
dataset_slug.zip
└─ dataset_slug/
   ├─ manifest.csv
   ├─ README.md
   └─ photos/
      ├─ IMG_0001.jpg
      └─ ...
```

사용자가 직접 채워야 하는 필수값:

- `photos/` 아래 이미지 파일
- `manifest.csv.photo`
- `manifest.csv.gt_input_raw`

선택값:

- `manifest.csv.notes`

사용자가 직접 입력하지 않는 값:

- `capture_lat`, `capture_lon`
- `timestamp`
- `country`, `city`
- `eval_provider`

이 값들은 도구가 EXIF, 좌표 기반 reverse geocoding, provider lookup으로 생성한다. 추출 또는 추정에 실패한 행만 보정 대상으로 표시한다.

#### Step 3. 자동 채움

사용자가 사진과 GT 장소명을 넣으면, 도구는 먼저 이미지에서 평가에 필요한 기본 신호를 추출한다. 목표는 “정답을 맞히는 것”이 아니라, 이후 후보 검색과 선택 알고리즘을 같은 조건에서 재현할 수 있게 만드는 것이다.

| 구분 | 필드 | 추출/생성 방법 | 용도 |
|---|---|---|---|
| 파일 식별 | `photo_id`, `file_name`, `source_id` | 파일명/등록 source | eval row 식별 |
| 이미지 메타 | `width`, `height`, `format`, `file_hash` | 이미지 파일 | 중복/손상/재처리 확인 |
| 좌표 | `lat`, `lon` | EXIF GPS | 후보 검색의 중심점 |
| 좌표 보조 | `altitude`, `gps_accuracy`, `gps_timestamp` | EXIF에 있으면 사용 | GPS 품질 판단 |
| 촬영 시각 | `captured_at` | EXIF DateTimeOriginal | 영업시간/시간대 disambiguation |
| 시간대 | `timezone` | 좌표 기반 timezone 추정 | local time 변환 |
| 기기 정보 | `device_make`, `device_model` | EXIF | source 품질 분석. 핵심 평가지표는 아님 |
| OCR | `ocr_text`, `ocr_blocks`, `ocr_confidence` | Vision OCR | 간판/메뉴/영수증 텍스트 신호 |
| VLM 보조 | `vlm_caption`, `visual_category` | 선택 옵션 | 장면/업종 추정. MVP에서는 optional |
| 역지오코딩 | `country`, `city`, `address` | reverse geocoding | 지역 판단과 provider 선택 |
| 평가 provider | `eval_provider` | country 기준. 한국 Kakao, 한국 외 MapKit | GT 기준명/후보검색 기준 |
| GT 원본 | `user_selected_place_name` | 사용자 입력 | 사용자가 의도한 장소의 원본 기록 |
| GT 입력 형식 | `gt_input_type`, `gt_input_raw`, `gt_parse_confidence` | 사용자 입력값 파싱 | 장소명/URL/provider ID/좌표/복합 입력 구분 |
| GT 기준명 | `eval_place_name` | provider 기준 canonical mapping | 후보명과 비교할 평가 기준명 |
| GT provider ID | `eval_provider_place_id` | provider lookup 또는 URL/ID 파싱 | 이름 비교보다 안정적인 정답 식별자 |
| 후보검색 | `candidates[]` | 지역별 기준 provider | retrieval/ranking 평가 |
| 후보 상세 | `candidate_name`, `provider_id`, `lat`, `lon`, `distance_m`, `category`, `rank`, `source` | provider 응답 | top-K, within-Xm 지표 계산 |
| 반경 지표 | `within_25m_count`, `within_50m_count`, `within_100m_count`, `within_200m_count` | 후보 좌표 거리 계산 | 주변 POI 밀도 측정 |
| 반경 hit | `within_25m_hit`, `within_50m_hit`, `within_100m_hit`, `within_200m_hit` | GT 후보 매칭 + 거리 계산 | 정답이 물리적으로 가까운 후보 안에 있는지 판단 |
| 매칭 결과 | `rank_raw`, `rank_norm`, `match_evidence` | matching engine | raw/norm 기준 평가 |
| 품질 플래그 | `flags` | ingest/matching 결과 | no_coord, no_exif_time, no_ocr, no_gt, provider_not_run 등 |

업로드 단계에서 반드시 있어야 하는 최소 필드는 `photo_id`, `file_name`, `gt_input_raw`다. `lat`, `lon`은 후보 검색 실행에 필요하지만 사용자가 직접 입력하는 값이 아니며, EXIF 추출에 실패하면 `needs_location_review`로 보낸다. `captured_at`은 선택 알고리즘의 보조 신호이므로 없어도 행을 버리지 않는다. 결측은 `flags`로 남기고, 해당 지표 계산에서만 제외한다.

GT가 함께 들어온 행은 기본적으로 “사용자가 고른 정답”으로 간주한다. 도구는 이 원본값을 보존한 뒤, 지역별 평가 provider 기준으로 `eval_place_name`을 생성한다.


#### GT 입력 형식 판별

GT는 항상 “깔끔한 장소명”으로 들어온다고 가정하면 안 된다. 사용자는 장소명을 직접 쓰기도 하고, 지도 앱 공유 URL이나 provider place ID를 붙여 넣을 수도 있다. 따라서 `eval_provider`를 정한 직후, GT 원본을 다음 형식 중 하나로 판별한다. 이 판별은 GT의 출처를 의심하기 위한 절차가 아니라, 같은 사용자 선택값을 provider 기준 평가값으로 안정적으로 변환하기 위한 절차다.

| `gt_input_type` | 예 | 처리 |
|---|---|---|
| `plain_name` | `Blue Bottle Coffee Shibuya` | provider 기준으로 lookup 후 `eval_place_name`/`eval_provider_place_id` 생성 |
| `provider_url` | Apple Maps/Kakao Map/Google Maps 공유 URL | URL에서 provider, place id, 좌표, 이름을 파싱 |
| `provider_place_id` | Kakao place id, MapKit identifier 등 | 해당 provider에서 상세 조회 후 canonical name 확보 |
| `name_with_address` | `블루보틀 성수, 서울 성동구...` | 이름과 주소를 분리해 lookup disambiguation에 사용 |
| `name_with_coord` | `Blue Bottle, 35.66, 139.70` | 입력 좌표를 보조 신호로 사용하되 사진 EXIF 좌표와 충돌 여부 확인 |
| `non_poi_text` | `집`, `회사`, `길거리`, `unknown` | 평가 대상 제외 또는 별도 flag 처리 |

이 판별 결과는 다음 필드로 남긴다.

```text
gt_input_raw              # 사용자가 넣은 원문
gt_input_type             # plain_name/provider_url/provider_place_id/...
gt_parse_confidence       # 파싱 신뢰도
gt_provider_hint          # 입력에서 드러난 provider. 없으면 null
gt_name_hint              # 입력에서 추출한 장소명
gt_address_hint           # 입력에서 추출한 주소
gt_coord_hint_lat/lon     # 입력에서 추출한 좌표가 있을 때
eval_provider_place_id    # 평가 provider 기준 place id
eval_place_name           # 평가 provider 기준 canonical name
```

주의할 점은 `gt_input_type`과 `eval_provider`가 다를 수 있다는 것이다. 예를 들어 한국 장소를 Google Maps URL로 넣었더라도, 최종 평가는 Kakao Local 기준으로 맞춘다. 이 경우 Google URL은 `gt_provider_hint`로만 보존하고, Kakao lookup을 통해 `eval_place_name`과 `eval_provider_place_id`를 만든다.

### 9.4 결측 처리

결측은 행 삭제가 아니라 flag다.

| 상황 | 처리 |
|---|---|
| EXIF GPS 없음 | `no_coord` |
| GT 없음 | `no_gt` |
| GT 형식 파싱 실패 | `gt_parse_failed` |
| GT provider hint와 평가 provider가 다름 | `gt_provider_mismatch`를 정보성 flag로 남김 |
| GT에 좌표가 있으나 EXIF 좌표와 크게 다름 | `gt_coord_conflict` |
| POI가 아닌 라벨 | `non_poi` 또는 향후 `no_venue` |
| 해당 provider 미실행 | `deferred` |

---

## 10. 시스템 구조

현재 구조:

```text
eval_set_reconciled.csv
        +
dashboard_config.json
        │
        ▼
server.py
  ├─ /api/overview
  └─ /api/records
        │
        ▼
dataset-overview.html
mvp-eval-ui.html
```

목표 구조:

```text
eval_set_reconciled.csv
candidate result files
run result files
dashboard_config.json
        │
        ▼
match_score.py
        │
        ▼
server.py
  ├─ /api/overview
  ├─ /api/records
  ├─ /api/matchrate
  └─ /api/runs
        │
        ▼
POI 평가 UI
```

---

## 11. API 명세

### 11.1 `GET /api/overview`

상태: 구현됨.

목적:

- 데이터셋 구성
- source provenance
- confidence rollup
- country/category 분포
- schema fill
- pipeline 상태
- config warnings

반환 주요 필드:

```json
{
  "generated_from": "eval_set_reconciled.csv + dashboard_config.json (live)",
  "total": 280,
  "n_columns": 23,
  "sources": [],
  "confidence": [],
  "countries": [],
  "categories": [],
  "fill": {},
  "photo_present": 268,
  "gt_present": 272,
  "schema": [],
  "samples": {},
  "pipeline": [],
  "config_warnings": []
}
```

### 11.2 `GET /api/records?dataset=<key|all>`

상태: 부분 구현됨.

목적:

- case analysis용 row-level record 반환

현재 반환 예:

```json
{
  "dataset": "linkedspaces",
  "photo": "...jpg",
  "photo_url": "/linkedspaces-photos/...jpg",
  "gt": "Place Name",
  "gt_confidence": "user_selected",
  "category": "restaurant",
  "lat": "37.12345",
  "lon": "-122.123",
  "ocr_text": "...",
  "baseline_pick": "Nearest Candidate",
  "rank": "3",
  "n_wide": "12",
  "dist": "42",
  "candidates": [
    {"name": "Candidate A", "dist": "12m"}
  ],
  "outcome": "selection",
  "oc_label": "식별실패"
}
```

개선 필요:

- top3뿐 아니라 top5/top10/full 후보 저장
- raw/norm match evidence 포함
- candidate rank/dist/source/provider 명시

### 11.3 `GET /api/matchrate`

상태: 미구현.

목적:

- 평가 결과 탭의 headline card와 retrieval curve를 live로 제공

Query:

```text
dataset=all|linkedspaces|union-city|vancouver
mode=raw|norm
method=baseline|<run-id>
```

필수 반환:

- n
- provider scope
- excluded reasons
- rank1/top3/top5/top10/miss
- curve at N=1,2,3,5,10
- radius buckets: within-25m/50m/100m/200m candidate count와 GT hit
- raw→norm flips

### 11.4 `GET /api/runs`, `POST /api/runs`

상태: 미구현.

목적:

- 알고리즘 실행 등록/조회
- 최근 실행 목록
- 실행 상태와 score 조회

---

## 12. 정규화 매칭 엔진

### 12.1 왜 필요한가

현재 raw 이름 비교만으로는 실제 검색 실패와 이름 표기 실패를 구분하지 못한다.

그래서 `match_score.py`가 필요하다.

### 12.2 입력

```text
eval_set_reconciled.csv
provider별 candidate result TSV/JSON
dashboard_config.json
```

### 12.3 출력

최소 출력:

```text
photo
dataset
user_selected_place_name
eval_place_name
eval_provider
candidate_name
rank_raw
rank_norm
match_raw
match_norm
match_score
match_evidence
excluded_reason
```

### 12.4 normalization

양쪽 문자열에 동일 적용:

1. lowercase
2. Unicode normalize
3. diacritics 제거
4. `®`, `™`, `©` 제거
5. punctuation 제거/공백화
6. `&`와 `and` 정규화
7. generic token 제거 또는 저가중
8. token set 생성

Generic token 예:

```text
the
restaurant
bar
grill
cafe
coffee
center
store
shop
hotel
market
kitchen
house
place
```

### 12.5 match rule 초안

```text
normalized exact match
OR significant token recall >= 0.8
OR jaccard >= 0.6
```

동률이면 더 가까운 후보를 선택한다.

### 12.6 evidence

모든 normalized match는 사람이 검토할 evidence를 남긴다.

```json
{
  "gt_norm": "din tai fung",
  "candidate_norm": "din tai fung",
  "overlap_tokens": ["din", "tai", "fung"],
  "score": 1.0,
  "rule": "normalized_exact"
}
```

---

## 13. 기능 요구사항

### 13.1 구현됨

| ID | 내용 |
|---|---|
| FR-OV-1 | CSV+config 기반 live overview API |
| FR-OV-2 | config warning 노출 |
| FR-OV-3 | source provenance 표시 |
| FR-OV-4 | confidence rollup 표시 |
| FR-OV-5 | schema role/fill 표시 |
| FR-OV-6 | pipeline extracted/merged 상태 표시 |
| FR-REC-1 | row-level records API 일부 |
| FR-CASE-1 | outcome별 case list/detail 일부 |

### 13.2 목업 구현됨, 실제 연결 필요

| ID | 내용 |
|---|---|
| FR-RUN-1 | 테스트 이름/버전 UI |
| FR-RUN-2 | 입력 파라미터 선택 UI |
| FR-RUN-3 | predict 계약 snippet 생성 |
| FR-RUN-4 | 파일 첨부 UI |
| FR-EVAL-1 | rank/top-k/MISS 카드 UI |
| FR-EVAL-2 | raw/norm toggle UI |
| FR-EVAL-3 | retrieval curve UI |
| FR-EVAL-4 | 알고리즘별 accuracy chart UI |
| FR-ADD-1 | dataset 추가 flow 가이드 |

### 13.3 미구현

| ID | 내용 |
|---|---|
| FR-MATCH-1 | `match_score.py` raw/norm rank 산출 |
| FR-MATCH-2 | full/top10 candidate 기반 top-N curve 산출 |
| FR-API-1 | `/api/matchrate` |
| FR-RUN-API-1 | `/api/runs` |
| FR-RUN-EXEC-1 | predict script 실행 harness |
| FR-INGEST-1 | `ingest_dataset.py` |
| FR-INGEST-2 | EXIF/OCR/geocode/지역별 provider 후보 자동 채움 |

---

## 14. 구현 우선순위

### P0. 평가 결과를 mock에서 live로 바꾸기

이게 가장 중요하다.

1. `server.py`의 절대경로 제거

현재:

```python
DIRECTORY = "/Users/massis/Desktop/fastblog/poi-test-data"
```

권장:

```python
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
```

2. 후보 결과를 top10 또는 full로 저장
3. `match_score.py` 구현
4. `/api/matchrate` 구현
5. `mvp-eval-ui.html`의 mock `DATA` 제거
6. 평가 결과 탭을 live API에 연결

### P1. case analysis 고도화

1. normalized match evidence 표시
2. raw MISS → norm recovered 케이스 필터
3. retrieval failure / selection failure / non_poi / no_gt 필터 정리
4. 후보 리스트 top10 표시

### P2. algorithm run harness

1. run directory 구조 생성
2. predict(case) 실행
3. timeout/error 처리
4. predictions.tsv 저장
5. scores.json 저장
6. `/api/runs` 추가
7. 평가 결과 탭에서 run별 비교

### P3. ingest 자동화

1. 새 dataset config 등록 가이드 유지
2. 사진+GT 입력
3. EXIF 추출
4. OCR 추출
5. geocode
6. candidate probe
7. CSV append/merge
8. 결측 flag

---

## 15. MVP 완료 정의

MVP는 “화면이 있다”가 아니라, 다음 질문에 live data로 답할 수 있어야 끝난다.

> 현재 앱은 사용자가 고른 장소를 몇 %나 첫 후보로 맞추고, 몇 %는 후보 안에도 못 넣는가?

완료 조건:

- [ ] `match_score.py`가 raw/norm rank를 산출한다.
- [ ] `/api/matchrate`가 scope/mode별 metric을 반환한다.
- [ ] 평가 결과 탭이 mock DATA 없이 live API를 사용한다.
- [ ] rank-1/top-3/top-5/top-10/MISS가 live 값으로 표시된다.
- [ ] within-25m/50m/100m/200m 후보 수와 GT hit가 live 값으로 표시된다.
- [ ] top-N retrieval curve가 live 값으로 표시된다.
- [ ] n과 excluded reason이 항상 표시된다.
- [ ] raw→norm recovered 케이스 수가 표시된다.
- [ ] case detail에서 GT/앱선택/normalized match evidence를 볼 수 있다.
- [ ] baseline normalized 성능이 확정된다.

---

## 16. 열린 결정

1. `non_poi`와 `no_venue`를 분리할지.
2. normalized match threshold 초기값을 얼마로 둘지.
3. candidate list를 full 저장할지 top10까지만 저장할지.
4. 실행 결과를 CSV 컬럼에 머지할지, `runs/` 아래 별도 관리할지.
5. 한국 행은 Kakao Local을 기준 baseline으로 평가한다. MapKit 기준 결과가 필요하면 보조 비교 run으로만 둔다.
6. `category`를 알고리즘 입력으로 허용할지. 현재는 GT 유래라 기본 off가 맞다.

---

## 17. 현재 파일 기준 상태

| 파일 | 역할 |
|---|---|
| `eval_set_reconciled.csv` | 현재 평가셋 본체 |
| `dashboard_config.json` | source/confidence/schema/pipeline config |
| `server.py` | 로컬 API 서버, `/api/overview`, `/api/records` |
| `dataset-overview.html` | live 데이터셋 개요 |
| `mvp-eval-ui.html` | 최종 도구 목업. 일부 live, 일부 mock |
| `merge_signals.py` | 신호를 CSV에 비파괴 머지 |
| `ls_nearby_results.tsv` | linkedspaces MapKit 후보/랭크 결과 |
| `ls_ocr_text.tsv`, `ocr_text.tsv` | OCR 추출 결과 |
| `ai_ocr_v2.tsv`, `ai_ocr_v3.tsv` | 온디바이스 LLM/OCR 실험 결과 |

---

## 18. 한 줄 요약

이 도구는 “POI 성능 대시보드”가 아니라, **사용자가 고른 장소를 앱이 왜 못 맞추는지 — 후보 검색이 약한 건지, 후보 선택이 약한 건지 — 를 분리해서 보여주는 평가 장치**다.

그 구분이 서야 OCR, LLM, VLM, 후보 API 교체 중 무엇이 실제로 효과가 있는지 말할 수 있다.
