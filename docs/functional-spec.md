# POI 평가 도구 — 기능 명세서 (페이지별)

> 대상: `mvp-eval-ui.html` (단일 페이지 · 4탭) + 보조 페이지.
> 모든 수치는 서버 API 실측이며 목업 값이 없다. 코드=`~/Desktop/poi`, 데이터=`~/Desktop/poi-data` (`POI_DATA_DIR`).
> API 상세는 [API-SPEC.md](API-SPEC.md) 참고. 최종 갱신 2026-07-10.

---

## 0. 진입 · 페이지 구성

| 페이지 | 파일 | 역할 |
|---|---|---|
| 진입 | `GET /` | `302 → /mvp-eval-ui.html` (서버 리다이렉트) |
| **메인 툴** | `mvp-eval-ui.html` + `mvp-eval-ui.js` | 4탭 단일 페이지 앱 (본 문서의 핵심) |
| 개요 풀버전 | `dataset-overview.html` | ①탭의 상세판 — 스키마 테이블·툴팁·경고배너·라이브 집계 |
| 명세서 뷰어 | `spec-viewer.html` | 리포지토리의 `.md` 스펙 문서를 브라우저에서 렌더 |
| 정적 랜딩 | `index.html` | 구 대시보드 랜딩(정적) |

메인 툴 상단 탭: **① 개요 · ② 평가 실행 · ③ 평가 결과 · ④ 데이터셋 추가.** 탭 전환은 클라이언트에서 뷰 토글(`.tabs button` → `.view.on`), 각 탭은 진입 시 해당 API를 `no-store`로 호출한다.

**핵심 개념**
- **후보 검색(retrieval)**: 후보 공급원(MapKit 등)이 GT 장소를 후보 리스트에 넣었는가 → 알고리즘이 고를 수 있는 상한.
- **식별(selection) 정확도**: 제출된 알고리즘의 `예측 == GT` 비율 → 실제 성능 지표.
- **매칭 정책**: 같은 공급원 내 exact 문자열 일치. 한국 row는 Kakao Local 데이터 확보 전까지 홀드아웃. `non_poi`/GT 없음 row는 자동 제외.
- **GT 모델(provider별)**: `input_place_name`(사용자 원본 입력) + `gt_mapkit`·`gt_kakao`(provider 정규 정답명). 채점은 행의 provider에 맞는 GT 컬럼을 사용 — 비한국→`gt_mapkit`, 한국→`gt_kakao`. 두 컬럼은 MapKit/Kakao 재조회로 채우며, **비어 있으면 `input_place_name`으로 폴백**(재조회 전까지 기존 지표 유지). Kakao 데이터가 없어 `gt_kakao`는 현재 전부 빈 상태.

---

## ① 개요 (Overview) — `GET /api/overview`

데이터셋의 구조·규모·신호 채움 현황을 한눈에 보여주는 대시보드.

**기능**
1. **KPI 4종** — 총 행 수 · GT 라벨 있는 행 · 사진 참조 있는 행 · 국가 수.
2. **출처(provenance)** — dataset별 행 수·색·소유자·소스 타입. config에 없는 소스는 경고로 노출.
3. **신뢰등급(채점 취급)** — 원시 `gt_confidence`를 canonical tier(`user_selected`/`non_poi` 등)로 롤업, tier별 행 수·설명·구성원(raw 값) 표시.
4. **국가 분포** — 국기 + 행 수.
5. **신호 파이프라인** — 신호별(GPS·OCR·베이스라인·컬럼 등) 추출/머지 진행 상태 막대. 상태 `wait`(미착수)·`run`(추출됐으나 CSV 미머지)·`done`.
6. **한 행의 구조 테이블** — 필드(그룹) → 역할(입력신호/라벨/메타) → 채움률 → 추출 방법. "채움 낮으면 그 신호를 쓰는 알고리즘 상한도 낮다"는 입력벡터 관점 제공.

**표시 원칙** — 구조는 실데이터에서, 라벨/그룹/설명은 `dashboard_config.json`에서. config에 없는 컬럼·소스·tier는 버리지 않고 `config_warnings`로 표면화.

---

## ② 평가 실행 (Run) — `POST /api/run` · `GET /api/runs`

알고리즘 스크립트를 제출 → eval set 전체 실행 → 채점 → ③에 실측 막대로 반영.

**기능**
1. **실행 설정** — 테스트 이름(이름 같으면 자동 버저닝) · 저장 모드(`auto`=다음 버전 / `v1`·`v2` 덮어쓰기) · 스코프(전체/linkedspaces/union-city/vancouver).
2. **입력 파라미터 선택** — 함수가 받을 신호를 체크. `nearby_candidates`엔 top-K(3/5/10/전체) 선택 + 각 K의 GT 커버리지(%) 표시. 각 파라미터의 추출 방법도 함께 노출.

   | UI 파라미터 | `case` 필드 | 추출 방법(현재) |
   |---|---|---|
   | 좌표 `lat,lon` | `lat`,`lon` | EXIF |
   | `ocr_text` | `ocr_text` | Vision VNRecognizeTextRequest |
   | 주변 후보 `nearby_candidates` | `nearby_candidates[]` | MapKit MKLocalPointsOfInterest |
   | `city,country,address` | `geocode{}` | 지오코딩 |
   | `category` | `category_hint` | GT 파생 |

3. **사용 방법 스니펫** — 선택한 입력을 스크립트에서 불러오는 예시 코드 자동 생성.
4. **예측 함수 첨부** — `predict(case)` 계약을 구현한 파일 업로드(`.py` 외 언어는 stdin JSON → stdout 예측). **▶ 실행**.
5. **최근 실행 테이블** — 이름·버전·스크립트·입력·스코프·rank-1(정확도)·상태.

**채점 규약** — `예측 == GT`, 후보검색과 동일한 공급원-exact 정책. 한국/`non_poi`/GT 없음 row는 자동 홀드아웃. 결과는 `generated/runs/<name>__v<k>.json`으로 버전 저장. 스크립트는 격리 서브프로세스에서 실행(로컬 단일 사용자용).

---

## ③ 평가 결과 (Eval) — `GET /api/matchrate` · `GET /api/records`

후보 검색 커버리지와 식별 정확도를 시각화하고, 케이스 단위로 성공/실패를 분석.

**기능**
1. **스코프 필터** + 매칭 정책 표시(provider exact name).
2. **후보 지표 카드 4종** — rank-1(GT가 1위 후보) · top-3 · top-5 · MISS(후보에 GT 없음).
3. **후보 검색 곡선** — N=1·3·5에서 GT가 top-N에 존재하는 비율(MapKit 실측, 한국 제외). "검색 상한/커버리지"이며 식별 정확도가 아님을 명시.
4. **식별 정확도 막대** — 제출된 알고리즘별(②에서) `예측==GT` 정확도. 이름당 최신 버전이 막대. 제출 없으면 비어 있음. 후보 API 이름(MapKit/Kakao)은 공급원이지 알고리즘이 아님.
5. **케이스 분석** — outcome 칩(정답/식별실패/검색실패/non_poi/deferred/no_gt)으로 필터 → 케이스 리스트(썸네일+GT+outcome 배지) → 상세(사진·좌표·OCR·후보 리스트에서 GT/베이스라인 pick 하이라이트).

   - **검색실패(retrieval)**: GT가 후보 API 결과에 아예 없음.
   - **식별실패(rank>1)**: GT가 후보엔 있으나 1위가 아님.

---

## ④ 데이터셋 추가 (Add) — `POST /api/validate-upload-package`

새 블로그/소스를 붙이는 절차. **사람은 2가지만**, 나머지는 도구가 자동 채움.

**기능**
1. **3단계 안내** —
   - STEP 1 등록(사람): `dashboard_config.json › sources`에 한 항목(`key·owner·source_type·label·color·default_confidence`).
   - STEP 2 템플릿 ZIP(사람): `photos/` 이미지 + `manifest.csv`(`photo`+`gt_input_raw`), notes 선택.
   - STEP 3 자동 채움(도구): 좌표·시각(EXIF), OCR(Vision), 도시·국가(역지오코딩), eval_provider(KR=Kakao / non-KR=MapKit), gt_confidence(기본값), **provider 정규 정답명(`gt_mapkit`/`gt_kakao`) ← `input_place_name`을 MapKit/Kakao에 재조회**(provider는 국가 기반, 매칭 실패 시 빈 채로 두고 폴백).
2. **템플릿 ZIP 다운로드** — 빈 업로드 템플릿.
3. **ZIP 검증** — 업로드 전 manifest 구조·이미지 경로 검증. 빈 템플릿은 `manifest_empty`로 거부(데이터 채운 뒤 업로드해야 함).
4. **사람 vs 도구 역할표** + 플래그 안내(`no_coord`·`no_gt`).

**원칙** — 결측은 조용히 버리지 않고 플래그로 표시(개요·경고에 노출). 보강도 같은 절차, 기존 `--dataset` key 지정. 이 탭은 절차 설명이며 평가 수치가 아님.

---

## 데이터 흐름 요약

```
④ 데이터셋 추가(ingest) → ① 개요(구조 파악) → ② 평가 실행(알고리즘 제출·채점) → ③ 평가 결과(지표·케이스 분석) ↺
```
후보 검색 커버리지는 알고리즘 성능의 상한을, 식별 정확도는 실제 성능을 측정한다.
