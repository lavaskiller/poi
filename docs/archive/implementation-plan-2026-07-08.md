# POI 평가 도구 구현 계획

작성일: 2026-07-08  
기준 문서: `poi-test-data/PRD-SRD-dataset-dashboard.md`

## 1. 구현 전에 먼저 확정해야 하는 규격

명세를 바로 코드로 옮기기 전에 먼저 고정해야 하는 것은 UI가 아니라 데이터 계약이다. 이 도구의 핵심은 “이미지 + 사용자가 고른 GT”를 받아 후보 검색과 후보 선택을 분리해서 평가하는 것이므로, 데이터 추가 시점의 입력 형식과 저장 스키마가 흔들리면 이후 지표가 모두 흔들린다.

### 1.1 데이터 추가 입력 단위

데이터 추가는 항상 하나의 `dataset` 아래에 여러 `photo row`를 추가하는 형태로 처리한다.

```text
dataset
└─ rows[]
   ├─ image
   ├─ capture metadata
   ├─ user GT raw
   ├─ GT parse/canonicalization result
   ├─ candidate retrieval result
   └─ selection/evaluation result
```

MVP에서는 사용자가 동일한 구조의 ZIP 파일을 올리는 방식을 1차 입력 규격으로 고정한다. 템플릿 ZIP을 도구에서 먼저 내려받게 하고, 사용자는 그 안의 `photos/`에 이미지를 넣고 `manifest.csv`에 이미지와 GT만 채운 뒤 다시 압축해 업로드한다. 로컬 디렉터리 등록, JSONL/API 입력은 같은 구조가 안정화된 뒤 확장한다.

## 2. 데이터 추가 입력 형식

### 2.1 1차 지원: ZIP upload package

가장 먼저 지원할 입력 형식은 템플릿 기반 ZIP 패키지다.

```text
dataset_slug.zip
└─ dataset_slug/
   ├─ manifest.csv
   ├─ README.md
   └─ photos/
      ├─ IMG_0001.jpg
      ├─ IMG_0002.jpg
      └─ ...
```

도구는 빈 템플릿을 제공한다.

- 템플릿 디렉터리: `poi-test-data/templates/poi-dataset-upload-template/`
- 템플릿 ZIP: `poi-test-data/templates/poi-dataset-upload-template.zip`

사용자는 템플릿의 구조를 바꾸지 않고 다음 두 값만 채우는 것을 원칙으로 한다.

1. `photos/` 아래 이미지 파일
2. `manifest.csv`의 `photo`, `gt_input_raw`

`manifest.csv`의 입력 컬럼은 “사용자가 직접 입력해야 하는 값”과 “도구가 이미지/좌표/provider 조회로 자동 보강해야 하는 값”을 구분한다. 사용자가 직접 제공해야 하는 최소 입력은 `photo`와 `gt_input_raw`뿐이다. `capture_lat`, `capture_lon`, `timestamp`, `country`, `city`는 사용자가 손으로 입력하지 않는다. 도구가 우선 추출·추정하고, 실패한 행만 보정 대상으로 표시한다.

| 컬럼 | 사용자 직접 입력 | 시스템 처리 | 평가상 역할 | 설명 |
|---|---:|---|---|---|
| `photo` | O | ZIP 내부 파일 경로 검증 | 원본 입력 | ZIP 루트 기준 이미지 상대 경로. 예: `photos/IMG_0001.jpg` |
| `gt_input_raw` | O | 입력 형식 파싱 | 정답 원본 | 사용자가 고른 GT 원문. 장소명, URL, place id, 이름+주소 등 허용 |
| `notes` | 선택 | 그대로 저장 | 리뷰 보조 | 사람이 남긴 메모 |
| `capture_lat` | X | EXIF GPS에서 추출. 실패 시 보정 입력 허용 | 검색 중심점 | 후보 검색의 중심 좌표 |
| `capture_lon` | X | EXIF GPS에서 추출. 실패 시 보정 입력 허용 | 검색 중심점 | 후보 검색의 중심 좌표 |
| `timestamp` | X | EXIF 촬영 시각에서 추출. 실패 시 비워둠 | 보조 신호 | 1차 평가는 좌표 우선. 이후 동선/시간 기반 선택 알고리즘에 활용 가능 |
| `country` | X | 좌표 기반 reverse geocode로 추정 | provider 결정 | 한국이면 Kakao Local, 한국 외면 MapKit 기준 평가 |
| `city` | X | 좌표 기반 reverse geocode로 추정 | 필터/분석 | 데이터셋 탐색, 지역별 집계, 리뷰 보조 정보 |
| `username` | X | 로그인/업로드 세션에서 자동 채움 | provenance | 데이터 제공자/라벨러 식별 |

`manifest.csv` 예시:

```csv
photo,gt_input_raw,notes
photos/IMG_0001.jpg,Blue Bottle Coffee Shibuya,optional note
photos/IMG_0002.jpg,https://map.kakao.com/link/map/...,kakao url input
```

업로드 검증 규칙:

- ZIP 안에는 정확히 하나의 dataset root 디렉터리가 있어야 한다.
- `manifest.csv`는 dataset root 바로 아래에 있어야 한다.
- `manifest.csv.photo`는 ZIP 내부의 실제 이미지 파일을 가리켜야 한다.
- 허용 이미지 확장자는 우선 `.jpg`, `.jpeg`, `.png`, `.heic`로 제한한다.
- 같은 `photo`가 중복되면 업로드를 실패시키고 중복 행을 표시한다.
- 이미지에 EXIF GPS가 없으면 행을 삭제하지 않고 `needs_location_review` flag를 부여한다.
- GT 파싱이 실패하면 행을 삭제하지 않고 `needs_gt_review` flag를 부여한다.

### 2.2 허용할 GT 입력 형식

GT는 들어오는 순간 기본적으로 “사용자가 고른 정답”이다. 도구가 판별하는 것은 사용자가 골랐는지가 아니라, 그 원문을 어떻게 평가 provider 기준값으로 바꿀지다.

| `gt_input_type` | 입력 예 | 처리 |
|---|---|---|
| `plain_name` | `Blue Bottle Coffee Shibuya` | 사진 좌표 주변에서 평가 provider로 lookup |
| `provider_url` | Apple Maps/Kakao/Google 공유 URL | URL에서 provider hint, place id, 이름, 좌표를 파싱 |
| `provider_place_id` | Kakao place id, MapKit identifier | 해당 provider 상세 조회 후 평가 provider로 재매칭 |
| `name_with_address` | `블루보틀 성수, 서울 성동구...` | 이름/주소 분리 후 disambiguation에 사용 |
| `name_with_coord` | `Blue Bottle, 35.66, 139.70` | 입력 좌표와 사진 좌표 충돌 여부 확인 |
| `non_poi_text` | `집`, `회사`, `길거리`, `unknown` | 평가 제외 또는 non-POI bucket 처리 |

### 2.3 2차 지원: JSONL/API 입력

ZIP 패키지 규격이 안정화되면 같은 최소 입력 스키마를 JSONL/API로 열어 둔다. JSONL/API에서도 사용자가 직접 보내는 값은 이미지 참조와 GT 원문이 기본이다. 좌표, 국가, 도시, 촬영 시각은 내부 ingest 단계에서 추출·추정한다.

```json
{
  "dataset": "tokyo-trip-2026",
  "photo": "photos/IMG_0001.jpg",
  "photo_url": null,
  "gt_input_raw": "Blue Bottle Coffee Shibuya",
  "notes": ""
}
```

API는 나중에 붙이더라도 내부 ingest는 ZIP/CSV와 JSONL을 같은 row schema로 normalize해야 한다.

## 3. 내부 표준 row schema

현재 `eval_set_reconciled.csv`는 기존 대시보드와 연결되어 있으므로 바로 갈아엎지 않는다. 대신 v1 스키마를 정의하고, 기존 컬럼은 호환 alias로 유지한다.

### 3.1 입력/원본 영역

| 필드 | 설명 |
|---|---|
| `dataset` | 데이터셋 slug |
| `photo` | 이미지 파일명 |
| `photo_url` | 원격 URL이 있을 경우 |
| `capture_lat` | 검색 중심 좌표 latitude |
| `capture_lon` | 검색 중심 좌표 longitude |
| `timestamp` | 촬영 시각 |
| `country` | 국가 코드 또는 국가명 |
| `city` | 도시 |
| `gt_input_raw` | 사용자가 제공한 GT 원문 |
| `user_selected_place_name` | 사용자가 고른 장소명 원본. `gt_input_raw`에서 장소명을 추출하지 못하면 raw와 동일하게 둠 |

### 3.2 GT 파싱/정규화 영역

| 필드 | 설명 |
|---|---|
| `gt_input_type` | `plain_name`, `provider_url`, `provider_place_id`, `name_with_address`, `name_with_coord`, `non_poi_text` |
| `gt_parse_confidence` | `high`, `medium`, `low` |
| `gt_provider_hint` | 입력에서 드러난 provider. 예: `mapkit`, `kakao`, `google` |
| `gt_name_hint` | 입력에서 추출한 장소명 |
| `gt_address_hint` | 입력에서 추출한 주소 |
| `gt_coord_hint_lat` | 입력에 포함된 좌표 latitude |
| `gt_coord_hint_lon` | 입력에 포함된 좌표 longitude |
| `eval_provider` | 한국은 `kakao_local`, 한국 외는 `mapkit` |
| `eval_provider_place_id` | 평가 provider 기준 place id |
| `eval_place_name` | 평가 provider 기준 canonical name |
| `canonicalization_status` | `matched`, `ambiguous`, `not_found`, `non_poi`, `needs_review` |

### 3.3 후보 검색/선택 평가 영역

| 필드 | 설명 |
|---|---|
| `retrieval_provider` | 후보 리스트를 만든 provider |
| `candidate_count` | 후보 총 개수 |
| `candidate_top1_name` | 후보 1위 이름 |
| `gt_rank` | 정답 후보 순위. 없으면 `MISS` |
| `gt_distance_m` | 평가 기준 장소와 후보의 거리 |
| `top_1_hit` | rank-1 hit 여부 |
| `top_3_hit` | top-3 hit 여부 |
| `top_5_hit` | top-5 hit 여부 |
| `top_10_hit` | top-10 hit 여부 |
| `within_25m_count` | 25m 이내 후보 수 |
| `within_25m_hit` | 25m 이내 정답 존재 여부 |
| `within_50m_count` | 50m 이내 후보 수 |
| `within_50m_hit` | 50m 이내 정답 존재 여부 |
| `within_100m_count` | 100m 이내 후보 수 |
| `within_100m_hit` | 100m 이내 정답 존재 여부 |
| `failure_type` | `correct`, `retrieval_failure`, `selection_failure`, `no_gt`, `non_poi`, `needs_review` |

기존 컬럼과의 매핑:

| 기존 컬럼 | v1 필드 |
|---|---|
| `gt_place_name` | `user_selected_place_name` 또는 과도기에는 `eval_place_name` 표시용 alias |
| `app_poi_rank` | `gt_rank` |
| `app_poi_dist_m` | `gt_distance_m` |
| `app_nearby_n_wide` | `candidate_count` |
| `app_nearby_top1` | `candidate_top1_name` |

## 4. 구현 순서

### Phase 0. 문서/스키마 고정

목표: 코드 작성 전에 입력/출력 계약을 고정한다.

작업:

1. `PRD-SRD-dataset-dashboard.md`의 데이터 추가/GT 정규화 섹션을 위 스키마 기준으로 정리한다.
2. `schema/poi_eval_row_v1.json` 또는 `poi_eval_schema.py`를 만든다.
3. 현재 `eval_set_reconciled.csv` 헤더와 v1 필드의 매핑표를 코드로 둔다.
4. 샘플 `examples/manifest.csv`를 만든다.

완료 조건:

- 새 데이터셋 입력에 필요한 필수/선택 컬럼이 문서와 코드에서 동일하다.
- 기존 CSV를 v1 row로 읽었을 때 누락/alias가 명확히 표시된다.

### Phase 1. Ingest validator 구현

목표: 데이터 추가 전에 입력 오류를 사람이 고칠 수 있게 한다.

작업:

1. `tools/validate_manifest.py` 추가.
2. 필수 컬럼 검사.
3. 이미지 파일 존재 검사.
4. 좌표 형식 검사.
5. `gt_input_raw` 공백/결측 검사.
6. EXIF 좌표/시각 추출 fallback 구현.
7. 결과를 `ingest_report.json`과 `ingest_report.csv`로 저장.

완료 조건:

```text
python3 tools/validate_manifest.py --dataset path/to/dataset_slug
```

실행 시 다음이 나온다.

- import 가능 행 수
- 차단 오류 행 수
- 경고 행 수
- no_coord / no_gt / missing_photo / bad_timestamp 등 flags

### Phase 2. GT parser 구현

목표: `gt_input_raw`를 표준 GT hint 필드로 분해한다.

작업:

1. `tools/parse_gt_input.py` 추가.
2. URL provider 판별: Kakao Map, Apple Maps, Google Maps 우선.
3. 좌표 포함 여부 파싱.
4. 이름+주소 분리 규칙 구현.
5. `non_poi_text` 사전 정의.
6. `gt_input_type`, `gt_provider_hint`, `gt_name_hint`, `gt_address_hint`, `gt_coord_hint_*`, `gt_parse_confidence` 생성.

완료 조건:

- 같은 입력은 항상 같은 parse 결과를 만든다.
- 파싱 실패는 행 삭제가 아니라 `needs_review` flag로 남긴다.

### Phase 3. 평가 provider 결정 및 canonicalization

목표: 사용자 GT 원본을 지역별 평가 provider 기준으로 맞춘다.

작업:

1. `eval_provider` 결정 함수 구현.
   - `country == KR` 또는 reverse geocode 결과 한국: `kakao_local`
   - 그 외: `mapkit`
2. Kakao Local lookup adapter 구현.
3. MapKit lookup/probe adapter 정리.
4. 좌표 반경 기반 disambiguation 규칙 구현.
5. 복수 후보/미발견/비POI 상태를 `canonicalization_status`로 저장.

완료 조건:

- `eval_place_name`과 `eval_provider_place_id`가 생성된다.
- 실패 케이스는 `not_found`, `ambiguous`, `needs_review`, `non_poi`로 구분된다.

### Phase 4. 후보 검색 결과 저장 모델 정리

목표: 검색 실패와 선택 실패를 분리할 수 있도록 후보 리스트를 원본 그대로 저장한다.

작업:

1. 후보 리스트 저장 포맷 정의: CSV보다는 JSONL 권장.
2. 각 후보에 `rank`, `name`, `provider_place_id`, `lat`, `lon`, `distance_m`, `category`, `address` 저장.
3. 기존 `ls_nearby_results.tsv`를 v1 candidate JSONL로 변환하는 migration script 작성.
4. top-N과 within-Xm 계산은 후보 JSONL에서 파생한다.

완료 조건:

- 후보가 없어서 실패한 경우와 후보 안에 있는데 선택을 못 한 경우를 코드로 구분할 수 있다.

### Phase 5. Metrics engine 구현

목표: 명세의 핵심 지표를 재현 가능한 함수로 계산한다.

작업:

1. `tools/compute_metrics.py` 추가.
2. `top_1_hit`, `top_3_hit`, `top_5_hit`, `top_10_hit` 계산.
3. `within_25m/50m/100m_count` 계산.
4. `within_25m/50m/100m_hit` 계산.
5. `failure_type` 계산.
6. dataset/country/provider/category별 rollup 계산.

완료 조건:

- 같은 입력 row와 candidate list에서 항상 같은 metrics가 나온다.
- dashboard API가 파일을 직접 해석하지 않고 metrics output을 읽을 수 있다.

### Phase 6. 알고리즘 선택 실험 구조 구현

목표: 2차 목표인 “후보 리스트 안에서 어떤 후보를 고를지”를 실험 가능한 구조로 만든다.

작업:

1. 알고리즘 입력 인터페이스 정의.
   - image-derived text/OCR
   - capture lat/lon
   - candidate top-K
   - category hint
   - timestamp/city/country
2. baseline selectors 구현.
   - nearest candidate
   - name/OCR string match
   - category-aware scoring
3. selector 결과 저장.
   - `selector_name`
   - `selector_version`
   - `selected_candidate_rank`
   - `selected_candidate_id`
   - `is_correct`
4. 기존 목업의 평가 실행 탭을 실제 run list와 연결.

완료 조건:

- provider 후보 리스트는 동일하게 고정하고 selector만 바꿔서 비교할 수 있다.

### Phase 7. Dashboard/API 정리

목표: 현재 `server.py`, `dataset-overview.html`, `mvp-eval-ui.html`를 v1 output에 맞춘다.

작업:

1. `/api/overview`가 v1 schema coverage를 보여주도록 수정.
2. `/api/records`가 `eval_place_name`, `user_selected_place_name`, `failure_type`, top-10, within-Xm 필드를 내려주도록 수정.
3. 데이터셋 추가 탭은 실제 validator 결과를 표시하도록 연결.
4. 평가 실행 탭은 selector runs를 표시하도록 연결.
5. 평가 결과 탭은 raw/normalized를 명확히 구분한다.

완료 조건:

- UI의 모든 숫자가 mock 상수가 아니라 파일/metrics output에서 온다.

## 5. 먼저 판단해야 할 열린 결정

아래는 코드 작성 전에 결정해야 하는 항목이다.

| 항목 | 추천안 | 이유 |
|---|---|---|
| 데이터 추가 1차 형식 | 템플릿 기반 ZIP 패키지 | 사용자가 구조를 고민하지 않게 하고, 이미지와 GT를 항상 같은 단위로 업로드하게 함 |
| 내부 candidate 저장 | JSONL | 후보 리스트는 nested 구조라 CSV보다 JSONL이 안전함 |
| 기존 `gt_place_name` 유지 여부 | 과도기 alias로 유지 | 현재 dashboard/server가 이 컬럼을 읽고 있음 |
| `user_selected_place_name` 생성 방식 | `gt_input_raw`에서 이름을 추출하되 실패 시 raw 보존 | GT는 사용자 선택값이라는 전제를 유지 |
| 한국 판별 | country 우선, 없으면 좌표 reverse geocode | provider 결정에 필수 |
| 반경 지표 기본값 | 25m, 50m, 100m | 밀집 지역/일반 지역을 동시에 보기 좋음 |
| top-N 기본값 | 1, 3, 5, 10 | 기존 rank 지표와 top-10 요구를 모두 포함 |
| canonicalization 실패 처리 | 삭제하지 않고 `needs_review` | 평가셋 품질 관리에 필요 |

## 6. 바로 다음 액션

1. `PRD-SRD-dataset-dashboard.md`에 ZIP 입력 형식과 v1 row schema를 통합한다.
2. `poi-test-data/templates/poi-dataset-upload-template.zip`을 데이터 추가 화면에서 다운로드할 수 있게 연결한다.
3. `poi-test-data/tools/validate_upload_package.py`를 만든다.
4. 기존 `eval_set_reconciled.csv`를 대상으로 v1 schema coverage report를 만든다.
5. 그 결과를 보고 기존 CSV 컬럼명을 유지할지, 새 컬럼을 추가할지 결정한다.

## 7. 구현 시 주의점

- GT는 기본적으로 사용자 선택값이다. 출처 의심이나 user/system 구분을 1차 모델에 넣지 않는다.
- 원본 GT와 평가 provider 기준값은 반드시 분리한다.
- 검색 실패와 선택 실패는 같은 실패로 묶지 않는다.
- 좌표/GT/후보 결측 행은 삭제하지 않고 flag로 남긴다.
- provider 교체 실험과 selector 알고리즘 실험은 분리한다.
- dashboard 수치는 mock 상수가 아니라 재계산 가능한 output 파일에서 읽어야 한다.
