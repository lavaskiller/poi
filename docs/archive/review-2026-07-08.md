# POI Test Data Review

검토 일시: 2026-07-08
대상 경로: `poi-test-data/`

## 1. 한줄 요약

`poi-test-data`는 앱의 POI 식별 품질을 재현 가능하게 평가하기 위한 로컬 데이터셋/대시보드/프로브 모음이다. 현재는 **데이터 수집·신호 병합·대시보드 개요**는 상당히 정리되어 있으나, PRD/SRD가 핵심 MVP로 둔 **정규화 매칭 엔진(`match_score.py`)과 `/api/matchrate`**가 아직 빠져 있어 “정직한 최종 매치율”을 도구가 완전히 산출하는 단계는 아니다.

## 2. 디렉토리 구성

```text
poi-test-data/
├── eval_set_reconciled.csv       # 현재 중심 데이터셋, 280 rows x 23 cols
├── dashboard_config.json         # dataset/confidence/schema/pipeline config
├── server.py                     # 로컬 HTTP 서버 + /api/overview + /api/records
├── dataset-overview.html         # 라이브 개요 대시보드
├── mvp-eval-ui.html              # MVP 평가 UI 프로토타입
├── PRD-SRD-dataset-dashboard.md  # 평가 방법론/도구 PRD+SRD
├── merge_signals.py              # OCR/MapKit 결과를 CSV에 비파괴 머지
├── ls_mapkit_probe.swift         # linkedspaces용 MapKit 후보 프로브
├── ai_poi_run.swift              # FoundationModels 기반 POI 추론 실험
├── linkedspaces-photos/          # 216 files, 약 213MB
├── photos/                       # 19 files, 약 82MB
├── union-city-trip/              # 18 files, 약 32MB
└── tools/                        # FastVLM 관련 venv/repo, 약 2.0GB
```

전체 `poi-test-data/`는 Git 기준으로 통째로 untracked 상태다.

## 3. 데이터셋 현황

`eval_set_reconciled.csv` 기준:

| 항목 | 값 |
|---|---:|
| rows | 280 |
| columns | 23 |
| datasets | linkedspaces 228, union-city 33, vancouver 19 |
| canonical user_selected | 233 |
| canonical confident | 32 |
| canonical non_poi | 6 |
| canonical unresolved | 9 |

### dataset 분포

```text
linkedspaces  228
union-city     33
vancouver      19
```

### gt_confidence raw 분포

```text
user_selected            228
strong_content            17
synthetic_named           11
synthetic_unconfirmed      8
non_poi                    6
confirmed_user             5
inferred                   4
ambiguous                  1
```

`dashboard_config.json`의 rollup 결과:

```text
user_selected  233 = user_selected 228 + confirmed_user 5
confident       32 = strong_content 17 + synthetic_named 11 + inferred 4
non_poi          6
unresolved       9 = synthetic_unconfirmed 8 + ambiguous 1
```

### 국가 정규화 결과

`server.py`의 `build_overview()` 기준:

```text
United States 206
South Korea    28
Canada         24
Unknown        12
Mexico          7
Spain           1
France          1
Netherlands     1
```

`country_by_dataset`가 있어서 `union-city`와 `vancouver`는 CSV country가 비어 있어도 각각 United States/Canada로 보정된다.

## 4. 현재 베이스라인 수치

`eval_set_reconciled.csv`의 `app_poi_rank` 기준 현재 관측값:

### 전체, baseline rank가 있는 242행

| Metric | Count | Rate |
|---|---:|---:|
| rank-1 | 38 / 242 | 15.7% |
| top-3 | 59 / 242 | 24.4% |
| top-5 | 68 / 242 | 28.1% |
| MISS | 157 / 242 | 64.9% |

### canonical `user_selected`, baseline rank가 있는 195행

| Metric | Count | Rate |
|---|---:|---:|
| rank-1 | 31 / 195 | 15.9% |
| top-3 | 46 / 195 | 23.6% |
| top-5 | 54 / 195 | 27.7% |
| MISS | 126 / 195 | 64.6% |

### linkedspaces + user_selected + non-KR, baseline rank가 있는 190행

| Metric | Count | Rate |
|---|---:|---:|
| rank-1 | 30 / 190 | 15.8% |
| top-3 | 45 / 190 | 23.7% |
| top-5 | 53 / 190 | 27.9% |
| MISS | 122 / 190 | 64.2% |

이 숫자는 PRD/SRD의 “raw 미정규화 하한선” 설명과 일치한다. 다만 아직 정규화 토큰셋 매칭 전이므로 최종 결론으로 쓰면 안 된다.

## 5. 파이프라인 상태

`server.py`의 `/api/overview` 계산 결과:

| 단계 | extracted | merged | total | status | note |
|---|---:|---:|---:|---|---|
| GPS 좌표 | 280 | 280 | 280 | done |  |
| 사진 다운로드+변환 | 268 | 268 | 280 | done |  |
| GT 라벨 | 272 | 272 | 280 | done |  |
| Vision OCR | 268 | 268 | 280 | done | 123 텍스트 검출 · 145 텍스트 없음 |
| MapKit 베이스라인 | 242 | 242 | 280 | done | 38행 제외(한국·무사진, kr_deferred) |
| 온디바이스 LLM (v2) | 52 | 0 | 280 | run | CSV 미머지 |
| FastVLM (이미지) | 0 | 0 | 280 | wait | 셋업·스모크 |

config warnings는 현재 0개다.

## 6. 구현 파일 검토

### `PRD-SRD-dataset-dashboard.md`

좋은 점:

- 문제를 “POI 개선”보다 먼저 “평가 방법 정형화”로 잡은 방향이 맞다.
- rank-1/top-k/MISS 지표가 앱 UX와 직접 연결되어 있다.
- raw vs normalized, n/분모/제외행 표기, 순환참조 금지 등 정직성 게이트가 잘 정의되어 있다.
- `eval_set_reconciled.csv` + `dashboard_config.json`를 single source로 두는 방향이 좋다.

남은 점:

- 문서상 MVP 완료 정의의 핵심인 `match_score.py`, `/api/matchrate`, top-N live curve가 아직 없다.
- `ingest_dataset.py`도 신규 예정으로만 남아 있다.

### `server.py`

좋은 점:

- Python 표준 라이브러리만 사용해서 로컬 실행성이 좋다.
- `/api/overview`가 CSV와 config를 매 요청마다 읽어 live 집계를 만든다.
- config에 없는 dataset/confidence/schema를 warning으로 올리는 구조가 좋다.
- `/api/records`로 case drill-down을 시작한 것도 좋다.

주의점:

- `DIRECTORY = "/Users/massis/Desktop/fastblog/poi-test-data"`가 하드코딩되어 있어 다른 경로에서는 깨진다.
- `/api/matchrate`가 아직 없다.
- `build_records()`의 후보 리스트는 `ls_nearby_results.tsv`만 읽는다. union-city/vancouver의 top3 후보는 records API에 충분히 반영되지 않을 수 있다.
- `outcome()`은 현재 `app_poi_rank` 기반 raw 판정만 한다. PRD의 normalized matching과 evidence는 아직 구현되지 않았다.
- `_photo_url()`은 union-city 사진을 빈 문자열로 반환하므로 UI에서 union-city 이미지는 로컬 표시가 안 된다.

### `merge_signals.py`

좋은 점:

- 빈 셀만 채우는 비파괴/멱등 방식이다.
- OCR과 MapKit baseline merge 목적이 분명하다.

주의점:

- 상대경로 기반이라 반드시 `poi-test-data` 디렉토리에서 실행해야 한다.
- 백업 생성이 없다. 문서의 “백업 후 실행” NFR과 완전히 일치하려면 실행 전 timestamp backup을 만들면 좋다.
- `open(CSV)`에 encoding이 없는 곳이 있다. macOS 기본에서는 보통 괜찮지만 명시하는 편이 안전하다.

### `ls_mapkit_probe.swift`

좋은 점:

- 앱 경로와 맞게 80m strict → 250m wide로 설계되어 있다.
- MapKit throttle 대응을 위해 pace와 retry cooldown이 있다.
- coord cache로 중복 좌표 재조회 비용을 줄인다.

주의점:

- `rankOf()`가 단순 lowercase substring이다. PRD의 정규화 토큰셋 매칭과 다르다.
- 후보 리스트를 top3만 TSV에 저장한다. top-5/top-10 curve와 normalized rerank를 하려면 전체 후보 또는 최소 top10 저장이 필요하다.
- `key = %.5f,%.5f` 캐시는 약 1m 단위 반올림이라 의도된 중복 제거인지 확인 필요하다.

### `mvp-eval-ui.html`

좋은 점:

- MVP가 어떤 의사결정 화면이어야 하는지 보여주는 프로토타입으로 유용하다.
- `/api/records`, `/api/overview` 일부를 실제로 사용한다.

가장 큰 문제:

- 핵심 evaluation block의 `DATA`가 mock/static이다. 현재 CSV live 숫자와 불일치할 수 있다.
- 예: static `all.raw`는 `n=190, rank1=30, top3=49, top5=55, miss=129`인데, 실제 linkedspaces user_selected non-KR는 `n=190, rank1=30, top3=45, top5=53, miss=122`다.
- 이 화면을 미팅에서 쓰려면 반드시 `/api/matchrate` 기반 live 데이터로 바꿔야 한다.

### `ai_poi_run.swift`

좋은 점:

- prompt variant v0~v3로 실험을 추적할 수 있다.
- coords_only / caption_only / coords_caption arm 분리가 되어 있다.
- transit/screen/private residence 등 non-POI hallucination 방지 규칙이 구체적이다.

주의점:

- 출력이 raw JSON 문자열 TSV일 뿐, `eval_set_reconciled.csv`와 평가 컬럼으로 아직 연결되지 않는다.
- `score_ai.py`를 통한 평가 흐름은 있으나 dashboard에는 merged되지 않은 상태다.

## 7. 주요 리스크

1. **정규화 매칭 엔진 부재**
   - 현재 핵심 수치는 raw/substring 기반에 가깝다.
   - 문서상으로도 “raw는 하한선, 신뢰 불가”라고 되어 있다.

2. **대시보드 일부가 mock 수치**
   - `mvp-eval-ui.html`의 핵심 수치와 그래프가 live API가 아니라 static `DATA`다.
   - 실제 데이터와 조금씩 다르므로 의사결정용으로 쓰면 위험하다.

3. **후보 리스트 저장 깊이가 부족**
   - `ls_nearby_results.tsv`는 `top3_wide`만 저장한다.
   - top-5/top-10 curve, normalized matching의 evidence, false positive review에는 후보 전체 또는 top10 이상이 필요하다.

4. **경로 하드코딩/실행 위치 의존**
   - `server.py`는 절대경로 하드코딩.
   - `merge_signals.py`는 상대경로라 실행 디렉토리 의존.

5. **대용량 tools 포함**
   - `tools/`가 약 2GB다.
   - Git에 올릴 계획이라면 반드시 제외하거나 별도 설치 스크립트/문서로 분리해야 한다.

6. **데이터셋/사진 수 불일치 가능성**
   - `linkedspaces-photos`는 216 파일인데 linkedspaces rows는 228이다.
   - pipeline도 사진 다운로드+변환 268/280으로 12행 결측을 표시한다.
   - 결측은 의도대로 드러나지만, matchrate denominator에서 어떻게 제외하는지 명확히 API에 반영해야 한다.

## 8. 권장 다음 작업 순서

### P0 — 지금 바로 필요한 것

1. `match_score.py` 작성
   - 입력: `eval_set_reconciled.csv`, `dashboard_config.json`, MapKit 후보 TSV
   - 출력 컬럼: `match_raw`, `match_norm`, `match_rank_norm`, `match_evidence`, `match_excluded_reason`
   - 규칙: 대칭 정규화, generic token 저가중/제외, Jaccard threshold, exact/raw 병기

2. `/api/matchrate` 구현
   - dataset scope: `all | linkedspaces | union-city | vancouver`
   - mode: `raw | norm`
   - 반환: n, excluded, rank1/top3/top5/miss, curve, flips

3. `mvp-eval-ui.html`의 static `DATA` 제거
   - `/api/matchrate`를 fetch해서 카드/곡선 렌더
   - mock은 별도 demo mode로만 남기기

### P1 — 평가 신뢰도 강화

4. MapKit probe 결과를 top3가 아니라 top10 또는 full 후보로 저장
   - `top_candidates_json` 또는 별도 TSV 추천

5. `server.py` 경로 하드코딩 제거
   - `DIRECTORY = os.path.dirname(os.path.abspath(__file__))`

6. `merge_signals.py`에 자동 백업 추가
   - `eval_set_reconciled.backup-YYYYMMDD-HHMMSS.csv`

7. `/api/records`에 normalized evidence 포함
   - GT normalized tokens
   - matched candidate
   - overlap tokens
   - threshold score

### P2 — 확장성

8. `ingest_dataset.py` 추가
   - 사진+GT만 받아서 EXIF/OCR/MapKit baseline/flags 자동 채움

9. FastVLM 결과를 표준 방법 컬럼으로 병합
   - method별 결과를 long-form TSV로 관리하는 편이 좋음

10. `tools/` 정리
   - `.gitignore`에 `poi-test-data/tools/`, `*.venv`, model cache 등 제외
   - 설치 재현은 README/스크립트로 분리

## 9. 결론

현재 `poi-test-data`는 방향성이 좋고, 특히 PRD/SRD는 평가 기준을 꽤 정직하게 잡고 있다. 데이터도 `linkedspaces` 실제 사용자 선택 228행을 중심으로 의미 있는 규모에 도달했다.

다만 지금 상태를 “평가 완료”로 보면 안 된다. 현재 산출 가능한 baseline은 raw 기준 하한선이며, 프로젝트 문서가 요구하는 신뢰 가능한 결론은 아직 `match_score.py`와 `/api/matchrate`가 들어와야 가능하다.

가장 먼저 할 일은 **정규화 매칭 엔진 + live matchrate API + UI mock 제거**다.
