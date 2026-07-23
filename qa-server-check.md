# POI Eval 프론트엔드·백엔드 점검 보고서

## 범위

- 백엔드 실행 및 핵심 API 상태 확인
- Vite 개발 서버와 API proxy 확인
- React production build 및 TypeScript 검사
- Python 단위 테스트와 컴파일 검사
- `/new-run`에서 runner preflight와 dataset disabled 상태가 일치하는지 실제 Chromium DOM으로 확인

## 결과 요약

전체적인 서버 및 빌드 상태는 정상이다. 현재 로컬 데이터에는 실행 가능한 dataset이 없으며, `/new-run`은 네 dataset을 모두 비활성화하고 Run 버튼도 비활성화한다. 이는 backend `run_preflight` 결과와 일치한다.

점검 중 프론트엔드 문제 두 건을 발견해 수정했다.

1. ES2020 TypeScript target에서 지원하지 않는 `String.prototype.replaceAll` 때문에 production build가 실패함
2. 비활성 사유가 candidate blocker보다 일반 exclusion을 우선 표시할 수 있었고, eligibility 설명이 더 이상 사용하지 않는 match-rate 기준이라고 안내함

수정 후 production build, Python 테스트, 컴파일 및 diff 검사를 모두 통과했다.

## 실행 상태

### 백엔드

- 주소: `http://127.0.0.1:8420`
- 실행 명령: `POI_SKIP_GIT_SYNC_CHECK=1 python3 server.py`
- 상태: 정상 실행
- `/api/health`: HTTP 200
- `/api/git-status`: HTTP 200
- `/api/overview`: HTTP 200
- `/api/datasets`: HTTP 200
- `/api/runs`: HTTP 200
- 인증 요구: 없음
- origin 검사: 활성화
- data directory: `/Users/massis/Desktop/test_poi/poi/poi-data`

### 프론트엔드

- 주소: `http://127.0.0.1:5173`
- Vite 실행 상태: 정상
- `/`: HTTP 200
- Vite를 통한 `/api/overview` proxy: HTTP 200
- HMR: 변경한 `NewRun.tsx`를 정상 반영

## `/new-run` 검증

실제 설치된 Google Chrome을 headless 모드로 실행하여 React 렌더링 완료 후 DOM을 검사했다.

| Dataset | Backend preflight | UI 상태 | UI 사유 |
|---|---|---|---|
| `linkedspaces` | 72 eligible, candidate 72건 누락 | disabled | `Nearby candidate artifacts are missing (72)` |
| `poi-dataset-20260708` | 81 eligible, candidate 81건 누락 | disabled | `Nearby candidate artifacts are missing (81)` |
| `union-city` | 0 eligible | disabled | `No canonical MapKit ground truth (23)` |
| `vancouver` | 7 eligible, candidate 7건 누락 | disabled | `Nearby candidate artifacts are missing (7)` |

추가 확인:

- 네 dataset 버튼 모두 실제 HTML `disabled` 속성을 가짐
- Run evaluation 버튼도 실제 HTML `disabled` 속성을 가짐
- disabled dataset에 화면 표시 사유와 `title` 설명이 모두 존재
- eligibility 안내가 runner의 GT/provider/non-POI/candidate-artifact 검사를 명시함
- candidate artifact blocker가 있는 경우 일반 row exclusion보다 blocker를 우선 표시함

따라서 현재 상태에서는 사용자가 실행 불가능한 dataset을 선택하거나 `/api/run` 요청까지 진행할 수 없다.

## 발견 및 수정한 문제

### 1. Production build 실패 — 수정 완료

**증상**

`npm run build`에서 `String.prototype.replaceAll` 타입 오류가 발생했다. 프로젝트의 TypeScript library target은 ES2020이며 `replaceAll`은 해당 target에서 제공되지 않는다.

**수정**

```ts
reason.replaceAll("_", " ")
```

을 다음과 같이 변경했다.

```ts
reason.replace(/_/g, " ")
```

**검증**

Production build 성공:

- TypeScript build 성공
- Vite 74 modules transformed
- production assets 생성 성공

### 2. 잘못된 disabled 사유가 표시될 수 있음 — 수정 완료

**문제**

기존 구현은 `exclusions`와 `blockers`를 합친 뒤 가장 큰 count를 표시했다. 그러면 candidate artifact가 없어 실제 실행이 차단된 dataset에서도, count가 더 큰 `non_mapkit` 같은 일반 제외 사유가 대표 사유로 표시될 수 있었다.

**수정**

- blocker가 하나라도 있으면 blocker 중 대표 사유를 표시
- blocker가 없을 때만 exclusion을 표시

이제 `linkedspaces`, `poi-dataset-20260708`, `vancouver`에 실제 차단 원인인 candidate artifact 누락이 표시된다.

### 3. Eligibility 설명이 실제 구현과 불일치 — 수정 완료

**문제**

화면은 eligibility가 “same rules as match-rate”라고 안내했지만, 현재 값은 runner preflight 기준이며 candidate artifact 조건도 포함한다.

**수정**

설명을 runner의 GT, provider, non-POI, candidate-artifact 검사 기준이라고 변경했다.

## 자동 검증 결과

### Backend 및 Python

```text
Ran 49 tests in 0.015s
OK
```

통과 항목:

- `python3 -m unittest discover -s tests`
- `python3 -m py_compile server.py tools/run_algorithm.py`
- `git diff --check`

### Frontend

```text
vite v5.4.21 building for production...
✓ 74 modules transformed.
✓ built in 610ms
```

통과 항목:

- `tsc -b`
- `vite build`

## 남은 데이터 문제

애플리케이션 로직과 UI 차단은 정상 동작하지만, 현재 로컬 데이터에서 runnable dataset은 0개다. 원인은 다음과 같다.

- `linkedspaces`, `poi-dataset-20260708`, `vancouver`: runner 입력용 candidate artifact 누락
- `union-city`: canonical MapKit cohort 없음

따라서 실제 run 성공까지 검증하려면 최신 candidate snapshot을 복원하거나 최신 seed bundle을 다시 적용해야 한다. UI를 우회하여 억지로 run을 실행하는 방식은 올바른 검증이 아니다.

## 낮은 우선순위 개선 사항

### API 404 응답 형식

존재하지 않는 `/api/*` 경로와 잘못된 method의 `/api/run` 요청은 HTTP 404를 반환하지만 body는 generic HTML `File not found`다. 프론트엔드/API 소비자 일관성을 위해 다음과 같은 JSON 오류 형식이 더 적절하다.

```json
{
  "error": "not_found",
  "message": "API route not found"
}
```

이는 현재 preflight 기능을 막는 결함은 아니므로 낮은 우선순위다.

## 제한 사항

- Playwright가 요구하는 bundled Chromium binary가 설치되어 있지 않아 Playwright 기반 interaction test는 실행하지 못했다.
- 대신 시스템에 설치된 Google Chrome으로 실제 React DOM 렌더링과 disabled 속성 및 문구를 검증했다.
- 별도 vision API를 사용할 수 없어 스크린샷의 시각적 픽셀 검토는 수행하지 못했다.
- runnable fixture가 없으므로 실제 성공 run 및 결과 화면 전환은 실행하지 않았다.

## 변경 파일

- `server.py`
- `tests/test_run_algorithm_helpers.py`
- `tools/run_algorithm.py`
- `web/src/lib/api.ts`
- `web/src/pages/NewRun.module.css`
- `web/src/pages/NewRun.tsx`

점검 보고서:

- `qa-server-check.md`
