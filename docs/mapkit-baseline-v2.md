# mapkit-baseline v2

**이 문서가 다루는 것:** 시드·대시보드에 올라가는 알고리즘 **`mapkit-baseline` 버전 2**  
**엔트리포인트:** `examples/mapkit_baseline_v2.py` 의 `predict(case)`  
**번들 이름:** `ensemble_v2` (`tools/bundle_submission.py`)

다른 실험 런(`selector-loop70` 스티치 등)은 여기에 포함하지 않는다.  
v2는 **한 장의 사진 + 후보 목록**이 들어올 때마다 아래 순서로 **한 번** 답을 낸다.

---

## 무엇을 하는 알고리즘인가

MapKit이 GPS 근처에서 준 **장소 후보 목록** 안에서,  
사진에 찍힌 곳으로 보이는 **이름 하나**를 고른다.

| 항목 | 내용 |
|------|------|
| 입력 | `nearby_candidates`, `ocr_text`, `image` (및 메타) |
| 출력 | `{ "prediction": "장소이름", "reason": "..." }` — 이름 없으면 빈 문자열(abstain) |
| 정답(GT) | **사용 안 함**. 채점은 하네스가 나중에 함 |
| 후보 밖 이름 | 원칙적으로 만들지 않음. VLM이 말해도 목록에 있는 표기로만 매핑 |

v1(`mapkit_ocr_override` / weighted + unique OCR)보다  
**OCR 규칙이 세고**, 약한 케이스에만 **FastVLM**을 붙인 버전이다.

---

## 전체 흐름

코드 순서 그대로다 (`predict`).

```text
predict(case)
│
├─ 후보 0개? → prediction "" , reason no_candidates
│
├─ [A] 결정론 코어  (_core_pick)
│     list_fit 과 access_ocr 를 각각 돌린 뒤 하나만 채택
│     (둘 다 실패 시 weighted → nearest)
│
├─ reason == list_fit ?  → 그 이름으로 즉시 반환  (VLM 안 부름)
│
├─ [B] access_ocr 가 “약하면” FastVLM skill @ top-5
│     약함 = access_ocr 결과가 없거나, 거리 1등(nearest)과 같음
│     짧은·단정 답만 코어를 덮어씀 (vlm_skill)
│     UNKNOWN / 애매 / 장황 → 코어 유지
│
└─ [C] structure_refine (list_fit 쪽 규칙)
      이름이 바뀌면 reason = structure_refine
```

환경 변수 `POI_VLM_MODE=live`(기본)인데 FastVLM을 못 돌리면  
**OCR만 돌리고 점수를 속이지 않는다** — 런 전체를 실패시킨다.  
의도적으로 코어만 보려면 `POI_VLM_MODE=off`.

---

## [A] 결정론 코어 `_core_pick`

VLM 없이, 후보 + OCR만으로 이름을 고른다.

### 두 개의 규칙 엔진

| 이름 | 파일 | 하는 일 |
|------|------|---------|
| **access_ocr** | `examples/selector_access_ocr.py` | (1) OCR이 후보 이름과 강하게 겹치면 그 후보 (2) 아니면 거리 1등이 Stop/Gift Shop/Entrance 등이면 **같은 이름 줄기의 본체 후보**로 (3) 아니면 거리 1등 |
| **list_fit** | `examples/selector_list_fit.py` | 더 센 OCR 점수(긴 고유 토큰 가중, 약한 OCR로 1등 뒤집기 금지) + generic(화장실·주차 등) 제외 + 접근 라벨 강등 + 마지막에 structure refine 일부 |

**왜 두 개를 돌리나.**  
list_fit이 access_ocr와 **다른 이름**을 내면, OCR/리스트 적합이 “거리 쪽과 다르게 말할 만큼” 강하다는 뜻으로 보고 **list_fit을 채택**한다.  
같으면 access_ocr(또는 list_fit만 있는 경우 등) 쪽으로 가고, 뒤에 VLM 여부를 본다.

### 코어 선택 표 (`_core_pick`)

| 조건 | prediction | reason |
|------|------------|--------|
| list_fit 있고 access_ocr와 **다름** | list_fit | `list_fit` |
| 위가 아니고 access_ocr 있음 | access_ocr | `access_ocr` |
| 위가 아니고 list_fit만 있음 | list_fit | `list_fit_only` |
| 둘 다 없음 → weighted 성공 | weighted | `weighted` |
| 그마저 없음 | 후보[0] 이름 | `nearest` |

`weighted`는 `examples/mapkit_weighted.py` — 카테고리 가중 유효거리로 고르는 백업이다.

### access_ocr “본체” 규칙이 의미하는 것

지도에는 목적지 핀 옆에 **정류장·기프트샵·기부함** 핀이 따로 있는 경우가 많다.  
GPS상 그 핀이 1m 더 가까우면 “가장 가까운 곳”만 쓰면 답이 잘못 나온다.

예 (후보 목록 안에 둘 다 있을 때):

- 1등 `Banff Gondola Stop` → 고름 `Banff Gondola`
- 1등 `Goulding's Gift Shop` → 고름 `Goulding's Lodge` (이름 줄기가 맞고 거리가 가까운 본체)

새 이름을 지어내지 않고, **이미 목록에 있는** 다른 후보로 옮긴다.

---

## [B] FastVLM — 약할 때만

### 언제 부르나 (`_should_call_vlm`)

`reason == list_fit` 이면 **여기서 끝** — VLM 호출 없음.

그 외에는 access_ocr 결과(`pred_acc`)를 본다.

| pred_acc | VLM 호출 |
|----------|----------|
| 비어 있음 | 예 |
| 거리 1등(nearest)과 **같음** (정규화 비교) | 예 |
| nearest와 **다름** | 아니오 (규칙이 이미 거리를 이겼음) |

즉 “값싼 규칙이 거리 1등에서 못 벗어난 케이스”에만 사진을 본다.  
특정 사진 리스트를 골라 돌리는 residual이 **아니다**. 조건에 걸리는 모든 케이스에 동일 적용.

### 어떻게 부르나

| 항목 | 값 |
|------|-----|
| 모듈 | `examples/mapkit_vlm_live.py` |
| 후보 창 | 거리순 **상위 5개** (`VLM_K = 5`) |
| 스타일 | `skill` (`VLM_STYLE`) |
| 모델 | FastVLM 0.5B (Apple, MPS) |

skill 프롬프트 요지: 후보 번호 하나만, 또는 **UNKNOWN**. 설명 금지.  
간판/로고 → 랜드마크 → 접근 라벨보다 목적지 선호. 음식만 보인다고 옆 가게 고르지 말 것.

### 답을 언제 믿나 (`_high_confidence_vlm_name`)

모델 raw 문자열이 아래를 **모두** 통과할 때만 코어를 덮어쓴다.

1. 비어 있지 않음  
2. `UNKNOWN` 없음  
3. hedge 문구 없음 (`not clearly`, `however`, `closest match`, `likely` …)  
4. 길이 ≤ **16** 글자 (장황 free-text 차단)  
5. `parse_selection`으로 후보 인덱스 파싱 성공  
6. 그 이름이 **지금 코어 예측과 다름**

통과 시 `reason = vlm_skill`.  
실패 시 코어 이름 유지 (억지 오버라이드 없음).

`POI_VLM_MODE=off` 이면 VLM을 안 돌리고 `reason`에 `+vlm_mode_off`만 붙인다.  
이게 **허용된** 다운그레이드다. 그 외 이미지 없음·모델 오류 등은 **RuntimeError**.

### 캐시

`POI_VLM_CACHE` JSONL은 **같은 입력 재호출 절약용 메모**다.  
캐시 키에 모델·프롬프트·후보·사진이 들어간다.  
“미리 골라 둔 어려운 사진만 맞춰 둔 답안지”가 아니다. 파일을 지우면 전부 다시 추론한다.

---

## [C] structure_refine

VLM 전후 최종 이름에 `selector_list_fit._refine_structure` 를 한 번 더 적용한다.  
(코어가 list_fit으로 끝난 경우에도, list_fit 내부에서 이미 refine을 거친 뒤  
여기서 한 번 더 돌 수 있다.)

| 패턴 | 동작 |
|------|------|
| 이름이 Vigo / Coinstar 등 매장 안 키오스크 | 상위 후보 중 supermarket/grocery 쪽으로 |
| 이름에 trail/hike 가 있고 같은 고유 어간이 후보에 반복 | Point / Museum 쪽 대표 이름 선호 |

바뀌면 `reason = structure_refine`.

---

## reason 값 요약

| reason | 의미 |
|--------|------|
| `no_candidates` | MapKit 목록 비음 → 빈 예측 |
| `list_fit` | OCR/리스트 적합이 access와 달라서 채택. **VLM 스킵** |
| `access_ocr` | access_ocr 채택 (이후 VLM이 안 덮었거나 약하지 않음) |
| `list_fit_only` | access 실패, list_fit만 있음 |
| `weighted` / `nearest` | 규칙 실패 후 백업 |
| `…+vlm_mode_off` | 코어 + VLM 의도적 미사용 |
| `vlm_skill` | FastVLM 짧은 답이 코어를 덮음 |
| `structure_refine` | 마지막 구조 규칙으로 이름 변경 |

---

## 의존 모듈

번들 `ensemble_v2`가 한 파일로 묶는 구성:

| 모듈 | 역할 |
|------|------|
| `mapkit_baseline_v2` | 오케스트레이션 (`predict`) |
| `selector_list_fit` | list_fit + structure_refine |
| `selector_access_ocr` | access_ocr |
| `mapkit_weighted` | weighted 백업 |
| `mapkit_vlm_live` | FastVLM 추론·프롬프트·캐시 |

하네스는 `examples/` 를 PYTHONPATH에 안 넣으므로, 제출·시드 재실행은 반드시 번들을 쓴다.

---

## 실행

```bash
# FastVLM (Apple Silicon) — live 모드에 필요
./tools/setup_fastvlm.sh

export POI_DATA_DIR="$(pwd)/poi-data"
export POI_PREDICT_PYTHON="$POI_DATA_DIR/tools/fastvlm-venv/bin/python"

# 라이브 앙상블 (기본 POI_VLM_MODE=live)
$POI_PREDICT_PYTHON tools/run_algorithm.py \
  --name mapkit-baseline \
  --script <(python3 tools/bundle_submission.py ensemble_v2) \
  --params image,nearby_candidates,ocr_text
```

| 환경 변수 | 기본 | 의미 |
|-----------|------|------|
| `POI_VLM_MODE` | `live` | `live` · `off` · `cache_first` |
| `POI_VLM_CACHE` | data 아래 live cache JSONL | 호출 메모이 |
| `POI_FASTVLM_REPO` / `POI_FASTVLM_MODEL` | `poi-data/tools/ml-fastvlm`… | 모델 경로 |
| `POI_PREDICT_PYTHON` | fastvlm-venv 자동 탐지 | predict 프로세스 |

대시보드 New run에서 mapkit-baseline v2 / ensemble 번들을 골라도 동일 코드 경로다.

---

## v1과의 차이 (한 줄)

| | mapkit-baseline **v1** | mapkit-baseline **v2** |
|---|---|---|
| 코어 | weighted + unique OCR override | **list_fit vs access_ocr** 코어 |
| 비전 | 없음 | 약할 때만 **FastVLM skill@5**, 짧은 답만 채택 |
| 실패 시 | (해당 없음) | live인데 VLM 불가면 **런 실패** (가짜 앙상블 점수 방지) |

시드에 들어 있는 v2 점수는 아카이브이며, 머신을 바꿔 라이브 재실행하면 숫자가 달라질 수 있다.  
공정 비교는 **같은 후보 스냅샷 + 같은 가중치 + live 재실행**으로 한다.

---

## 이 문서에 없는 것

- `selector-loop70` 오프라인 스티치·residual 캐시 합성  
- confidence gate / 지오그래픽 폴백 제품 정책  
- Kakao 전용 파이프라인  

위는 v2 `predict` 계약 밖이다.
