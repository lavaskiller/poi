# POI 평가 도구 — API 명세서

> 서버: `server.py` (Python 표준 라이브러리 `http.server`, 로컬 단일 사용자).
> UI는 리포지토리에서, 데이터셋 파일은 `POI_DATA_DIR`에서 읽는다.
> 페이지별 기능은 [FUNCTIONAL-SPEC.md](FUNCTIONAL-SPEC.md) 참고. 스키마는 2026-07-10 실측 응답 기준.

## 실행

```bash
POI_DATA_DIR=/Users/massis/Desktop/poi-data POI_PORT=8488 python3 /Users/massis/Desktop/poi/server.py
# 기본 포트 8488(POI_PORT 미지정 시 8420). Base URL = http://127.0.0.1:<PORT>
```

## 공통 규약

- 응답: `application/json; charset=utf-8`, `Cache-Control: no-store`, `ensure_ascii=false`(한글 그대로).
- 데이터 소스: `POI_DATA_DIR`의 `eval_set_reconciled.csv`, `dashboard_config.json`(없으면 repo 폴백), `generated/{mapkit,kakao_local}_candidates.jsonl`, 각종 `*.tsv`.
- 에러: 처리 중 예외는 `500 {"error": "<메시지>"}`. 엔드포인트별 상태코드는 아래.

## 엔드포인트 요약

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/` | `302 → /mvp-eval-ui.html` |
| GET | `/api/overview` | 데이터셋 구조·집계 (①탭) |
| GET | `/api/records` | 케이스 레코드 목록 (③ 케이스 분석) |
| GET | `/api/matchrate` | 후보 검색 커버리지 지표 (③) |
| GET | `/api/runs` | 저장된 알고리즘 실행 목록 (②/③) |
| POST | `/api/run` | 알고리즘 제출·채점 (②) |
| POST | `/api/validate-upload-package` | 데이터셋 ZIP 검증 (④) |
| GET | 정적 | `mvp-eval-ui.html/.js`, `dataset-overview.html`, `spec-viewer.html`, `index.html` (repo) · `/linkedspaces-photos/*`, `/photos/*`, `/templates/*` (데이터/repo) |

---

## GET `/api/overview`

데이터셋 구조·집계. 파라미터 없음.

**응답(200)** — 주요 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `total` | int | 총 행 수 |
| `n_columns` | int | 컬럼 수 |
| `photo_present` / `gt_present` | int | 사진 참조 / GT 있는 행 수 |
| `palette` | string[] | 색 팔레트 키 |
| `sources` | object[] | `{key,count,label,color,owner,source_type,desc,known}` |
| `confidence` | object[] | `{key,count,color,desc,members:[[raw,cnt]],known}` (canonical tier) |
| `countries` | object[] | `{key,count,flag}` |
| `categories` | [string,int][] | 상위 12개 `[이름,수]` |
| `category_total_kinds` | int | 카테고리 종류 수 |
| `fill` | object | `{컬럼명: 비어있지_않은_행수}` |
| `schema` | object[] | `{group,role_key,role_label,role_tag,fill,cols[],desc,known}` |
| `samples` | object | `{dataset: {대표 행 필드…}}` |
| `pipeline` | object[] | `{label,extracted,merged,total,status(wait/run/done),note}` |
| `config_warnings` | string[] | config 미정의 항목 경고 (빈 배열이 정상) |

---

## GET `/api/records`

케이스 레코드 목록 (③ 케이스 분석 좌측 리스트/상세).

**쿼리:** `dataset` = `all`(기본)·`linkedspaces`·`union-city`·`vancouver`.

**응답(200):** 레코드 배열.

`gt`는 provider별 정규 정답명(`gt_mapkit`/`gt_kakao`)이며, 비면 `input_place_name`으로 폴백한 **유효 GT**다. `input_place_name`은 사용자 원본 입력을 그대로 노출한다.

```json
[{
  "dataset": "vancouver",
  "photo": "IMG_6133.jpeg",
  "photo_url": "/photos/IMG_6133.jpeg",
  "gt": "",
  "input_place_name": "",
  "gt_confidence": "synthetic_unconfirmed",
  "category": "cafe",
  "lat": "49.282753",
  "lon": "-123.1101",
  "ocr_text": "",
  "baseline_pick": "Public Toilet@8m",
  "rank": "MISS",
  "n_wide": "50",
  "dist": "-",
  "candidates": [{"name": "…", "dist": "…"}],
  "outcome": "no_gt",
  "oc_label": "no_gt"
}]
```

`outcome` ∈ `correct`(정답)·`selection`(식별실패, rank>1)·`retrieval`(검색실패, MISS)·`non_poi`·`deferred`·`no_gt`·`other`.

---

## GET `/api/matchrate`

후보 검색 커버리지 지표(식별 정확도 아님). 한국은 Kakao 데이터 확보 전까지 홀드아웃.

**쿼리:** `dataset`(위와 동일) · `mode` = `exact`(기본)·`normalized`.

**응답(200):**

```json
{
  "dataset": "all", "mode": "exact",
  "matching_policy": {
    "primary": "same-provider exact string equality",
    "korea_provider": "kakao_local (held out until Kakao data is available)",
    "non_korea_provider": "mapkit",
    "provider_place_id": "nullable/fallback; not required for MVP scoring"
  },
  "counts": {
    "rows": 280, "excluded_non_poi": 6, "eligible": 238, "evaluated": 228,
    "rank1": 38, "top3": 59, "top5": 68, "miss": 143,
    "selection_failure": 47, "search_failure": 143,
    "excluded_no_gt": 8, "no_provider_data": 10, "excluded_korea_pending_kakao": 28
  },
  "n": 228, "rank1": 38, "top3": 59, "top5": 68, "miss": 143,
  "rank1_rate": 0.1667, "top3_rate": 0.2588, "top5_rate": 0.2982, "miss_rate": 0.6272,
  "by_provider": { "mapkit": { "rows": 252, "evaluated": 228, "rank1": 38, "…": "…" },
                   "kakao_local": { "rows": 28, "evaluated": 0, "…": 0 } },
  "by_dataset":  { "linkedspaces": {"…": "…"}, "union-city": {"…": "…"}, "vancouver": {"…": "…"} },
  "cases": [
    { "dataset": "linkedspaces", "photo": "…", "gt": "Liberty Burger",
      "country": "United States", "provider": "mapkit",
      "status": "correct", "rank": 1, "source": "legacy_app_poi_rank" }
  ]
}
```

- `n` = 채점된 행 수. `rank1/top3/top5` = GT가 top-N 후보에 포함된 수, `miss` = 후보에 GT 없음.
- `cases[].status` ∈ `correct`·`selection_failure`·`search_failure`·`no_provider_data`·`excluded_non_poi`·`excluded_no_gt`·`excluded_korea_pending_kakao`. `rank`는 정수·`"MISS"`·`null`.

---

## GET `/api/runs`

저장된 알고리즘 실행(`generated/runs/*.json`) 요약 목록. 파라미터 없음.

**응답(200):**

```json
{ "runs": [
  { "name": "spec-probe", "safe_name": "spec-probe", "version": 1,
    "scope": "vancouver", "mode": "exact", "params": ["nearby_candidates"],
    "lang": "python", "created_at": "2026-07-10T12:26:58",
    "n_eligible": 11, "correct": 2, "accuracy_pct": 18 }
] }
```

---

## POST `/api/run`

알고리즘 제출 → eval set 실행 → 채점 → 버전 저장. 스크립트는 격리 서브프로세스에서 실행(로컬용).

**요청 본문 (JSON):**

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | string | 테스트 이름(자동 버저닝 키) |
| `script_text` | string | 제출 스크립트 전체 |
| `lang` | string | `python`(기본) 등 |
| `scope` | string | `all`·`linkedspaces`·`union-city`·`vancouver` |
| `mode` | string | `exact`(기본)·`normalized` |
| `params` | string[] | 입력 파라미터 키. 예: `["nearby_candidates"]` |
| `save_mode` | string | `auto`(다음 버전)·`v1`·`v2`(덮어쓰기) |

**`predict(case)` 계약** (Python):
```python
def predict(case) -> str:      # 예측 장소명, 기권은 ""
    # 반환: str  또는  {"prediction": "...", "reason": "..."}
    ...
```
- 그 외 언어: stdin으로 case JSON → stdout으로 예측 출력.
- `case`는 **선택한 params에 해당하는 필드만** 노출하며 **GT를 절대 포함하지 않는다**. `photo`는 항상 포함.

| `case` 필드 | 타입 | params 키 |
|---|---|---|
| `photo` | string | (항상) |
| `lat`,`lon`,`timestamp` | string | `lat,lon` |
| `ocr_text` | string | `ocr_text` |
| `vlm_caption` | string | (미추출, 현재 `""`) |
| `nearby_candidates` | `[{name,rank,distance_m}]` (근접순) | `nearby_candidates` |
| `geocode` | `{city,country,address}` | `city,country,address` |
| `category_hint` | string | `category` |

**응답(200):**
```json
{ "ok": true, "name": "spec-probe", "safe_name": "spec-probe", "version": 1,
  "created_at": "2026-07-10T12:26:58", "scope": "vancouver", "mode": "exact",
  "params": ["nearby_candidates"], "lang": "python",
  "metrics": { "n_eligible": 11, "correct": 2, "abstained": 0, "errored": 0,
    "accuracy": 0.1818, "accuracy_pct": 18,
    "by_dataset": { "vancouver": { "n": 11, "correct": 2, "accuracy": 0.1818 } } },
  "n_cases": 11 }
```
- 채점: `예측 == GT`(공급원 exact). 한국/`non_poi`/GT 없음 row는 자동 홀드아웃 → `n_eligible`에서 제외.
- 저장: `generated/runs/<safe_name>__v<version>.json`.

**상태코드:** `200` 성공 · `400` JSON 파싱 실패 · `422` 제출 오류(`RunError`) · `500` 기타.

---

## POST `/api/validate-upload-package`

데이터셋 업로드 ZIP을 ingest 전에 구조 검증(④). 본문 = ZIP 바이너리(`Content-Type: application/zip`, 최대 500MB).

**응답:**
```json
{ "ok": false,
  "dataset_root": "poi-dataset-upload-template",
  "manifest_path": "poi-dataset-upload-template/manifest.csv",
  "row_count": 0, "image_count": 0,
  "errors": [{ "code": "manifest_empty", "message": "manifest.csv has no data rows" }],
  "warnings": [], "row_flags": [] }
```

**상태코드:** `200` 검증 통과(`ok:true`) · `422` 검증 실패(`ok:false`, `errors[]`) · `400` 잘못된 ZIP / 빈 업로드 / 잘못된 `Content-Length` · `413` 500MB 초과 · `500` 기타. 빈 템플릿은 데이터 행이 없어 `manifest_empty`로 정상적으로 거부된다.

---

## 정적 라우트

- **UI/문서(리포지토리에서 서빙):** `/mvp-eval-ui.html`, `/mvp-eval-ui.js`, `/dataset-overview.html`, `/spec-viewer.html`, `/index.html`, `/templates/*`.
- **데이터 파일(`POI_DATA_DIR`에서 remap):** `/linkedspaces-photos/<file>`, `/photos/<file>`. (union-city 사진은 로컬 미서빙.)
- `POI_DATA_DIR`이 repo와 다를 때 `translate_path`가 데이터 prefix만 `POI_DATA_DIR`로 재매핑하므로 UI는 항상 최신, 데이터는 워크스페이스에서 읽는다.
