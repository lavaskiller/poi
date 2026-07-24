# Best algorithm: selector-loop70 (and live twin)

이 문서는 현재 평가 세트에서 **가장 높은 점수를 낸 알고리즘**이  
**무엇을 입력으로 받아, 어떤 순서로, 왜 그렇게 고르는지**를 설명합니다.

코드 파일 목록만 나열하지 않고, **한 장의 결정 흐름**으로 읽히게 썼습니다.

---

## 1. 한 줄 요약

> GPS 주변 MapKit 후보 목록에서,  
> **값싼 규칙(OCR·접근점 제거)으로 먼저 고르고**,  
> 그게 “그냥 제일 가까운 곳” 수준으로 약할 때만  
> **사진(VLM)으로 후보를 다시 고른다.**

| | Offline champion | Live twin (재현·배포용) |
|---|---|---|
| **이름** | `selector-loop70` | `mapkit-baseline` v2 |
| **점수 (166 eligible)** | **exact 48%** (80/166) · **canonical 70%** (117/166) | 시드/라이브 재측정 (아카이브 ~48%대; VLM 환경 의존) |
| **코드** | `tools/stitch_loop70_ensemble.py` + 구성 셀렉터들 | `examples/mapkit_baseline_v2.py` (`ensemble_v2` 번들) |
| **성격** | 여러 런·캐시를 **스티치**한 최고 기록 | 같은 철학의 **완전 라이브** `predict()` |

**exact** = 이름 문자열 일치(엄격).  
**canonical** = alias / related_credit 등 라벨 관계 포함(제품에 더 가깝게 “같은 장소로 인정”).

> **중요:** loop70의 공식 ≥70% pass 기록은 **오프라인 스티치 + residual VLM 캐시**를 포함합니다.  
> 앱에 넣을 “한 함수”에 가장 가까운 것은 **mapkit-baseline v2** 입니다.  
> 둘 다 아래 파이프라인 철학은 같습니다.

---

## 2. 입력이 뭐고, 출력이 뭔가

```text
입력 (predict 시점에 GT 없음)
├─ nearby_candidates[]   MapKit 근처 POI (거리순, category/id 포함)
├─ ocr_text              기기 Vision OCR (간판·메뉴 텍스트)
└─ image                 사진 (VLM이 켜질 때만 사용)

출력
└─ place name 문자열  (또는 빈 문자열 = abstain)
   + reason 태그 (list_fit / vlm_skill / …)
```

평가 때만 CSV의 ground truth와 비교합니다.  
**예측 경로에는 GT가 들어가지 않습니다.**

---

## 3. 전체 그림 (loop70 / v2 공통 철학)

```text
                    ┌─────────────────────────┐
   사진 + GPS  ───► │ MapKit nearby (top ~20) │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
     ┌────────────────┐                 ┌──────────────────┐
     │ list_fit       │                 │ access_ocr       │
     │ 강한 OCR 매칭  │                 │ OCR + 접근점강등 │
     │ 구조 refine    │                 └────────┬─────────┘
     └───────┬────────┘                          │
             │                                   │
             └────────────┬──────────────────────┘
                          ▼
              list_fit 이 access_ocr 와 다르면?
                    │
          yes ──────┤────── no
           │                 │
           ▼                 ▼
     list_fit 채택     access≈nearest (약함)?
                              │
                    yes ──────┤────── no
                     │                 │
                     ▼                 ▼
              FastVLM (skill)     access_ocr 유지
              짧은 확신 답만 채택
                     │
                     └────────┬────────
                              ▼
                     structure_refine
                     (키오스크→마트, 트레일→포인트 등)
                              ▼
                         최종 place name
```

직관:

1. **글자가 보이면 OCR이 이김** (거리보다 증거를 우선).  
2. **버스 정류장 / 기프트샵 / 화장실** 같은 “접근·부대시설” 1등은 본체로 끌어올림.  
3. 그래도 “그냥 제일 가까운 곳”이면 **사진으로 후보 중 고름**.  
4. VLM은 **짧게·단정적으로** 고를 때만 믿음 (장황한 추측 문장은 버림).

---

## 4. 단계별 동작

### Step A — `access_ocr` (값싼 기본선)

**파일:** `examples/selector_access_ocr.py`

| 순서 | 규칙 | 예시 |
|------|------|------|
| 1 | OCR이 후보 이름과 강하게 겹치면 그 후보 | 간판 `CAPILANO` → Capilano … Park |
| 2 | rank-1이 Stop / Gift Shop / Entrance 등이면, 이름 핵이 같은 비-접근 후보로 | *Banff Gondola **Stop*** → *Banff Gondola* |
| 3 | 아니면 거리 1등 (nearest) | |

역할: **VLM 없이** 자주 나는 실패(접근점이 1등)를 줄입니다.

---

### Step B — `list_fit` (OCR·리스트 적합도 강화판)

**파일:** `examples/selector_list_fit.py`  
**후보 창:** 보통 top **10–20** (loop70 스티치는 limit 20).

access_ocr보다 공격적인 OCR 점수:

- 긴 고유 토큰(길이 ≥7) OCR 히트에 큰 가산점  
- OCR 오타 허용(긴 토큰 fuzzy, 예: SUSPENSTON ≈ suspension)  
- rank-1을 뒤집으려면 **점수 마진**이 있어야 함 (약한 OCR 플립 방지)  
- 순수 generic (`Restroom`, `Parking` …) 제외  
- 마지막에 **structure refine** (아래 Step D)

**스티치 규칙 (핵심):**

```text
if list_fit 결과 ≠ access_ocr 결과:
    → list_fit 채택   # OCR/구조가 “다른 답을 말할 정도로” 강함
else:
    → access 쪽 유지 후, 약하면 VLM으로
```

즉 list_fit은 **항상 이기지 않고**, access와 **의견이 갈릴 때만** 이깁니다.

---

### Step C — 사진 모델 (VLM) — “약할 때만”

| | Offline loop70 | Live mapkit-baseline v2 |
|---|---|---|
| 트리거 | residual / cascade 스티치, skill 캐시 등 | **access_ocr ≈ nearest** 인 모든 케이스에 동일 적용 |
| 모델 | FastVLM 0.5B (캐시된 출력 재사용 가능) | 동일, **라이브 추론** (캐시는 메모이제이션만) |
| 프롬프트 | skill / place_match 등 실험 혼합 | **skill @ top-5**, UNKNOWN 허용 |
| 수락 조건 | 후보 이름 복원 + 길이 필터 등 | **짧은 답만** (≤16자), hedge 문구 거부, 번호/유일 이름 파싱 |

**Live v2가 VLM 답을 버리는 경우 (의도적):**

- `UNKNOWN`
- “not clearly… however closest is …” 식 hedge
- 긴 free-text (0.5B가 추측으로 이름 발명하는 패턴이 코호트에서 손해)

이때는 **access_ocr를 유지**합니다.  
“무조건 VLM  Believes”가 아니라 **고-precision 오버라이드**입니다.

---

### Step D — `structure_refine`

**파일:** `examples/selector_list_fit.py` 의 `_refine_structure`

OCR이 이미 잠근 이름은 건드리지 않고, 구조 패턴만:

| 패턴 | 동작 |
|------|------|
| rank가 Vigo / Coinstar 등 **매장 안 키오스크** | 근처 supermarket / grocery 이름으로 |
| 현재 픽이 trail/hike 이고, 주변에 같은 고유 stem이 잔뜩 | Point / Museum 쪽 클러스터 대표로 |

loop70 v5 노트: 이 refine이 소수의 케이스를 더 끌어 canonical 70%대에 기여.

---

### Step E — (Offline only) free-text name recovery

**파일:** `tools/stitch_loop70_ensemble.py` 의 `recover_name`

과거 VLM raw 출력에서 따옴표·부분 문자열로 **후보 리스트에 있는 이름만** 복원.  
라이브 v2는 이 경로를 쓰지 않고, 짧은 skill 파싱만 씁니다 (장황 free-text가 평균적으로 손해).

---

## 5. 점수 해석 (selector-loop70 v5, n=166)

| 지표 | 값 | 의미 |
|------|-----|------|
| exact | 80 / 166 (**48%**) | 문자 그대로 GT와 동일 |
| canonical | 117 / 166 (**70%**) | alias + related_credit 포함 |
| abstain | 11 | 후보 0 등 |
| wrong (exact 기준 잔여) | 37 | 아직 틀린 구체 POI |

`match_kind` 대략: exact 80 · alias 16 · related_credit 21 · related 1 · wrong 37 · abstain 11.

**baseline-nearest**는 같은 코호트에서 exact ~38%대.  
loop70은 거리 1등 대비 **+10%p exact**, canonical 쪽은 라벨 관계와 함께 **~70%** 고지.

---

## 6. 왜 이 구조인가 (설계 의도)

| 실패 유형 | 대응 단계 |
|-----------|-----------|
| 간판은 보이는데 더 가까운 잡 POI가 1등 | OCR (`list_fit` / `access_ocr`) |
| 목적지 앞 *Stop / Gift Shop* 이 1등 | access demote |
| OCR 약함·실내·밀집 상권 | VLM (약할 때만) |
| VLM 환각·장황 추측 | 짧은 답만 수락 / UNKNOWN 유지 |
| 마트 안 키오스크·트레일 노드 | structure_refine |

**카테고리 분류기를 쓰지 않습니다.**  
카테고리는 weighted 거리 등에 쓰일 수 있지만, loop70 본체는  
**후보 리스트 + OCR + (조건부) 사진** 입니다.

---

## 7. 재실행 방법

### Offline 스티치 (기록 재현에 가깝게)

```bash
# 선행: access_ocr / photo-match cascade 런 JSON, skill residual cache 등
python3 tools/stitch_loop70_ensemble.py
```

의존 기본 경로(스크립트 argparse 참고):

- `poi-data/generated/runs/selector-access-ocr__v1.json`
- `poi-data/generated/runs/selector-photo-match-cascade__v2.json`
- `poi-data/generated/vlm_skill_k20_loop70_residual_cache.jsonl`

### Live ensemble (배포·공정 비교용)

```bash
# FastVLM 준비 (Apple Silicon)
./tools/setup_fastvlm.sh

poi-data/tools/fastvlm-venv/bin/python tools/run_algorithm.py \
  --name mapkit-baseline \
  --script <(python3 tools/bundle_submission.py ensemble_v2) \
  --params image,nearby_candidates,ocr_text
```

VLM 없이 deterministic core만:

```bash
POI_VLM_MODE=off python3 tools/run_algorithm.py …
```

| 환경 변수 | 기본 | 역할 |
|-----------|------|------|
| `POI_VLM_MODE` | `live` | `live` / `off` / `cache_first` |
| `POI_PREDICT_PYTHON` | fastvlm-venv 자동 | `predict` 서브프로세스 |
| `POI_VLM_CACHE` | mapkit_baseline_v2_live_cache.jsonl | 라이브 호출 메모이 (삭제 시 재추론) |

`live`인데 FastVLM이 없으면 **조용히 OCR-only로 점수를 속이지 않고 실패**합니다.

---

## 8. 관련 파일 지도

| 역할 | 경로 |
|------|------|
| Offline 스티치 엔트리 | `tools/stitch_loop70_ensemble.py` |
| Live ensemble `predict` | `examples/mapkit_baseline_v2.py` |
| Live FastVLM 런타임 | `examples/mapkit_vlm_live.py` |
| list_fit | `examples/selector_list_fit.py` |
| access_ocr | `examples/selector_access_ocr.py` |
| 카테고리 가중 거리 (core fallback) | `examples/mapkit_weighted.py` |
| 셀렉터 이름·시드 표 | `tools/SELECTORS.md` |
| 제출 번들 | `python3 tools/bundle_submission.py ensemble_v2` |

셀렉터 전체 목록·구 파일명 매핑은 [`tools/SELECTORS.md`](../tools/SELECTORS.md) 참고.

---

## 9. 이 알고리즘이 *아닌* 것

- 딥러닝 end-to-end place ID 모델이 아님  
- 카테고리/지역 사전 분류 후 분기하는 시스템이 아님 (평가 슬라이스용 카테고리와 무관)  
- “VLM이 항상 최종 결정”이 아님 — **약한 케이스의 신중한 오버라이드**  
- loop70 최고 점수 JSON ≠ 프로덕션 단일 바이너리 (라이브는 v2 계약 사용)

---

## 10. 다음 제품 연결 (참고)

잘못 고른 구체 POI를 줄이려면, 이 파이프라인 **위에** confidence gate를 올리는 편이 자연스럽습니다.

- 후보 0 / abstain → 지오그래픽만  
- margin 애매 · OCR 무 · VLM 미호출 → POI 대신 지역  
- list_fit·짧은 VLM 합의 → 구체 POI  

그 게이트 튜닝 UI는 이 문서 범위 밖이며, 알고리즘 본체 이해는 여기까지면 충분합니다.

---

*Metrics snapshot: `selector-loop70` v5 on the private 166-case eligible cohort; re-runs and label-relation files can move the number slightly. Prefer live v2 for apples-to-apples future comparisons.*
