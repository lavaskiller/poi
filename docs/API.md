# POI 평가 도구 — API 명세서

> 서버: `server.py` (Python 표준 라이브러리 `http.server`, 로컬 단일 사용자).
> UI는 리포지토리에서, 데이터셋 파일은 `POI_DATA_DIR`에서 읽는다.
> 페이지별 기능은 [functional-spec.md](functional-spec.md) 참고. 스키마는 2026-07-10 실측 응답 기준.

## 실행

```bash
POI_DATA_DIR=/absolute/path/to/poi-data POI_PORT=8420 python3 server.py
# 기본 포트 8420. Base URL = http://127.0.0.1:<PORT>
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
| GET | `/api/datasets` | 데이터셋 및 신호별 채움 현황 (④) |
| GET | `/api/runs` | 저장된 알고리즘 실행 목록 또는 한 실행의 상세 (②/③) |
| DELETE | `/api/runs` | 이름·버전으로 저장된 실행을 영구 삭제 (③) |
| GET | `/api/jobs` · `/api/jobs/status?job_id=…` | 비동기 작업 및 상태 (④) |
| POST | `/api/run` | 알고리즘 제출·채점 (②) |
| POST | `/api/validate-upload-package` | 데이터셋 ZIP 검증 (④) |
| POST | `/api/ingest` | ZIP을 비동기 ingest 작업으로 등록 (④) |
| GET | 정적 | `mvp-eval-ui.html/.js`, `/examples/*`, `/templates/*` (repo) · 구성된 사진 폴더 (data root) |

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

`gt`는 provider별 정규 정답명(`gt_mapkit`/`gt_kakao`)이 **canonical**일 때만 값이 있다. provider GT가 비어 있거나 `NON_MAPKIT`, `SIM_MAPKIT`, `NON_KAKAO`, `SIM_KAKAO`, `KOR`, `NON_KR` 같은 resolution sentinel이면 `gt`는 빈 문자열이고 `gt_status`가 이유를 나타낸다. `input_place_name`은 사용자 원본 입력을 그대로 노출할 뿐, GT로 폴백하지 않는다.

```json
[{
  "dataset": "sample",
  "photo": "IMG_0001.jpeg",
  "photo_url": "/photos/IMG_0001.jpeg",
  "gt": "",
  "gt_status": "no_gt",
  "provider": "mapkit",
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
  "oc_label": "GT 제외: no_gt"
}]
```

`outcome` ∈ `correct`(정답)·`selection`(식별실패, rank>1)·`retrieval`(검색실패, MISS)·`non_poi`·`deferred`·`no_gt`·`non_mapkit`·`sim_mapkit`·`non_kakao`·`sim_kakao`·`other_provider_marker`·`korea_pending_kakao`. 후자의 GT-resolution 상태들은 채점 대상이 아니다.

---

## GET `/api/matchrate`

후보 검색 커버리지 지표(식별 정확도 아님). 한국은 Kakao 데이터 확보 전까지 홀드아웃이며, provider-canonical GT가 아닌 resolution sentinel/빈 GT도 홀드아웃이다.

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
    "rows": 280, "gt_canonical": 85, "gt_non_mapkit": 139,
    "gt_sim_mapkit": 14, "gt_no_gt": 42,
    "excluded_non_poi": 6, "excluded_non_mapkit": 139,
    "excluded_sim_mapkit": 14, "excluded_no_gt": 8,
    "excluded_korea_pending_kakao": 28, "eligible": 85, "evaluated": 80,
    "rank1": 29, "top3": 45, "top5": 54, "top10": 62,
    "top20": 64, "top50": 65, "miss": 15,
    "selection_failure": 36, "search_failure": 15, "no_provider_data": 5
  },
  "n": 80, "rank1": 29, "top3": 45, "top5": 54,
  "top10": 62, "top20": 64, "top50": 65, "miss": 15,
  "rank1_rate": 0.3625, "top3_rate": 0.5625, "top5_rate": 0.675,
  "top10_rate": 0.775, "top20_rate": 0.8, "top50_rate": 0.8125,
  "miss_rate": 0.1875,
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

- `counts.gt_<status>`는 provider GT 품질 분포다. `canonical`만 eligible이다. `excluded_*`와 `no_provider_data`를 함께 보면 전체 행 → canonical GT → 실제 후보 데이터가 있는 평가 분모를 추적할 수 있다.
- `n` = 실제 후보 데이터가 있어 채점된 행 수. `rank1/top3/top5/top10/top20/top50`은 GT가 저장된 rank 기준 top-N에 포함된 수이며 누적이다. `miss` = 후보 결과에 GT 없음.
- 현재 rank의 출처는 MapKit probe의 wide 250m 결과(`ls_nearby_results.tsv`)이며, strict probe 반경은 80m이다. 후보는 API relevance가 아니라 사진 좌표까지의 거리 오름차순으로 재정렬한다. fresh unique-coordinate 요청에는 1.5초 간격을 두고, wide가 비면 cooldown 후 재시도한다.
- 새 MapKit probe 출력은 wide 결과 전체를 JSON으로 보존하며 `category`, `provider_place_id`(지원 OS), 후보 좌표, 거리를 포함한다. `tools/match_score.py --convert-mapkit-tsv`가 이를 flat candidate JSONL로 변환한다. 구형 로컬 snapshot은 top-3 위주이고 metadata가 비어 있을 수 있으며, 제출 알고리즘은 빈 metadata를 허용해야 한다.
- `cases[].status` ∈ `correct`·`selection_failure`·`search_failure`·`no_provider_data`·`excluded_non_poi`·`excluded_no_gt`·`excluded_non_mapkit`·`excluded_sim_mapkit`·`excluded_korea_pending_kakao`. `rank`는 정수·`"MISS"`·`null`.

---

## GET `/api/runs`

저장된 알고리즘 실행(`generated/runs/*.json`) 요약 목록. 파라미터 없이 호출한다.

**응답(200):**

```json
{ "runs": [
  { "name": "spec-probe", "safe_name": "spec-probe", "version": 1,
    "scope": "vancouver", "mode": "exact", "params": ["nearby_candidates"], "candidate_limit": 10,
    "lang": "python", "created_at": "2026-07-10T12:26:58",
    "script_sha256": "<64-char SHA-256>",
    "evaluation_set_sha256": "<64-char SHA-256>",
    "evaluation_set_sha256_derived": false,
    "data_snapshot_sha256": "<64-char SHA-256>",
    "n_eligible": 11, "correct": 2, "abstained": 0, "errored": 0, "accuracy_pct": 18,
    "duration_ms": 18340.2,
    "latency_ms": {"mean": 12.4, "p50": 9.1, "p95": 28.0, "max": 110.2, "n": 11},
    "runtime": {"device_class":"desktop_host", "platform":"…", "machine":"…", "python":"…"} }
] }
```

`script_sha256` identifies byte-identical submitted code; old persisted records derive it from their stored script text. Equal accuracy is not evidence that two executions are different algorithms.

`evaluation_set_sha256` identifies the ordered evaluation cohort `(dataset, photo, gt)`. Direct run comparison requires the same cohort and scoring mode. `data_snapshot_sha256` hashes the CSV, config, and candidate files used for the run; optional provider files that are absent are recorded as missing rather than failing the run. Legacy runs without these fields remain readable, but the UI warns that comparison compatibility is incomplete.

`duration_ms` is the full submitted-process wall time, including process startup. `latency_ms` summarizes available per-case `predict()` call wall times (`mean`, `p50`, `p95`, `max`, `n`); case detail has an individual `latency_ms`. These and `runtime` are measurements of the evaluation host, explicitly **not** mobile-device measurements. Legacy records can omit them.

### GET `/api/runs?name=<name>&version=<positive integer>`

Returns the complete persisted record for one logical run, including `metrics`, case-level `cases`, and the submitted `script_text`. Both selectors are required. The server resolves a generated filename internally and verifies the record's stored name/version, so a slug collision cannot access another run.

This is a local single-user API: run detail may contain submitted local code and case metadata. Do not expose it to untrusted clients.

### DELETE `/api/runs?name=<name>&version=<positive integer>`

Permanently removes exactly one persisted run JSON after the same logical-identity check. It does not delete source scripts outside `generated/runs/`, datasets, photos, or candidate data.

**Response (200):** `{ "ok": true, "deleted": {"name":"spec-probe","version":1,"run_id":"spec-probe__v1"} }`.

**Status codes for run detail/deletion:** `400` missing or malformed selector · `404` no matching run (including a safe-slug path attempt that does not name a stored record) · `500` read/delete failure.

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
| `candidate_limit` | integer \| null | nearby 후보 상한. `1`–`250`; `null`은 전체. `nearby_candidates` 선택 시 적용 |
| `save_mode` | string | `auto`(다음 버전)·`v1`·`v2`(덮어쓰기) |

**`predict(case)` 계약** (Python):
```python
def predict(case) -> str:      # 예측 장소명, 기권은 ""
    # 반환: str  또는  {"prediction": "...", "reason": "..."}
    ...
```
- 그 외 언어: stdin으로 case JSON → stdout으로 예측 출력.
- `case`는 **선택한 params에 해당하는 필드만** 노출하며 **GT를 절대 포함하지 않는다**. `photo`는 항상 포함. `params` 생략은 기본 전체 신호, 명시적인 `[]`는 추가 신호 없음이다.

| `case` 필드 | 타입 | params 키 |
|---|---|---|
| `photo` | string | 사진 참조 ID/상대 경로 (항상; 이미지 바이트나 URL은 아님) |
| `lat`,`lon`,`timestamp` | string | `lat,lon` |
| `ocr_text` | string | `ocr_text` |
| `vlm_caption` | string | (미추출, 현재 `""`) |
| `nearby_candidates` | `[{name,rank,distance_m,category,provider_place_id,lat,lon}]` (근접순; legacy 데이터의 메타데이터는 빈 값) | `nearby_candidates` |
| `geocode` | `{city,country,address}` | `city,country,address` |


**응답(200):**
```json
{ "ok": true, "name": "spec-probe", "safe_name": "spec-probe", "version": 1,
  "created_at": "2026-07-10T12:26:58", "scope": "vancouver", "mode": "exact",
  "params": ["nearby_candidates"], "candidate_limit": 10, "lang": "python",
  "metrics": { "n_eligible": 11, "correct": 2, "abstained": 0, "errored": 0,
    "accuracy": 0.1818, "accuracy_pct": 18,
    "by_dataset": { "vancouver": { "n": 11, "correct": 2, "accuracy": 0.1818 } },
    "duration_ms": 18340.2,
    "latency_ms": { "mean": 12.4, "p50": 9.1, "p95": 28.0, "max": 110.2, "n": 11 },
    "runtime": { "device_class": "desktop_host", "notes": "Host-side wall time; not mobile runtime." } },
  "n_cases": 11 }
```
- 채점: `예측 == GT`(공급원 exact). 한국/Kakao, `non_poi`, 빈 provider GT 및 provider resolution sentinel은 자동 홀드아웃 → `n_eligible`에서 제외. raw `input_place_name`은 GT 대체값이 아니다.
- 저장: `generated/runs/<safe_name>__v<version>.json`.

**상태코드:** `200` 성공 · `400` JSON 본문/`params` 타입 오류 · `422` 제출 또는 `candidate_limit` 검증 오류(`RunError`) · `500` 기타.

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

- **UI/공개 리소스(리포지토리에서 서빙):** `/mvp-eval-ui.html`, `/mvp-eval-ui.js`, `/examples/*`, `/templates/*`.
- **데이터 파일(`POI_DATA_DIR`에서 remap):** 기본 사진 prefix(`/linkedspaces-photos/*`, `/photos/*`, `/union-city-trip/*`, `/generated/*`)와 `dashboard_config.json > sources.*.photo_dir`에 등록된 사진 폴더. URL 인코딩된 중첩 경로도 지원한다.
- `POI_DATA_DIR`이 repo와 다를 때 `translate_path`가 허용된 데이터 prefix만 데이터 루트로 재매핑하므로 UI는 항상 최신이며, 임의 경로를 데이터 루트에서 공개하지 않는다.
