# POI 파이프라인 MLOps 리뷰

## 범위와 판정

이 평가는 저장소에 구현·문서화된 **POI 후보 선택 및 오프라인 평가 파이프라인**을 대상으로 했다. 이는 아직 전형적인 온라인 ML 서비스라기보다, 강한 재현성 장치를 갖춘 로컬 평가/실험 플랫폼이다. 따라서 운영 배포·관측·롤백 관점의 공백은 “나쁜 구현”이라기보다 제품화 단계에서 반드시 메워야 할 항목이다.

**총평:** 선택 로직의 안전성과 오프라인 실험 무결성은 좋은 편이다. 반면 데이터·모델·프롬프트의 계보(lineage), 승인된 승격(release), 온라인 모니터링은 아직 수작업/로컬 파일 중심이다.

## 현재 설계에서 잘 된 점

1. **단계적 의사결정과 비용 제어** — `access_ocr`/`list_fit` 규칙으로 먼저 고르고, 규칙이 nearest pin을 벗어나지 못한 약한 경우에만 FastVLM top-5를 호출한다. 비용·지연·환각 위험을 줄이는 합리적 캐스케이드다.
2. **안전한 실패와 abstention** — 후보가 없으면 abstain, FastVLM live 모드에서 자산이 없으면 OCR-only 결과를 ensemble로 위장하지 않고 run을 실패시킨다. confidence gate도 틀린 POI 노출보다 Near fallback을 허용한다.
3. **GT 누수에 대한 인식** — predict 입력과 사후 평가 GT를 분리했고, confidence gate 문서가 GT-derived 신호를 명시적으로 금지한다. category prior에는 held-out/CV 규율도 있다.
4. **평가 실행의 기본 provenance** — run JSON에 스크립트 본문/SHA-256, evaluation-set 및 data-snapshot hash, 버전, 호스트 runtime, case-level 결과와 latency 요약을 남긴다. 후보 스냅샷도 hash와 active pointer로 관리한다.
5. **입력 품질 guardrail 및 회귀 테스트** — full candidate artifact가 없거나 lossy top-3만 있으면 실행을 막고, malformed artifact도 성공으로 처리하지 않는다. 로컬 unittest 104개가 통과했다.

## 우선순위 개선 사항

### P0 — 결과를 신뢰 가능한 release로 만들기

| 공백 | 위험 | 권고안 / 완료 기준 |
|---|---|---|
| 단일 unique-149 seed 결과(44% exact/65% canonical)는 archive이며 live 재실행과 다를 수 있다. 시간·장소·촬영원천 단위의 고정 test set 정책도 확인되지 않는다. | 같은 장소/연속 사진/반복 탐색으로 인한 과대평가와 leaderboard overfitting | `train/validation/test` manifest를 immutable ID와 group key(장소/세션/원천)로 고정하고, test GT는 release 승인 시에만 사용한다. 전체 + slice(국가/카테고리/후보수/OCR 유무/야간 등) CI 리포트를 필수화한다. |
| 룰·VLM 트리거·gate 가중치를 같은 cohort에서 반복 탐색할 수 있다. confidence gate 일부 CV는 존재하지만 selector 자체의 release gate는 별도다. | selection bias; “개선”이 holdout 재사용의 산물일 수 있음 | 개발용 validation과 봉인된 final test를 분리한다. promotion 기준은 accuracy만이 아니라 wrong-leak, coverage, abstention, p95 latency, 비용, 핵심 slice 하한을 포함한다. |
| `.github/` CI workflow가 없다. | 리뷰되지 않은 변경이 기준선 회귀를 일으켜도 병합/배포 가능 | PR CI에서 unit test, bundle/import isolation, fixed golden set, schema/data validation, baseline delta와 slice regression을 실행한다. protected branch와 required check를 설정한다. |

### P1 — 완전한 재현성 및 계보

| 공백 | 위험 | 권고안 / 완료 기준 |
|---|---|---|
| 현재 hash는 CSV/config/candidate artifact와 script 중심이다. 이미지 파일, OCR/scene 산출물, FastVLM checkpoint commit/checksum, torch/FastVLM 버전, prompt/template, VLM cache의 정확한 snapshot은 실행 manifest에 명시적으로 묶이지 않는다. | 같은 run ID라도 모델·이미지·cache가 달라 결과를 재현하지 못함 | `run_manifest.json`에 Git SHA/dirty state, container image digest, lockfile, checkpoint SHA-256, FastVLM commit, prompt version, input image/OCR/scene/candidate artifact hashes, cache schema+key digest를 기록하고 artifact store에 immutable 저장한다. |
| `poi-data/`가 gitignored private tree이며 로컬 파일과 active pointer에 의존한다. | 데이터 변경·삭제·동시 작업 시 lineage와 rollback이 약함 | DVC/lakeFS/오브젝트 스토리지 versioning 또는 최소한 content-addressed snapshot registry를 도입한다. active snapshot은 승인된 manifest ID로만 전환하고 atomic promotion/audit log를 남긴다. |
| FastVLM setup은 multi-GB 다운로드와 Mac/MPS에 의존한다. | 머신마다 다른 dependency/model 결과와 재현 불가 | Docker/OCI image 또는 lockfile 기반 재현 환경을 제공한다. MPS 전용 runtime은 별도 execution pool로 고정하고 startup smoke test 및 hardware compatibility matrix를 둔다. |

### P1 — 온라인 운영 준비

| 공백 | 위험 | 권고안 / 완료 기준 |
|---|---|---|
| 현재 metric은 offline run JSON과 desktop host latency다. 프로덕션 요청, VLM 호출률/실패율, end-to-end latency, 비용, fallback, 사용자 정정 이벤트에 대한 telemetry/alerting은 확인되지 않는다. | 성능·비용·품질 저하를 뒤늦게 발견 | request/run correlation ID를 도입하고 structured logs + metrics를 수집한다. dashboard와 alert: error rate, candidate-empty, OCR/VLM availability, VLM override/UNKNOWN, cache hit, gate block/wrong-leak proxy, p50/p95, cost/request. |
| drift/quality detection 및 재평가 스케줄이 없다. | 신규 지역·계절·카메라·MapKit 후보 변화에 조용히 악화 | 입력 drift(후보 수/거리, OCR length, category/region, scene), prediction drift, delayed label quality를 기준선과 비교하고 threshold 알림 및 scheduled canary/golden reevaluation을 둔다. |
| 모델/룰/gate의 registry와 canary/shadow/rollback 정책이 없다. | 문제가 생기면 어떤 조합으로 되돌릴지 불명확 | selector, gate, prompt, candidate snapshot을 하나의 versioned release bundle로 등록한다. shadow → canary → full rollout, SLO breach 자동/수동 rollback을 정의한다. |

### P2 — 거버넌스·보안·운영 탄력성

- 사진과 위치는 민감할 수 있다. 데이터 보존 기간, 접근 권한/RBAC, 암호화, 감사 로그, PII/EXIF 최소화, 외부 모델로 전송되는 payload 정책을 명시해야 한다.
- `POI_API_TOKEN`은 mutating API 보호의 출발점이지만 production authN/authZ, secret manager, TLS, rate limit, tenant/role audit까지 확장해야 한다.
- 로컬 daemon thread + filesystem JSON은 단일 사용자 실험에는 충분하나, 다중 사용자/장시간 job에는 durable queue, retry/idempotency, cancellation, worker isolation, artifact retention이 필요하다.
- human-in-the-loop 정답 reconcile의 reviewer agreement, 변경 이력, label version, sampled QA를 운영 지표로 만든다. GT 품질이 모델 상한을 정한다.

## 권장 목표 아키텍처

```text
Raw photos/GPS → immutable data snapshot + label version
                       ↓
MapKit/OCR/scene enrichment → versioned feature/candidate artifacts
                       ↓
Selector rules + FastVLM + confidence gate → versioned release bundle
                       ↓
Offline evaluator (fixed group split, slices, cost/latency) → approval registry
                       ↓
Shadow/Canary serving → telemetry + delayed labels → drift/quality monitoring
                       ↓
Rollback or retraining/rule-update loop
```

핵심 원칙은 **모델만 버전 관리하지 않고, 후보 검색 결과·OCR·프롬프트·gate·데이터 split을 함께 하나의 배포 단위로 관리**하는 것이다.

## 90일 현실적 로드맵

1. **0–30일:** group-aware frozen test manifest, CI baseline/slice gate, release scorecard, run manifest 확장(model/prompt/image/cache hashes), data snapshot registry를 만든다.
2. **31–60일:** containerized/reproducible FastVLM runner, model/release registry, structured event schema와 운영 dashboard를 도입한다.
3. **61–90일:** shadow/canary/rollback, drift + delayed-label monitoring, label QA/approval workflow, 비용·SLO 기반 alert를 적용한다.

## 근거 파일

- `docs/mapkit-baseline-v2.md` — rules-first, weak-case-only FastVLM 및 fail-loud contract
- `docs/confidence-gate.md` — runtime GT leakage 방지와 held-out/k-fold gate 평가
- `tools/run_algorithm.py` — versioned run record, script/data/evaluation hashes, host runtime/latency
- `tests/` — 104 local unit/regression tests passed
- `.github/` — 저장소에 directory가 없어 native CI workflow는 확인되지 않음
