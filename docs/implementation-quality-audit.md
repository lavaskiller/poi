# POI Eval 구현 상태 및 품질 감사

검토 기준: 현재 `/Users/massis/Desktop/poi` 작업 트리(커밋되지 않은 변경 포함)  
검토 범위: React/Vite 프런트엔드, Python API, 주요 제품 흐름, 데이터 정합성, 접근성·반응형, 로컬 운영 안전성

## 1. 요약 판정

현재 사이트는 **완성도 높은 화면 프로토타입 + 일부 실제 API 기능 + 미연결 핵심 기능**이 혼재된 상태다.

- **화면/디자인 구현:** 80–85%
- **읽기 API 및 결과 조회:** 65–75%
- **핵심 업무 흐름 완성도:** 35–45%
- **데이터 신뢰성/표현 정합성:** 40–50%
- **접근성·반응형·제품화 품질:** 40–50%
- **종합 제품 완성도:** **약 50–55%**

한 줄 판정:

> **내부 데모 및 일부 실제 검토 업무에는 사용할 수 있으나, “데이터 추가 → 알고리즘 실행 → 결과 비교·분석”을 완주하는 제품으로는 아직 미완성이다.**

가장 중요한 문제는 단순히 버튼 몇 개가 빠진 것이 아니라, **실제 데이터와 무관한 샘플 수치가 운영 데이터처럼 표시되는 화면이 있다는 것**이다. 이는 사용성보다 먼저 신뢰성 문제로 다뤄야 한다.

## 2. 검증 결과

### 확인된 정상 동작

실행 중인 `127.0.0.1:8420`에 읽기 전용 스모크 테스트를 수행했다.

| API | 결과 |
|---|---|
| `/api/overview` | 200, 실제 데이터 362행 |
| `/api/runs` | 200 |
| `/api/matchrate` | 200 |
| `/api/datasets` | 200 |
| `/api/jobs` | 200 |
| `/api/gt/reconcile` | 200, remaining 145 |
| `/api/records?dataset=all` | 200, 362 records |

- `python3 -m py_compile server.py tools/*.py`: **통과**
- 저장소에서 자동화 테스트 파일은 발견되지 않음
- 데이터 변경을 막기 위해 run 생성, ingest, reconcile 저장, 삭제 API는 호출하지 않음

### 검증하지 못한 부분

- 현재 환경에 `node`와 `npm`이 없어 `tsc -b && vite build`를 실행하지 못함
- Playwright Chromium 실행 파일도 없어 브라우저 렌더링·클릭·콘솔·반응형 실측 불가
- 따라서 프런트 TypeScript 컴파일 성공과 실제 시각 품질은 **미검증**

## 3. 구현 상태 맵

| 화면/기능 | 실데이터 | 핵심 조작 | 상태 |
|---|---|---|---|
| App shell / 연결 오류 | overview | Retry | 구현됨 |
| Onboarding | seed API | seed | 기본 구현 |
| Home | overview, runs | 주요 CTA 무동작 | 부분 구현 |
| New Run | overview/schema | 파일 첨부·실행 불가 | 핵심 미완성 |
| Results | runs, detail, matchrate | 필터·비교·내보내기 무동작 | 부분 구현 |
| Case Inspector | case API | 읽기 중심 | 대체로 구현, 재현성 문제 |
| Compare | 없음 | 모두 정적 | 목업 |
| Datasets | 없음 | 로컬 선택만 동작 | 목업 |
| Reconcile GT | queue/save/probe | 실제 저장 가능 | 가장 완성도 높음 |
| Retrieval Diagnostics | 없음 | 정적 표시 | 목업 |
| Jobs | 없음 | 없음 | Placeholder |

## 4. 핵심 이슈

### P0 — 제품 신뢰성/핵심 흐름

#### 1. Datasets가 실제 데이터와 다른 하드코딩 값을 운영 정보처럼 표시

- `web/src/pages/Datasets.tsx:20-69`: 데이터셋명, 행 수, 날짜, coverage가 상수
- `Datasets.tsx:135-139`, `291-304`: job 목록과 64% 진행률도 상수
- 실제 API는 총 362행, 4개 데이터셋이지만 화면 샘플은 3개 데이터셋, 총 1,284행
- `web/src/components/Sidebar.tsx:55-58`: 항상 `API connected · 3 datasets`

**영향:** 사용자가 ingest 성공 여부, 데이터 규모, coverage, 작업 진행 상태를 잘못 판단할 수 있다.

**조치:** `/api/datasets`, `/api/field-profile`, `/api/jobs`로 즉시 연결하거나, 연결 전까지 화면 전체에 명확한 `Demo data` 표시를 하고 조작 버튼을 disabled 처리한다.

#### 2. Compare와 Retrieval Diagnostics가 실제 결과가 아닌 샘플 수치를 실제 분석처럼 표시

- `web/src/pages/Compare.tsx:5-50`, `56-60`, `79-94`: run, accuracy, flipped cases가 고정
- `web/src/pages/RetrievalDiagnostics.tsx:4-27`: coverage curve와 알고리즘 점수가 고정

실제 API에서 최고 observed strict accuracy는 약 48%인데 Compare는 78.4%를 표시한다. Retrieval 화면 수치도 실제 match-rate와 다르다.

**영향:** 모델 개선/회귀 및 retrieval ceiling에 대한 의사결정을 왜곡한다.

**조치:** 실데이터 연결 전에는 정식 내비게이션에서 숨기거나 명시적인 샘플 화면으로 격리한다.

#### 3. 핵심 New Run 흐름이 실행되지 않음

- `web/src/pages/NewRun.tsx:104-128`: 실제 file input이나 drop handler 없이 가짜 첨부 파일 표시
- `NewRun.tsx:124`: `POST /api/run` 연결이 다음 작업이라고 명시
- `NewRun.tsx:220-223`: 실행 버튼이 항상 disabled
- 백엔드 `/api/run`은 이미 구현되어 있으나 `web/src/lib/api.ts`에 실행 메서드가 없음

**영향:** 제품의 핵심 JTBD인 알고리즘 평가를 UI에서 수행할 수 없다.

**조치:** 파일 선택, 언어/이름/scope/params 매핑, 실행 상태, 오류, 성공 후 결과 URL까지 하나의 수직 흐름으로 완성한다.

#### 4. New Run의 eligible 계산이 논리적으로 부정확

- `web/src/pages/NewRun.tsx:80-86`: 선택 필드 fill의 최솟값을 교집합 행 수로 사용

각 필드가 70행씩 채워져도 서로 겹치는 행이 40개일 수 있으므로 `min(fill)`은 실제 eligible이 아니다. 백엔드 eligibility에는 GT, provider, tier, candidate artifact 조건도 추가된다.

**영향:** 실행 전 표본 수와 binding constraint가 과대 표시될 수 있다.

**조치:** 선택 signal과 scope를 받아 행 단위 eligibility를 계산하는 backend preview endpoint를 만든다.

### P1 — 결과 재현성 및 데이터 계약

#### 5. Results가 최고 run 상세와 전역 match-rate를 한 결과처럼 혼합

- `web/src/pages/Results.tsx:17-25`: 최고 accuracy run 상세와 인자 없는 `/api/matchrate`를 함께 조회
- `Results.tsx:95-105`: 전역 selection/retrieval miss를 선택된 run 지표 옆에 표시

두 데이터가 같은 scope, mode, evaluation hash를 사용한다는 보장이 없다.

**조치:** match-rate를 run name/version/snapshot에 귀속시키거나 별도 baseline 진단으로 명확히 분리한다.

#### 6. Case deep link가 특정 run에 고정되지 않음

- `web/src/pages/Results.tsx:136-139`: URL에 dataset/photo만 포함
- `web/src/pages/CaseInspector.tsx:8-15`: case 요청도 dataset/photo만 전달
- 서버는 조회 시점의 최고 run을 다시 선택

**영향:** 동일 URL의 prediction과 verdict가 최고 run 변경 후 달라질 수 있어 과거 결과 감사와 재현이 어렵다.

**조치:** case URL/API에 `run_name`과 `version`을 포함한다.

#### 7. 사진 조회가 dataset을 실질적으로 사용하지 않아 basename 충돌 가능

- 프런트는 dataset/photo를 모두 전달하지만 서버 사진 검색은 photo basename 중심

**영향:** 서로 다른 데이터셋에 같은 파일명이 있으면 잘못된 사진을 보여줄 수 있다.

**조치:** dataset 설정의 `photo_dir` 안에서만 안전하게 resolve한다.

#### 8. Home의 best/trend 비교가 동일 cohort인지 검증하지 않음

- `web/src/pages/Home.tsx`: 전체 run 중 accuracy 최대를 선택하고 이름/버전 중심으로 추세 계산

scope, scoring mode, eval snapshot이 다른 run끼리도 개선으로 표시될 수 있다.

**조치:** evaluation hash, scope, mode가 동일한 run만 비교한다.

### P1 — 백엔드 운영 안전성

#### 9. 제출 코드를 호스트 권한으로 실행

- `server.py`의 `/api/run` → `tools/run_algorithm.py` subprocess 실행
- 기본 timeout이 없고 container/VM sandbox, CPU/memory/network 제한이 없음

**판정:** 신뢰된 1인 로컬 도구라면 허용 가능하지만 공유 환경이나 외부 배포에는 차단 이슈다.

#### 10. 저장소 전체가 정적 파일 루트가 될 수 있음

- `SimpleHTTPRequestHandler` fallback이 저장소 루트 파일을 제공

**영향:** 소스, `.git`, 설정, run 산출물 등 의도하지 않은 파일 노출 가능.

**조치:** 정적 루트를 `web/dist` 같은 공개 디렉터리로 제한한다.

#### 11. CSV writer 잠금 규약과 run 저장의 동시성 안전성이 일관되지 않음

- 일부 OCR/GT 도구는 lock + atomic replace 사용
- ingest, EXIF, dataset delete 등은 같은 규약을 일관되게 사용하지 않음
- run version은 디렉터리 스캔 후 결정하고 최종 JSON에 직접 write

**영향:** CLI와 서버 작업이 겹치거나 동시 run 요청이 들어오면 lost update, 같은 버전 덮어쓰기, 부분 파일 가능.

**조치:** 모든 데이터 변경에 공통 lock/transaction helper를 사용하고 run version을 원자적으로 예약한다.

#### 12. 파괴적 API에 인증·Origin/CSRF 방어가 없음

- run 삭제, dataset 삭제 job, ingest, reconcile 등 write endpoint가 localhost 신뢰에 의존

**판정:** 개인 로컬 도구 범위를 벗어나면 위험. 최소 startup secret과 Origin/Host allowlist가 필요하다.

### P2 — UX, 접근성, 품질

#### 13. 화면 곳곳에 죽은 버튼과 가짜 컨트롤 존재

- Home의 Upload data/New run
- Results의 Compare/Export/filter
- Compare의 Add run/remove/filter
- Datasets의 template/add/rerun/log/dropzone
- `/jobs`는 Placeholder

**조치:** 동작을 연결하지 못한 컨트롤은 버튼처럼 보이지 않게 하거나 disabled + `Coming soon`으로 명시한다.

#### 14. 반응형 설계가 사실상 없음

CSS 전체에서 의미 있는 `@media`/`@container` 규칙이 없고 다음 고정 구조가 많다.

- 240px sidebar
- Case Inspector 470px photo column
- Reconcile 380px case column
- Results 3열 gallery와 nowrap filters
- Datasets 고정 열 및 390px ingest panel

**영향:** 작은 노트북/태블릿/모바일에서 수평 overflow와 콘텐츠 잘림 가능성이 높다.

#### 15. 접근성 상태 전달이 부족

- ProgressBar와 coverage bar에 `role="progressbar"`, `aria-valuenow` 없음
- loading/error/save 상태에 `aria-live`/`role="status"` 부족
- Reconcile 단일 선택 후보에 radio 또는 `aria-pressed` 의미 부족
- 지도 위치 변경의 키보드 대체 입력 부족
- 장식 없는 전역 링크 스타일

#### 16. 프런트 비동기 요청 경쟁과 오류 계약이 약함

- `useAsync.reload`는 요청 순서 역전 방지나 AbortController가 없음
- 일부 API는 HTTP 오류와 `{ok:false}`를 일관되게 검사하지 않음
- `/api/gt/reconcile` GET 내부 오류가 HTTP 200의 빈 queue처럼 반환될 수 있음

## 5. 좋은 점

- React/TypeScript/CSS Modules 구조가 명확하고 페이지·컴포넌트·API 계층이 분리되어 있다.
- App, Home, Results, Case, Reconcile에 기본 loading/error 분기가 있다.
- overview, runs, case, reconciliation 등 상당수 조회/검토 기능은 실제 API를 사용한다.
- Reconcile GT는 queue → 후보 선택 → 저장 → 다음 case 흐름이 연결된 가장 완성도 높은 화면이다.
- 백엔드 run 산출물은 code/data snapshot hash와 strict/canonical metric을 보관해 재현성을 고려했다.
- 일부 worker에는 lock, backup, atomic replace가 적용되어 있어 데이터 무결성 의도가 보인다.
- Python 전체는 구문 컴파일을 통과했고, 주요 GET API도 실제 데이터로 응답했다.

## 6. 권장 실행 순서

### 1주차: 신뢰성 회복

1. Datasets/Compare/Retrieval의 가짜 수치 제거 또는 Demo 라벨
2. Sidebar dataset count 실데이터화
3. 죽은 버튼 disabled/숨김 처리
4. Results run/match-rate 혼합 표시 분리

### 2주차: 핵심 수직 흐름 완성

5. New Run 파일 선택 및 `/api/run` 연결
6. 프런트 column → backend signal mapping 정의
7. backend eligibility preview 구현
8. 실행 성공 후 run-specific Results URL로 이동

### 3주차: 재현 가능한 분석

9. Results run selector
10. Case URL에 run name/version 추가
11. 실제 Compare 구현 및 cohort/hash guard
12. Retrieval을 실제 match-rate에 연결

### 4주차: 데이터 운영과 품질

13. Datasets ingest/jobs 실제 연결
14. 공통 CSV transaction lock과 run atomic save
15. 반응형 breakpoint 및 접근성 보완
16. Vitest/React Testing Library/API contract tests와 CI build 추가

## 7. 출시 판단

### 현재 가능한 범위

- 신뢰된 한 명의 개발자가 로컬에서 데이터와 기존 run을 조회
- 실패 사례 확인
- GT↔MapKit reconciliation 수행
- 내부 디자인/제품 데모

### 현재 권장하지 않는 범위

- 실제 사용자가 사이트만으로 새 평가를 생성하는 업무
- 화면의 Datasets/Compare/Retrieval 수치에 기반한 의사결정
- 다중 사용자 또는 외부 접근 배포
- 결과 재현성과 데이터 변경 안전성이 요구되는 운영 환경

## 최종 점수

- **구현 상태: 5.5 / 10**
- **코드 구조: 7 / 10**
- **데이터 신뢰성: 4.5 / 10**
- **UX 완성도: 5 / 10**
- **운영 안전성: 로컬 6 / 10, 공유 배포 3 / 10**

화면을 더 다듬기보다 먼저 **가짜 데이터를 제거하고 New Run의 실제 수직 흐름을 완성하는 것**이 품질 개선 효과가 가장 크다.
