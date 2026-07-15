# POI 인턴십 실행 계획

## 1. 지금 지령을 실행 항목으로 번역하면

우선순위는 다음 네 가지다.

1. **평가 프레임워크를 오늘 다른 사람이 실행할 수 있는 상태로 원격 저장소에 전달한다.**
2. **자동 POI 선택의 현재 성능과 한계를 숫자로 설명한다.**
3. **자동 선택 / 후보 선택기 / 선택 불가를 가르는 명시적 business rule을 만든다.**
4. **Yoobin과 사용자 흐름을 확정하고, 미국 인턴십 종료 시연 범위와 한국에서 이어갈 범위를 분리한다.**

핵심은 새 모델을 계속 붙이는 것보다 먼저 **handoff 가능성, 재현성, 의사결정 규칙, 데모 범위**를 닫는 것이다.

---

## 2. 저장소의 현재 상태

점검 결과:

- 로컬 `main`과 `origin/main`의 커밋 차이는 `0/0`이다.
- 그러나 아래 핵심 작업이 아직 커밋되지 않아 **현재 원격 저장소에는 최신 코드가 모두 올라가 있지 않다.**
  - rich MapKit 후보(category, provider ID, 좌표) 보존
  - 실행 하네스의 후보 메타데이터 전달
  - evaluation cohort / data snapshot hash
  - weighted MapKit 예제
  - FastVLM 실행기와 실험 보고서
  - 회귀 테스트
  - UI의 비교 가능성 표시 개선
- 현재 검증 결과:
  - `python3 -m unittest discover -s tests -v`: **13개 통과**
  - `git diff --check`: 통과
  - Python compile: 통과
  - Swift typecheck: 통과. 단, macOS 26의 `placemark` deprecation warning이 있다.

따라서 첫 번째 액션은 새 기능 개발이 아니라 **변경 파일 검토 → 문서 정합성 수정 → 커밋 → push → 깨끗한 clone에서 smoke test**다.

### 문서 정합성 상태

`docs/functional-spec.md`의 구 버전에는 provider canonical GT가 비면 `input_place_name`으로 fallback한다고 적혀 있었다. 현재 문서와 코드는 동일하게 **canonical GT만 채점하고 raw 입력명은 holdout**하도록 맞췄다.

---

## 3. 오늘 완료할 평가 프레임워크 handoff

### 3.1 완료 조건(Definition of Done)

다른 사람이 새 디렉터리에서 다음을 수행할 수 있어야 한다.

1. 원격 저장소 clone
2. `python3 server.py`
3. 브라우저에서 dashboard 접속
4. 데이터가 없을 때도 정상적인 empty state 확인
5. 허가된 로컬 데이터 또는 ZIP 추가
6. nearest baseline 실행
7. 저장된 결과와 실패 case 확인
8. 테스트 실행

### 3.2 push 전 체크리스트

- [ ] untracked 파일마다 공개 저장소에 포함해도 되는지 확인
- [ ] raw 사진, CSV, generated run/cache, API key, 개인 식별 데이터가 diff에 없는지 확인
- [x] `functional-spec.md`의 GT fallback 설명을 실제 holdout 정책과 일치시킴
- [ ] README에 최소 실행 및 테스트 명령을 명확히 기재
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `git diff --check`
- [ ] Python compile 및 Swift typecheck
- [ ] 기능 단위로 커밋하고 `origin/main`에 push
- [ ] 새 clone에서 dashboard와 baseline smoke test

### 3.3 권장 커밋 분리

1. `Preserve rich MapKit candidate metadata`
2. `Add cohort-safe run comparison metadata`
3. `Add weighted and FastVLM baselines with tests`
4. `Document evaluation results and handoff`

이미 섞인 변경이 많으므로 무리한 history 정리보다, 파일별 공개 가능성을 확인한 뒤 논리적으로 2~4개 커밋으로 나누는 것이 현실적이다.

---

## 4. 현재 자동 POI 선택에 대해 말할 수 있는 신뢰 수준

동일한 166개 채점 가능 case 기준:

| 방법 | 정확도 | 해석 |
|---|---:|---|
| MapKit nearest | 63/166 = **38.0%** | 전체 자동 선택 정확도 |
| weighted MapKit | 63/166 = **38.0%** | legacy 후보에는 category/ID/좌표가 없어 아직 공정한 full test가 아님 |
| FastVLM Top-5 | 64/166 = **38.6%** | nearest 대비 +1건, 실질적 개선은 작음 |
| MapKit Top-5 안에 GT 존재 | 76/166 = **45.8%** | retrieval ceiling |
| FastVLM의 candidate-covered selection | 64/76 = **84.2%** | GT가 Top-5에 있을 때의 조건부 선택 정확도 |

이 숫자가 뜻하는 바:

- 현재 병목은 주로 **selection model이 아니라 candidate retrieval**이다.
- “자동으로 잘 고른다”를 전체 case 기준으로 말하면 현재 약 39%이므로 제품 수준이라고 주장할 수 없다.
- 반면 정답이 후보 Top-5 안에 이미 들어온 case에서는 선택 성공률이 약 84%다.
- FastVLM 단독 override는 20건 중 4건을 고쳤지만 3건을 망가뜨렸다. 따라서 VLM이 다른 신호와 충돌할 때 무조건 덮어쓰는 정책은 안전하지 않다.
- Top-10/Top-20은 현재 retrieval을 늘리지 않고 distractor만 늘려 정확도를 낮췄다. 지금은 Top-5를 유지하는 것이 맞다.

### confidence를 어떻게 정의해야 하는가

현재 단계에서 confidence를 임의의 `0.87` 같은 모델 확률로 표현하면 안 된다. 우선은 **행동 등급(action tier)** 으로 정의한다.

- `HIGH` → 자동 선택
- `MEDIUM` → 후보 picker 표시
- `LOW` → 자동 선택하지 않고 검색/수동 입력 유도

향후 held-out validation set에서 각 tier의 실제 정답률을 측정한 뒤에만 “HIGH는 95% 이상” 같은 확률 의미를 부여한다.

평가 지표도 전체 정확도 하나가 아니라 다음을 함께 본다.

- auto-pick coverage: 전체 중 자동 선택한 비율
- auto-pick precision: 자동 선택한 것 중 정답 비율
- wrong auto-pick rate: 전체 중 잘못 자동 선택한 비율
- picker rate
- picker Top-5 recall
- no-result rate
- 국가/도시/카테고리별 위 지표
- confidence tier별 reliability

---

## 5. 제안하는 정확한 business logic v0

이 규칙은 현재 evidence에 맞춘 **보수적이고 테스트 가능한 초기 정책**이다. 38m와 category multiplier는 검증 완료 상수가 아니라 실험 시작값이다.

### Step 0 — 직접 POI 탭

- 사용자가 지도상의 POI를 직접 탭했고 provider place ID가 있으면 그 POI를 1순위로 사용한다.
- 단, 앱 이벤트에 `is_direct_poi_tap`, `tapped_provider_place_id`가 기록되어야 한다.
- 주변 후보와 명백히 충돌하거나 provider ID를 얻지 못하면 일반 흐름으로 내려간다.

### Step 1 — 후보 수집

- 기본은 MapKit wide search의 **Top-5**.
- 후보마다 `provider_place_id`, name, category, lat/lon, physical distance를 보존한다.
- 후보가 없으면 `LOW / NONE`으로 종료하고 검색 또는 수동 선택을 보여 준다.
- Top-10/20 확대는 새로운 GT가 6위 이후에 실제로 추가되는 retrieval 개선이 확인된 뒤 다시 검토한다.

### Step 2 — 정리

1. provider ID로 dedupe한다.
2. ID가 없으면 normalized name + 반올림 좌표 + category를 fallback key로 쓴다.
3. parking, restroom, ATM, EV charger, gas station, mailbox 등 목적지가 아닌 기반시설 후보는 제외한다.
4. entrance, exit, gate, ticket office, platform 등 부속시설은 제거하지 않고 감점하여 picker fallback으로 남긴다.

### Step 3 — ranking

초기 점수:

```text
effective_distance
  = physical_distance
  × category_multiplier
  × auxiliary_name_multiplier
```

- landmark/culture/lodging 등 목적지형 category는 보상한다.
- cafe/restaurant/store처럼 조밀한 상업 category는 더 보수적으로 본다.
- access point와 부속시설은 감점한다.
- multiplier와 gap은 반드시 train/validation 분리 또는 cross-validation으로 조정한다.

### Step 4 — confidence와 사용자 행동

#### `HIGH → AUTO_PICK`

다음 중 하나일 때:

1. 유효한 direct-tap provider ID가 있다.
2. weighted rank 1과 physical nearest가 같고, 아래 중 하나가 추가로 성립한다.
   - 1·2위 점수 gap이 calibration threshold 이상이다.
   - OCR/VLM이 같은 후보를 독립적으로 지지한다.
3. weighted rank 1과 VLM Top-5 선택이 같고, OCR 또는 category 신호가 반대하지 않으며 margin이 충분하다.

자동 선택 뒤에도 즉시 `변경` 또는 `되돌리기`를 제공한다.

#### `MEDIUM → SHOW_PICKER`

다음 중 하나일 때:

- 1·2위 gap이 threshold 미만이다. 초기 실험값은 일반 38m, landmark 36m.
- nearest, weighted, VLM 중 둘 이상이 서로 다르다.
- 후보는 있지만 OCR/visual evidence가 약하거나 충돌한다.
- direct tap은 있었지만 provider ID가 없거나 주변의 다른 목적지형 후보와 경쟁한다.

picker는 우선 Top-5를 보여 주고, `더 보기`에서 최대 20개까지 확장한다. 각 행에는 이름, category, 거리, 가능하면 썸네일/주소를 표시한다.

#### `LOW → NONE / MANUAL_SEARCH`

- 유효 후보가 없다.
- 필터 후 기반시설/부속시설 후보만 남는다.
- 이미지, 좌표, provider 결과가 부족해 confidence를 만들 수 없다.
- 후보가 모두 강하게 충돌하고 어떤 후보도 독립 신호 두 개의 지지를 받지 못한다.

이 경우 억지로 첫 후보를 저장하지 않고 `장소 검색`, `지도에서 선택`, `장소 없음`을 제공한다.

### VLM 사용 원칙

- VLM은 **retriever가 아니라 Top-5 reranker/확인 신호**로만 사용한다.
- VLM 단독으로 nearest를 override하지 않는다.
- override에는 OCR, category, margin, 반복 prompt agreement 중 최소 하나의 추가 근거를 요구한다.
- latency가 허용되지 않는 제품 경로에서는 background suggestion으로 사용하고, distance/category rule을 즉시 응답 경로로 둔다.

---

## 6. Yoobin과 확정할 사용자 흐름

회의에서는 화면 디자인부터 시작하지 말고 아래 결정을 먼저 내린다.

### 결정해야 할 질문

1. 잘못된 자동 선택과 picker 한 번 더 누르게 하는 것 중 어느 비용이 더 큰가?
2. 자동 선택된 POI는 저장 전에 보여 주는가, 저장 후 undo를 제공하는가?
3. picker는 Top-3, Top-5 중 무엇이 기본인가?
4. `장소 없음`과 `모르겠음`을 별도 선택지로 둘 것인가?
5. 사진당 POI 하나만 가능한가, 여러 POI 또는 area-level place도 가능한가?
6. direct map tap, photo import, 자동 추천이 같은 flow를 쓰는가?
7. 사용자의 수정 결과를 향후 GT/feedback으로 저장해도 되는가?

### 제안 flow

```text
사진/지도 좌표 입력
  → 후보 검색
  → confidence 분기
      HIGH: 자동 선택 + 변경/undo
      MEDIUM: Top-5 picker
      LOW: 지도/텍스트 검색 또는 장소 없음
  → 사용자 확정
  → 선택 결과와 수정 여부를 feedback event로 기록
```

### 회의 산출물

- 세 상태의 wireframe: auto / picker / none
- 각 상태로 들어가는 rule 표
- 사용자 수정 event schema
- demo에서 보여 줄 5~10개 대표 scenario
- 성공 기준: auto precision 목표와 허용 picker rate

---

## 7. 미국 인턴십 종료까지의 MVP

기간이 명시되지 않았으므로 기능을 deadline이 아니라 deliverable 단위로 쪼갠다.

### MVP 0 — Evaluation handoff

**목표:** 다른 개발자가 원격 저장소만으로 도구를 실행하고 같은 평가 절차를 재현.

포함:

- dashboard
- dataset ingest/validation
- baseline run
- retrieval vs selection metric 분리
- persisted run 비교
- cohort/snapshot hash
- 테스트와 문서

완료 기준:

- clean clone smoke test 성공
- 원격 커밋 SHA 공유
- 데이터가 없을 때와 허가된 데이터가 있을 때 모두 정상

### MVP 1 — Confidence policy simulator

**목표:** `AUTO_PICK / SHOW_PICKER / NONE`을 case별로 출력하고 risk-coverage를 평가.

포함:

- rich MapKit 후보 재수집
- category/ID/좌표 보존
- weighted ranker
- confidence tier와 reason code
- auto precision, auto coverage, picker recall 지표
- threshold 조정 UI 또는 config

완료 기준:

- 같은 snapshot에서 nearest와 정책 v0 비교
- confidence tier별 실측 정답률 표시
- 오류 case를 UI에서 확인 가능

### MVP 2 — End-to-end user-flow demo

**목표:** 기술 비전이 아니라 실제 동작하는 사용자 흐름을 시연.

데모 순서:

1. 명확한 case → 자동 선택
2. 두 후보가 가까운 case → picker
3. 후보 없음 → 수동 검색/장소 없음
4. 사용자가 자동 선택을 수정
5. dashboard에서 수정 전후와 confidence reason 확인

제품 앱 통합 일정이 불확실하면 local web demo로 먼저 완성하고, 앱 integration은 다음 단계로 둔다.

### Stretch — retrieval 개선

- OCR 키워드로 MapKit local search 보강
- landmark/general 병렬 검색
- 검색 반경 및 category group 실험
- rich candidate snapshot에서 Top-10이 실제 retrieval을 늘리는지 재평가

이 항목은 MVP 1의 데이터가 확보된 뒤에만 진행한다.

---

## 8. 한국에서 이어갈 가능성이 높은 일

미국 인턴십 종료 시점에 남길 수 있는 후속 범위:

- iOS/macOS 제품 코드에 direct-tap context와 picker 통합
- Kakao provider candidate 수집 및 한국 eval 활성화
- 국가/도시별 category multiplier 재보정
- 더 큰 허가 데이터셋으로 confidence calibration
- OCR-assisted retrieval과 landmark search
- latency, caching, offline 동작 최적화
- MapKit `placemark` deprecated API 교체
- feedback event를 학습/검증 데이터로 만드는 데이터 거버넌스

미국 기간에는 **재현 가능한 evaluator + 명확한 policy + demo flow**까지 닫고, provider 확장과 production integration을 한국 후속으로 넘기는 것이 가장 현실적이다.

---

## 9. 바로 공유할 수 있는 진행 보고 문안

> 우선 POI evaluation framework를 handoff 가능한 상태로 마무리하겠습니다. 현재 로컬에는 rich MapKit candidate metadata, run cohort/snapshot identity, weighted/FastVLM baseline, 테스트가 반영돼 있지만 아직 원격에 커밋되지 않은 변경이 있어 공개 가능 파일과 문서 정합성을 확인한 뒤 push하고 clean-clone smoke test까지 하겠습니다.
>
> 현재 166개 eligible case에서 nearest는 38.0%, FastVLM Top-5는 38.6%이고, GT가 Top-5 후보 안에 있는 비율은 45.8%입니다. 따라서 현재 핵심 병목은 candidate retrieval입니다. GT가 Top-5에 있는 case만 보면 FastVLM selection은 84.2%이지만, 전체 자동 선택 성능을 제품 수준이라고 말할 단계는 아닙니다.
>
> 자동 선택은 하나의 불확실한 probability 대신 HIGH/AUTO, MEDIUM/PICKER, LOW/NONE의 세 단계 business rule로 정의하겠습니다. direct tap ID, candidate margin, distance/category ranking, OCR/VLM agreement를 사용하고 VLM 단독 override는 허용하지 않는 보수적 정책을 제안합니다.
>
> Yoobin과는 auto-select, picker, no-result 세 user flow와 correction feedback을 확정하겠습니다. 미국 인턴십 종료 데모는 ① 평가 framework handoff, ② confidence policy simulator, ③ auto/picker/none end-to-end demo로 잡고, Kakao/Korea provider 및 production integration은 남은 기간에 따라 한국 후속 작업으로 분리하겠습니다.
