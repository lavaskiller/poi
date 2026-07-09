# POI 평가 도구 명세서

> 기준 파일: `mvp-eval-ui.html`, `dataset-overview.html`, `server.py`, `dashboard_config.json`, `eval_set_reconciled.csv`  
> 작성일: 2026-07-08  
> 대상 프로젝트: Bloggo POI 식별 개선 / KS2-32, KS2-34

---

## 1. 목적

POI 평가 도구는 Bloggo 앱이 사진/좌표 기반으로 제안하는 POI가 **사용자의 최종 장소 선택**과 얼마나 일치하는지 재현 가능하게 측정하고, 이후 OCR/LLM/VLM 기반 개선안을 같은 기준으로 비교하기 위한 로컬 평가 시스템이다.

이 도구의 핵심 목적은 세 가지다.

1. 현재 앱의 POI 후보 검색/선택 성능을 `rank-1`, `top-k`, `MISS`로 측정한다.
2. raw 이름 비교와 normalized 이름 비교를 분리해 이름 표기 차이로 생기는 가짜 실패를 드러낸다.
3. 새 알고리즘/새 데이터셋을 같은 계약으로 실행하고, 결과를 대시보드에서 비교한다.

---

## 2. 제품 원칙

### 2.1 정직성

모든 평가 수치는 반드시 다음 정보를 함께 표시한다.

- `n`: 실제 분모
- 제외 행 수 및 이유
- raw 기준인지 normalized 기준인지
- 검색 실패인지 식별 실패인지
- mock/example인지 live 데이터인지

### 2.2 데이터 주도

대시보드는 하드코딩된 데이터 구조에 의존하지 않는다. 가능한 한 다음 두 파일을 single source로 사용한다.

```text
eval_set_reconciled.csv
dashboard_config.json
```

### 2.3 모르는 값은 숨기지 않음

새 dataset, 새 confidence, 새 column이 config에 없으면 조용히 무시하지 않고 `config_warnings`로 노출한다.

### 2.4 원본 데이터 비파괴

자동 추출/머지 스크립트는 기본적으로 기존 값을 덮어쓰지 않고 빈 셀만 채운다. 기존 GT 라벨과 사람 판단은 보존한다.

---

## 3. 현재 구현 상태 요약

### 3.1 구현된 것

| 영역 | 상태 | 파일 |
|---|---|---|
| 데이터셋 개요 API | 구현됨 | `server.py /api/overview` |
| 레코드 API | 부분 구현됨 | `server.py /api/records` |
| 라이브 데이터셋 개요 화면 | 구현됨 | `dataset-overview.html` |
| MVP 통합 목업 화면 | 구현됨 | `mvp-eval-ui.html` |
| case analysis | 부분 live 구현 | `/api/records?dataset=linkedspaces` |
| 평가 실행 UI | 목업 | `mvp-eval-ui.html` |
| 평가 결과 카드/그래프 | mock/example | `mvp-eval-ui.html` |
| 데이터셋 추가 flow | 목업/계약 가이드 | `mvp-eval-ui.html` |
| 정규화 매칭 엔진 | 미구현 | 예정 `match_score.py` |
| matchrate API | 미구현 | 예정 `/api/matchrate` |
| 알고리즘 실행 harness | 미구현 | 예정 |
| ingest 자동화 | 미구현 | 예정 `ingest_dataset.py` |

### 3.2 현재 데이터셋 기준 주요 수치

`eval_set_reconciled.csv` 기준 현재 데이터셋은 다음과 같다.

| 항목 | 값 |
|---|---:|
| 총 행 | 280 |
| 총 컬럼 | 23 |
| 사진 있는 행 | 268 |
| canonical `user_selected` | 233 |
| baseline rank가 있는 행 | 242 |
| config warning | 0 |

Dataset 분포:

| dataset | count | 성격 |
|---|---:|---|
| `linkedspaces` | 228 | 실사용자 방문 export |
| `union-city` | 33 | 개인 블로그/코너케이스 |
| `vancouver` | 19 | 개인 블로그/코너케이스 |

---

## 4. 정보 구조 / 화면 명세

`mvp-eval-ui.html`는 4개 탭으로 구성된다.

```text
① 개요
② 평가 실행
③ 평가 결과
④ 데이터셋 추가
```

---

## 5. ① 개요 탭 명세

### 5.1 목적

현재 평가셋이 어떤 출처와 신뢰도로 구성되어 있고, 각 입력 신호가 얼마나 채워져 있는지 보여준다.

### 5.2 주요 UI

#### KPI 카드

| 카드 | 의미 | 데이터 출처 |
|---|---|---|
| 총 행 | 평가셋 전체 row 수 | `/api/overview.total` |
| 실사용자 GT | canonical `user_selected` row 수 | `/api/overview.confidence` |
| 사진 있는 행 | photo 컬럼 채움 수 | `/api/overview.photo_present` |
| 국가 | country rollup 종류 수 | `/api/overview.countries` |

#### 출처 provenance

각 dataset에 대해 다음을 표시한다.

- dataset key
- label
- owner
- source_type
- row count
- color

Config 위치:

```json
{
  "sources": {
    "linkedspaces": {
      "label": "실사용자 방문",
      "owner": "실사용자",
      "source_type": "real-user-export"
    }
  }
}
```

#### 신뢰등급 rollup

Raw `gt_confidence`를 canonical tier로 묶어 표시한다.

| canonical tier | 의미 |
|---|---|
| `user_selected` | 실제 사용자 선택 기반 지표 대상 |
| `confident` | 손라벨/콘텐츠 근거가 비교적 강한 케이스 |
| `non_poi` | POI가 아닌 케이스, must-refuse 평가 대상 |
| `unresolved` | GT 불확실, headline metric 제외 |

#### 국가/카테고리 분포

- 국가: dataset별 보정값과 CSV country를 함께 사용한다.
- 카테고리: CSV의 `category` 컬럼을 집계한다.

#### 한 행의 구조

각 컬럼을 다음 역할로 나눈다.

| 역할 | 예시 컬럼 | 의미 |
|---|---|---|
| 입력벡터 | image, lat/lon, timestamp, OCR, candidates | 알고리즘이 받을 수 있는 입력 |
| 정답 | `gt_place_name`, `gt_confidence` | 평가 기준 |
| 베이스라인 | `app_poi_rank`, `app_nearby_top1` | 현재 앱/MapKit 기준 결과 |
| 메타 | dataset, photo, notes | 식별/관리 정보 |

목업에서는 `ROWSTRUCT`로 정의되어 있고, 채움 비율은 `/api/overview.fill`에서 live로 가져온다.

### 5.3 기능 요구사항

| ID | 요구사항 | 상태 |
|---|---|---|
| OV-1 | `/api/overview`에서 CSV+config 기반 개요 JSON을 반환한다 | 구현됨 |
| OV-2 | config 미매핑 값을 warning으로 노출한다 | 구현됨 |
| OV-3 | dataset/source별 provenance를 표시한다 | 구현됨 |
| OV-4 | confidence rollup 결과를 표시한다 | 구현됨 |
| OV-5 | 컬럼별 역할과 채움 비율을 표시한다 | 구현됨 |
| OV-6 | 파이프라인 단계별 extracted/merged 상태를 표시한다 | 구현됨 |

---

## 6. ② 평가 실행 탭 명세

### 6.1 목적

새 POI 예측 알고리즘을 제출하고, 선택한 입력 신호만을 사용해 eval set 전체 또는 특정 dataset에 대해 실행한다.

현재는 UI 목업 상태이며 실제 실행 harness는 미구현이다.

### 6.2 실행 단위

하나의 실행은 다음 메타데이터를 가진다.

| 필드 | 설명 |
|---|---|
| test name | 테스트 이름, 예: `ocr-match` |
| version | 같은 이름이면 자동 증가, 예: `v1`, `v2` |
| script | 제출된 예측 스크립트 파일 |
| input config | 선택된 입력 파라미터 목록 |
| scope | 전체 또는 특정 dataset |
| status | running / done / failed |
| score summary | rank-1 등 핵심 수치 |

### 6.3 저장 모드

| 모드 | 설명 |
|---|---|
| 자동 | 같은 이름의 다음 버전으로 저장 |
| v1 덮어쓰기 | 기존 v1 결과 교체 |
| v2 덮어쓰기 | 기존 v2 결과 교체 |

### 6.4 실행 scope

| scope | 의미 |
|---|---|
| 전체 | 모든 dataset |
| linkedspaces | 실사용자 방문 데이터 |
| union-city | 우혁 개인 블로그/코너케이스 |
| vancouver | 인소 개인 블로그/코너케이스 |

### 6.5 입력 파라미터

목업에서 선택 가능한 입력은 다음과 같다.

| key | 이름 | 현재 추출 방법 | 기본 선택 | 주의 |
|---|---|---|---|---|
| `image` | 이미지 | 원본 사진 jpg | off | VLM/이미지 모델용 |
| `lat,lon` | 좌표 | EXIF GPS | on | 좌표 단독으로 venue 명명 금지 |
| `timestamp` | 촬영 시각 | EXIF DateTimeOriginal | off | 시간 기반 disambiguation 가능 |
| `ocr_text` | OCR 텍스트 | Vision VNRecognizeTextRequest | on | 간판/영수증/텍스트 신호 |
| `vlm_caption` | VLM 설명 | FastVLM-0.5B | off | 아직 미추출/부분 실험 |
| `nearby_candidates` | 주변 후보 | MapKit MKLocalPointsOfInterest | on | top-K 선택 가능 |
| `city,country,address` | 역지오코딩 | Apple CLGeocoder | off | area context |
| `category` | 카테고리 | GT 라벨 | off | GT 유래라 실사용 알고리즘에는 금지 |

### 6.6 후보 top-K 옵션

`nearby_candidates` 입력은 몇 개의 후보를 넘길지 선택할 수 있다.

| 옵션 | 의미 |
|---|---|
| top 3 | 상위 3개 후보만 전달 |
| top 5 | 상위 5개 후보만 전달 |
| top 10 | 상위 10개 후보 전달 |
| 전체 | 검색 API가 반환한 전체 후보 전달 |

UI는 각 top-K 안에 GT가 존재하는 비율을 함께 표시해야 한다.

예:

```text
top 5 · GT 28%
```

### 6.7 예측 함수 계약

#### Python

```python
def predict(case):
    # selected input only
    lat, lon = case["lat"], case["lon"]
    ocr = case["ocr_text"]
    cands = case["nearby_candidates"]

    return {
        "prediction": "Place Name",
        "reason": "why this place was selected"
    }
```

반환값은 다음 중 하나를 허용한다.

```python
"Place Name"
```

또는

```python
{
  "prediction": "Place Name",
  "reason": "..."
}
```

#### 기타 언어

- stdin: JSON case
- stdout: prediction string 또는 JSON

예:

```json
{
  "prediction": "Sizzling Lunch",
  "reason": "OCR contains signage and candidate list includes same venue"
}
```

### 6.8 실행 harness 요구사항

| ID | 요구사항 | 상태 |
|---|---|---|
| RUN-1 | 선택한 입력만 포함한 case bundle을 생성한다 | 미구현 |
| RUN-2 | 제출 스크립트를 eval set 전체에 실행한다 | 미구현 |
| RUN-3 | 실행 결과를 versioned run으로 저장한다 | 미구현 |
| RUN-4 | 같은 이름이면 자동 버저닝한다 | 목업 구현 |
| RUN-5 | 결과를 평가 엔진으로 넘겨 score를 산출한다 | 미구현 |
| RUN-6 | 최근 실행 목록을 표시한다 | 목업 구현 |

---

## 7. ③ 평가 결과 탭 명세

### 7.1 목적

현재 baseline과 제출된 알고리즘들의 성능을 같은 기준으로 비교한다.

평가 결과 탭은 세 개의 질문에 답해야 한다.

1. 후보 검색 API가 정답을 후보 리스트 안에 넣어주는가?
2. 후보 안에 정답이 있을 때 알고리즘이 잘 고르는가?
3. 실패 케이스는 검색 실패인가, 식별 실패인가?

### 7.2 컨트롤

#### Scope 선택

```text
전체
linkedspaces · 실사용자
union-city · 우혁
vancouver · 인소
```

#### Matching mode

| mode | 의미 |
|---|---|
| raw | 원문 이름 기준 exact/substring 매칭 |
| normalized | 정규화 토큰셋 매칭 |

### 7.3 헤드라인 카드

표시 metric:

| metric | 정의 | UX 의미 |
|---|---|---|
| rank-1 | GT가 첫 번째 후보 | 자동/무노력 성공 |
| top-3 | GT가 상위 3개 후보 안에 있음 | 낮은 사용자 노력 |
| top-5 | GT가 상위 5개 후보 안에 있음 | 리스트 내 발견 가능 |
| MISS | GT가 후보 리스트에 없음 | 수동 검색 필요/검색 실패 |

각 카드는 다음을 표시한다.

```text
percentage
count / n
```

예:

```text
rank-1
15.8%
30 / 190
```

### 7.4 meta line

항상 다음을 표시해야 한다.

```text
실사용자 GT n=190 · 제외: KR 28 · no_gt 4 · no_venue 6 · 기준: normalized 토큰셋
```

### 7.5 raw → normalized flip 표시

normalized mode에서는 raw 기준에서 MISS였지만 normalized 기준으로 회복된 케이스 수를 표시한다.

예:

```text
raw→normalized 뒤집힘: MISS 129 → 99 (가짜 MISS 30개 매칭으로 회복)
```

### 7.6 검색 retrieval curve

#### 목적

검색 API가 GT를 top-N 후보 안에 포함시키는지를 보여준다.

#### X축

```text
N = 1, 2, 3, 5, 10
```

#### Y축

```text
GT가 top-N 후보 안에 존재하는 비율
```

#### Line 종류

| line | 의미 | 상태 |
|---|---|---|
| MapKit | 현재 baseline 후보 API | 구현 대상 |
| Google Places | 대안 후보 API | 예시/이후 |
| Kakao Local | KR 대상 후보 API | 이후 |

주의: 이 그래프는 **검색 성능**이다. 알고리즘 선택 성능이 아니다.

### 7.7 식별 selection 정확도 막대그래프

#### 목적

후보/API와 입력 신호를 사용해 최종 예측 장소명을 내는 알고리즘별 정확도를 비교한다.

#### X축

알고리즘/run 이름.

예:

```text
nearest-only
ocr-match
fastvlm-name
```

#### Y축

```text
prediction == GT 비율
```

주의: 이 그래프는 top-N 함수가 아니라 **알고리즘당 하나의 정확도**다.

### 7.8 케이스 분석

현재 `/api/records?dataset=linkedspaces`를 사용해 부분 live로 구현되어 있다.

#### outcome bucket

| outcome | 라벨 | 정의 |
|---|---|---|
| `correct` | 정답 | `app_poi_rank == 1` |
| `selection` | 식별실패 | GT가 후보에는 있지만 rank 2 이상 |
| `retrieval` | 검색실패 | `app_poi_rank == MISS` |
| `non_poi` | non_poi | POI가 아닌 행 |
| `deferred` | deferred | baseline 미실행 |
| `no_gt` | no_gt | GT 없음 |
| `other` | 기타 | 위에 속하지 않음 |

#### 케이스 리스트

각 케이스는 다음을 표시한다.

- thumbnail
- GT 장소명
- outcome badge

#### 상세 패널

선택한 케이스에 대해 다음을 표시한다.

- 사진
- GT
- 앱 baseline 예측
- outcome 설명
- 후보 top3
- 후보 내 GT/앱선택 하이라이트
- OCR 텍스트
- 좌표
- 카테고리

### 7.9 기능 요구사항

| ID | 요구사항 | 상태 |
|---|---|---|
| EVAL-1 | scope별 metric을 조회한다 | 미구현 `/api/matchrate` 필요 |
| EVAL-2 | raw/norm 토글에 따라 metric을 갱신한다 | UI 목업 |
| EVAL-3 | rank-1/top-3/top-5/MISS 카드를 표시한다 | UI 목업 |
| EVAL-4 | top-N retrieval curve를 표시한다 | UI 목업 |
| EVAL-5 | 알고리즘별 selection accuracy를 표시한다 | UI 목업 |
| EVAL-6 | case outcome bucket을 표시한다 | 부분 구현 |
| EVAL-7 | 케이스 상세에서 후보/GT/앱선택을 하이라이트한다 | 부분 구현 |
| EVAL-8 | raw→normalized flip 수를 표시한다 | UI 목업 |

---

## 8. ④ 데이터셋 추가 탭 명세

### 8.1 목적

새 블로그/방문 기록 소스를 평가셋에 붙이는 절차를 명확히 안내한다.

목표는 사람이 제공해야 하는 것을 최소화하는 것이다.

```text
사람: 사진 + GT 장소명
도구: 좌표, 시각, OCR, 지오코딩, 후보검색, rank, confidence 등 자동 채움
```

### 8.2 등록 절차

#### Step 1. Config 등록

`dashboard_config.json > sources`에 새 dataset을 추가한다.

필수 필드:

| 필드 | 설명 |
|---|---|
| key | dataset 식별자 |
| owner | 소유자/라벨러 |
| source_type | `real-user-export`, `personal-blog` 등 |
| label | UI 표시명 |
| color | palette token |
| default_confidence | 기본 GT confidence |

예:

```json
{
  "seoul-trip": {
    "label": "서울 여행",
    "owner": "인소",
    "source_type": "personal-blog",
    "color": "green",
    "default_confidence": "confirmed_user"
  }
}
```

#### Step 2. 최소 입력 제공

사람이 제공해야 하는 최소 입력:

| 입력 | 필수 | 설명 |
|---|---|---|
| 사진 | 필수 | EXIF GPS 포함 권장 |
| GT 장소명 | 필수 | owner가 아는 실제 장소명 |
| category | 선택 | 장소 타입 |
| notes | 선택 | 라벨 근거/주의사항 |

#### Step 3. 자동 채움

`ingest_dataset.py`가 다음을 채운다.

| 컬럼/신호 | 추출 방법 |
|---|---|
| 좌표 | EXIF GPS |
| 촬영 시각 | EXIF DateTimeOriginal |
| OCR 텍스트 | Vision OCR |
| 도시/국가/주소 | reverse geocoding |
| MapKit 후보 | MKLocalPointsOfInterest |
| baseline rank | 후보검색 + 매칭 |
| gt_confidence | source의 default_confidence |
| flags | no_coord, no_gt 등 |

### 8.3 CLI 예시

```bash
python3 ingest_dataset.py \
  --dataset seoul-trip \
  --owner 인소 \
  --source personal-blog \
  --photos ./seoul/ \
  --gt seoul_gt.csv
```

### 8.4 결측 처리 원칙

결측은 행 삭제가 아니라 flag로 남긴다.

| 결측 | 처리 |
|---|---|
| EXIF GPS 없음 | `no_coord` flag |
| GT 없음 | `no_gt` flag |
| venue가 아닌 라벨 | `non_poi` 또는 향후 `no_venue` |
| baseline 미실행 | `deferred` |

### 8.5 기능 요구사항

| ID | 요구사항 | 상태 |
|---|---|---|
| ADD-1 | 새 source를 config에 등록한다 | 수동 |
| ADD-2 | 사진+GT CSV를 입력받는다 | 미구현 |
| ADD-3 | EXIF/OCR/geocode/MapKit을 자동 실행한다 | 미구현 |
| ADD-4 | 기존 CSV에 비파괴 append/merge한다 | 미구현 |
| ADD-5 | 결측을 flag로 남기고 dashboard warning에 노출한다 | 미구현 |

---

## 9. API 명세

## 9.1 `GET /api/overview`

### 목적

현재 CSV와 config를 기반으로 데이터셋 구성, 스키마, 파이프라인 상태를 반환한다.

### 상태

구현됨.

### Response shape

```json
{
  "generated_from": "eval_set_reconciled.csv + dashboard_config.json (live)",
  "total": 280,
  "n_columns": 23,
  "palette": ["blue", "cyan", "violet"],
  "sources": [],
  "confidence": [],
  "countries": [],
  "categories": [],
  "category_total_kinds": 0,
  "fill": {},
  "photo_present": 268,
  "gt_present": 272,
  "schema": [],
  "samples": {},
  "pipeline": [],
  "config_warnings": []
}
```

### 주요 필드

#### `sources[]`

```json
{
  "key": "linkedspaces",
  "count": 228,
  "label": "실사용자 방문",
  "color": "blue",
  "owner": "실사용자",
  "source_type": "real-user-export",
  "desc": "...",
  "known": true
}
```

#### `confidence[]`

```json
{
  "key": "user_selected",
  "count": 233,
  "color": "gold",
  "desc": "...",
  "members": [["user_selected", 228], ["confirmed_user", 5]],
  "known": true
}
```

#### `pipeline[]`

```json
{
  "label": "MapKit 베이스라인",
  "extracted": 242,
  "merged": 242,
  "total": 280,
  "status": "done",
  "note": "38행 제외(한국·무사진, kr_deferred)"
}
```

---

## 9.2 `GET /api/records?dataset=<key|all>`

### 목적

케이스 분석용 row-level records를 반환한다.

### 상태

부분 구현됨.

현재 `mvp-eval-ui.html`의 case analysis는 다음을 호출한다.

```http
GET /api/records?dataset=linkedspaces
```

### Response item

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
    {"name": "Candidate A", "dist": "12m"},
    {"name": "Candidate B", "dist": "20m"}
  ],
  "outcome": "selection",
  "oc_label": "식별실패"
}
```

### 개선 필요

현재 후보 리스트는 `ls_nearby_results.tsv`의 `top3_wide`만 파싱한다. 향후 top-5/top-10 curve와 normalized evidence를 위해 다음이 필요하다.

```json
{
  "candidates": [
    {
      "rank": 1,
      "name": "...",
      "dist_m": 12,
      "source": "MapKit",
      "match_raw": false,
      "match_norm": true,
      "match_score": 0.82,
      "match_evidence": ["tokenA", "tokenB"]
    }
  ]
}
```

---

## 9.3 `GET /api/matchrate?dataset=<key|all>&mode=<raw|norm>`

### 목적

평가 결과 탭의 headline cards와 retrieval curve를 live로 제공한다.

### 상태

미구현.

### Query params

| param | values | 설명 |
|---|---|---|
| dataset | `all`, `linkedspaces`, `union-city`, `vancouver` | 평가 scope |
| mode | `raw`, `norm` | 매칭 방식 |
| confidence | optional | 기본 `user_selected` |
| method | optional | 기본 `baseline` |

### Response shape

```json
{
  "dataset": "linkedspaces",
  "mode": "norm",
  "method": "baseline",
  "n": 190,
  "excluded": {
    "kr_deferred": 28,
    "no_gt": 4,
    "non_poi": 6,
    "unresolved": 8
  },
  "rate": {
    "rank1": {"count": 30, "pct": 15.8},
    "top3": {"count": 45, "pct": 23.7},
    "top5": {"count": 53, "pct": 27.9},
    "miss": {"count": 122, "pct": 64.2}
  },
  "curve": [
    {"k": 1, "count": 30, "pct": 15.8},
    {"k": 2, "count": 38, "pct": 20.0},
    {"k": 3, "count": 45, "pct": 23.7},
    {"k": 5, "count": 53, "pct": 27.9},
    {"k": 10, "count": 61, "pct": 32.1}
  ],
  "flips": {
    "raw_miss": 129,
    "norm_miss": 99,
    "recovered": 30
  }
}
```

---

## 10. 데이터 계약

## 10.1 `eval_set_reconciled.csv`

현재 주요 컬럼:

```text
dataset
photo
capture_lat
capture_lon
timestamp
caption_oracle
caption_ondevice
gt_place_name
poi_list_match
poi_match_keyword
category
gt_confidence
baseline_place_title
app_nearby_n_wide
app_poi_rank
app_poi_dist_m
app_nearby_top1
notes
username
city
country
address
photo_url
```

### 역할별 분류

| 역할 | 컬럼 |
|---|---|
| 식별자 | `dataset`, `photo`, `username` |
| 입력 신호 | `capture_lat`, `capture_lon`, `timestamp`, `caption_ondevice`, `photo_url` |
| 정답 | `gt_place_name`, `gt_confidence`, `category` |
| baseline | `app_nearby_n_wide`, `app_poi_rank`, `app_poi_dist_m`, `app_nearby_top1` |
| 보조/메모 | `notes`, `city`, `country`, `address`, `poi_list_match`, `poi_match_keyword` |

## 10.2 향후 추가될 평가 컬럼

`match_score.py`가 생성해야 할 컬럼:

```text
match_raw
match_norm
match_rank_raw
match_rank_norm
match_score_norm
match_evidence
match_excluded_reason
```

또는 CSV를 오염시키지 않기 위해 별도 결과 파일로 관리할 수도 있다.

추천:

```text
results/match/baseline_mapkit_raw.tsv
results/match/baseline_mapkit_norm.tsv
results/runs/<run_name>/predictions.tsv
results/runs/<run_name>/scores.json
```

---

## 11. 정규화 매칭 명세

### 11.1 목적

POI 이름 표기 차이 때문에 발생하는 가짜 MISS를 줄인다.

예:

```text
"Din Tai Fung®" vs "Din Tai Fung"
"Joe & The Juice" vs "Joe and the Juice"
"Ladurée Paris" vs "Laduree"
```

### 11.2 원칙

1. GT를 외부 DB 이름으로 덮어쓰지 않는다.
2. GT와 후보 이름에 같은 정규화 함수를 적용한다.
3. 후보 리스트 전체에서 가장 높은 match score를 찾는다.
4. top1만 보고 실패 처리하지 않는다.
5. threshold와 stopword는 config로 관리한다.
6. raw 결과와 norm 결과를 모두 보존한다.

### 11.3 정규화 단계

입력 문자열에 대해:

1. lowercase
2. unicode normalize / diacritics 제거
3. punctuation 제거 또는 공백화
4. `&` → `and`
5. trademark 기호 제거: `®`, `™`, `©`
6. generic token 제거 또는 저가중
7. whitespace normalize
8. token set 생성

### 11.4 generic token 예시

```text
the
restaurant
bar
grill
cafe
coffee
center
centre
store
shop
hotel
market
kitchen
house
place
```

### 11.5 match 판정

초기 기준 제안:

```text
exact normalized string match
OR
significant token recall >= 0.8
OR
jaccard >= 0.6
```

동률이면 capture point에서 더 가까운 후보를 선택한다.

### 11.6 output evidence

각 match는 사람이 검토할 수 있도록 evidence를 남긴다.

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

## 12. 실행 결과 저장 명세

향후 평가 실행 harness는 다음 구조를 사용한다.

```text
runs/
└── ocr-match/
    ├── v1/
    │   ├── config.json
    │   ├── script.py
    │   ├── predictions.tsv
    │   ├── scores.json
    │   └── errors.log
    └── v2/
        ├── config.json
        ├── script.py
        ├── predictions.tsv
        ├── scores.json
        └── errors.log
```

### 12.1 `config.json`

```json
{
  "name": "ocr-match",
  "version": 2,
  "scope": "linkedspaces",
  "inputs": {
    "lat,lon": {"method": "EXIF GPS"},
    "ocr_text": {"method": "Vision VNRecognizeTextRequest"},
    "nearby_candidates": {
      "method": "MapKit MKLocalPointsOfInterest",
      "top_k": 5
    }
  },
  "created_at": "2026-07-08T00:00:00Z"
}
```

### 12.2 `predictions.tsv`

```text
photo	dataset	prediction	reason	status	error
IMG_001.jpg	linkedspaces	Sizzling Lunch	OCR signage match	ok	
```

### 12.3 `scores.json`

```json
{
  "n": 190,
  "rank1": 42,
  "top3": 64,
  "top5": 72,
  "miss": 88,
  "accuracy": 0.221,
  "excluded": {
    "no_gt": 4,
    "non_poi": 6
  }
}
```

---

## 13. 서버/파일 구조 권장안

현재는 `poi-test-data` 루트에 주요 파일이 같이 있다. 향후 구현이 늘어나면 다음 구조를 권장한다.

```text
poi-test-data/
├── README.md
├── POI-EVAL-TOOL-SPEC.md
├── PRD-SRD-dataset-dashboard.md
├── dashboard_config.json
├── eval_set_reconciled.csv
│
├── server.py
├── dataset-overview.html
├── mvp-eval-ui.html
│
├── scripts/
│   ├── match_score.py
│   ├── ingest_dataset.py
│   ├── merge_signals.py
│   ├── eval_baseline.py
│   └── evaluate_combined.py
│
├── probes/
│   ├── ls_mapkit_probe.swift
│   ├── ai_poi_run.swift
│   └── ocr_probe.swift
│
├── results/
│   ├── mapkit/
│   ├── ocr/
│   ├── ai/
│   └── runs/
│
├── photos/
├── linkedspaces-photos/
├── union-city-trip/
└── tools/   # gitignore
```

단, 파일을 옮기기 전에는 `server.py`, HTML fetch 경로, merge script 경로를 먼저 상대경로 기반으로 바꿔야 한다.

---

## 14. 구현 우선순위

## P0 — 목업을 실제 평가 도구로 만드는 최소 작업

### P0-1. `server.py` 경로 정리

현재:

```python
DIRECTORY = "/Users/massis/Desktop/fastblog/poi-test-data"
```

권장:

```python
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
```

### P0-2. `match_score.py` 구현

입력:

```text
eval_set_reconciled.csv
ls_nearby_results.tsv 또는 full candidate TSV
dashboard_config.json
```

출력:

```text
match_raw
match_norm
match_rank_raw
match_rank_norm
match_evidence
```

### P0-3. `/api/matchrate` 구현

평가 결과 탭의 mock `DATA`를 제거하고 live API로 대체한다.

### P0-4. candidate top-K 저장 확장

현재 `top3_wide`만으로는 top-5/top-10 curve를 정확히 만들기 어렵다. MapKit probe 출력에 최소 top10 또는 full 후보를 저장한다.

### P0-5. `mvp-eval-ui.html` 평가 결과 live 연결

현재 mock:

```js
const DATA = { ... }
```

대체:

```js
fetch(`/api/matchrate?dataset=${scope}&mode=${mode}`)
```

---

## P1 — 알고리즘 실행 기능

1. run directory 구조 생성
2. Python predict 계약 실행
3. stdin/stdout 방식의 기타 언어 실행
4. timeout/error handling
5. predictions.tsv 저장
6. scores.json 저장
7. 최근 실행 API 추가

예상 API:

```http
GET  /api/runs
POST /api/runs
GET  /api/runs/<name>/<version>
```

---

## P2 — 데이터셋 ingest 자동화

1. `ingest_dataset.py` 구현
2. EXIF 추출
3. OCR 실행
4. reverse geocoding
5. MapKit probe 실행
6. confidence 기본값 적용
7. 결측 flag 처리
8. CSV append/merge

---

## 15. Definition of Done

### MVP DoD

- [ ] `match_score.py`가 raw/norm rank를 산출한다.
- [ ] `/api/matchrate`가 scope/mode별 metric을 반환한다.
- [ ] `mvp-eval-ui.html` 평가 결과 탭이 mock DATA 없이 live API를 사용한다.
- [ ] rank-1/top-3/top-5/MISS 카드가 live 값으로 표시된다.
- [ ] top-N curve가 live 값으로 표시된다.
- [ ] n과 excluded reason이 항상 표시된다.
- [ ] case analysis에서 raw/norm match evidence를 볼 수 있다.
- [ ] baseline normalized 성능이 확정된다.

### 정직성 DoD

- [ ] raw와 normalized 수치를 구분한다.
- [ ] 제외 행을 분모에서 숨기지 않는다.
- [ ] non-POI는 venue retrieval metric과 분리한다.
- [ ] unresolved/ambiguous는 headline metric에서 제외한다.
- [ ] config 미매핑 값은 warning으로 노출한다.

---

## 16. 열린 결정사항

1. `non_poi`와 `no_venue`를 같은 bucket으로 볼지 분리할지.
2. normalized match threshold 초기값을 어디로 둘지.
3. top-K 후보를 full로 저장할지 top10까지만 저장할지.
4. 알고리즘 실행 결과를 CSV 컬럼에 머지할지, `runs/` 아래 별도 결과로 관리할지.
5. KR dataset은 Kakao Local baseline을 별도 line으로 둘지, MapKit baseline에서 계속 deferred로 둘지.
6. `category`를 알고리즘 입력으로 허용할지. 현재 목업에서는 GT 유래 경고가 있으므로 기본 off가 맞다.

---

## 17. 결론

현재 목업은 단순 UI 스케치가 아니라 최종 도구의 기능 계약을 꽤 구체적으로 담고 있다. 핵심 구조는 다음으로 정리된다.

```text
개요: 현재 데이터셋/신호 상태를 live로 본다.
평가 실행: predict(case) 계약으로 새 알고리즘을 실행한다.
평가 결과: baseline과 알고리즘을 rank/top-k/MISS 및 case analysis로 비교한다.
데이터셋 추가: 사진+GT만 사람이 넣고 나머지는 ingest가 채운다.
```

가장 먼저 구현해야 할 것은 `match_score.py`와 `/api/matchrate`다. 이 두 개가 들어와야 목업의 평가 결과 탭이 실제 의사결정 도구가 된다.
