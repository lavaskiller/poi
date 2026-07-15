# 해외 MapKit 경로에서 Kakao식 POI 알고리즘 재현 가능성 검토

## 결론

**조건부로 가능하다.** 현재 macOS/Swift/MapKit 환경만으로도 다음 핵심 구조는 해외 좌표에 구현할 수 있다.

1. POI 그룹별 병렬 검색
2. ID 기반 중복 제거
3. 기반시설 및 불필요 후보 제외
4. 카테고리·부속시설 보정 점수 계산
5. 1·2위 점수 차이에 따른 `.single` / `.ambiguous` 판정
6. 직접 POI 탭에서 후보 선택 UI를 더 적극적으로 표시

다만 의미를 구분해야 한다.

- **알고리즘 구조의 재현:** 가능
- **현재 저장된 후보 데이터만으로 과거 케이스를 즉시 재평가:** 불가능
- **Kakao와 동일한 후보 집합 및 선택 결과 재현:** 불가능

마지막 항목은 결함이 아니라 공급자 차이다. MapKit과 Kakao Local은 POI 커버리지, 좌표, 카테고리 체계, canonical name이 서로 다르므로 같은 수식이라도 입력 후보가 다르다. 해외에서는 “Kakao 알고리즘의 MapKit 대응판”으로 정의해야 한다.

## 현재 환경에서 확인한 사항

- macOS 26.5.2
- Swift 6.3.3
- 현재 SDK의 `MKLocalPointsOfInterestRequest.maxRadius`: **2,000m**
- `MKLocalPointsOfInterestRequest.pointOfInterestFilter` 사용 가능
- `MKMapItem.pointOfInterestCategory` 사용 가능
- `MKMapItem.identifier` 사용 가능
  - SDK 기준 iOS 18+/macOS 15+

따라서 관광·문화 후보를 900~1,200m까지 넓히는 검색은 MapKit의 2,000m 제한 안에서 수행할 수 있다. 카테고리 필터를 사용한 그룹별 요청과 MapKit identifier 기반 deduplication도 현재 환경에서 구현 가능하다.

## 현재 저장 데이터로 바로 재현할 수 없는 이유

`poi-data/generated/mapkit_candidates.jsonl`을 점검한 결과:

- 후보: 537개
- 후보가 있는 사진: 147개
- 사진당 최대 후보: 18개
- `category`가 채워진 후보: **0개**
- `provider_place_id`가 채워진 후보: **0개**
- 후보 좌표가 채워진 후보: **0개**
- 대부분의 사진은 후보가 3개만 저장됨

현재 실행 하네스도 제출 알고리즘에 아래 세 필드만 전달한다.

```json
{
  "name": "...",
  "rank": 1,
  "distance_m": 12.0
}
```

따라서 기존 snapshot만으로는 다음을 할 수 없다.

- 카테고리 배수 계산
- MapKit ID 기반 중복 제거
- 후보 좌표에서 거리 재계산 및 검증
- 기반시설을 카테고리로 정확하게 제외
- 랜드마크 그룹과 일반 그룹의 독립 검색 결과 복원
- 최대 20개 picker 후보를 일관되게 전달

또한 현재 평가 row에는 지도 확대 단계와 `directPOITap` 여부가 없다. 따라서 70/100/140/200/280m 동적 반경과 직접 탭 특수 동작을 **과거 사진 데이터에서 그대로 재현할 수 없다.** 평가용 기본 zoom/direct-tap 시나리오를 별도로 정의하거나, 실제 앱 이벤트에서 해당 값을 기록해야 한다.

## MapKit 카테고리 대응안

Kakao 코드를 그대로 번역하기보다 내부의 공급자 중립 카테고리로 정규화하는 편이 안전하다.

| 내부 그룹 | MapKit 후보 카테고리 | 초기 배수 제안 |
|---|---|---:|
| `landmark` | landmark, nationalMonument, castle, fortress, amusementPark, aquarium, zoo, nationalPark, park, beach | 0.50 |
| `culture` | museum, theater, movieTheater, musicVenue, planetarium, library, conventionCenter, stadium | 0.55 |
| `lodging` | hotel, campground, rvPark | 0.70 |
| `transit` | publicTransport, airport | 0.75 |
| `public` | police, fireStation, postOffice, school, university | 0.85 |
| `bank` | bank | 1.15 |
| `pharmacy` | pharmacy | 1.20 |
| `store` | store | 1.30 |
| `market` | foodMarket | 1.30 |
| `restaurant` | restaurant, bakery, brewery, winery, distillery | 1.40 |
| `cafe` | cafe | 1.50 |
| 기타/미분류 | 나머지 | 1.00 |

이 표는 **구현 시작값**이지 검증된 해외 최적값이 아니다. 특히 다음은 Kakao와 1:1 대응하지 않는다.

- MapKit에는 편의점 전용 카테고리가 없고 보통 `store`로 뭉친다.
- `publicTransport`는 지하철역뿐 아니라 다른 대중교통 시설을 포함할 수 있다.
- 시청·법원 등 Kakao `PO3` 전체에 대응하는 단일 government 카테고리가 없다.
- 공원, 해변, 대학, 경기장처럼 해외에서 “목적지”가 될 수 있는 범주는 Kakao 표보다 세분화가 필요하다.

따라서 초기에는 위 매핑을 쓰되 국가·도시·카테고리별 평가 결과로 배수를 다시 학습하거나 조정해야 한다.

## 제외 및 감점 규칙의 해외화

### 카테고리로 제외 가능한 항목

- parking
- restroom
- atm
- evCharger
- gasStation
- mailbox

### 이름 규칙이 추가로 필요한 항목

MapKit 카테고리만으로는 아래를 안정적으로 구분하기 어렵다.

- 버스정류장과 목적지형 교통역
- 택시승강장
- 관리사무소·경비실
- 쓰레기·분리수거 시설
- 택배함
- 입구·출구·탑승장·매표소

한국어 문자열 목록만 번역해서는 부족하다. 최소한 영어·스페인어·프랑스어 등 데이터셋의 언어별 토큰을 관리해야 한다. 예:

- 강한 제외: `parking`, `parking garage`, `restroom`, `toilet`, `ATM`, `EV charging`, `gas station`
- 부속시설 감점: `entrance`, `exit`, `gate`, `ticket office`, `ticket booth`, `platform`, `boarding`, `visitor center`, `information center`

이름 규칙은 substring 오탐을 피하도록 토큰/단어 경계와 locale을 함께 사용해야 한다.

## 권장 구현 구조

### 1. 후보 수집기 개선

현재 `tools/swift/ls_mapkit_probe.swift`의 `Ranked`는 이미 category를 읽지만 출력에서 버린다. 프로브 결과를 TSV preview가 아니라 full JSONL로 직접 저장하도록 바꾼다.

후보별 최소 필드:

```json
{
  "provider": "mapkit",
  "provider_place_id": "...",
  "name": "...",
  "lat": 0.0,
  "lon": 0.0,
  "category": "MKPOICategory...",
  "distance_m": 0.0,
  "search_group": "landmark|general",
  "search_radius_m": 250.0
}
```

identifier가 없는 구형 런타임 또는 일부 결과는 다음 합성키로 fallback할 수 있다.

```text
normalizedName + roundedLatitude + roundedLongitude + category
```

### 2. 병렬 검색

- 랜드마크 그룹과 일반 그룹을 `async let` 또는 task group으로 병렬 실행
- 필요하면 그룹 내부도 카테고리별 필터 요청으로 분리
- 결과를 `MKMapItem.identifier`로 dedupe
- 동일 ID가 여러 검색에 나타나면 가장 작은 실제 거리와 가장 구체적인 카테고리를 유지

MapKit은 한 요청에 여러 inclusion category를 지정할 수 있으므로, Kakao처럼 반드시 카테고리마다 별도 HTTP 요청을 보낼 필요는 없다. **결과 누락 여부를 평가한 뒤** 그룹 단위 요청과 카테고리 단위 요청 중 더 안정적인 방식을 선택하면 된다.

### 3. 공급자 중립 랭커

```text
effectiveDistance
  = actualDistance
  × normalizedCategoryMultiplier
  × auxiliaryNameMultiplier
```

초기 기준:

- 부속시설 이름: `× 1.45`
- 일반 ambiguity gap: `< 38m`
- landmark-only gap: 실제 거리 기준 `< 36m`
- MapKit 단순 경로와 비교 실험을 위해 `< 22m` baseline도 유지

단, 22/36/38m는 서로 다른 분포에서 만들어진 값이므로 하나로 합치지 말고 실험 파라미터로 노출하는 편이 낫다.

### 4. 직접 탭 및 zoom 입력

실제 앱 함수에는 최소 다음 context를 전달한다.

```swift
struct POIResolutionContext {
    let coordinate: CLLocationCoordinate2D
    let zoomLevel: Int?
    let isDirectPOITap: Bool
    let tappedMapItemIdentifier: MKMapItem.Identifier?
}
```

직접 탭에서 MapKit이 tapped item identifier를 제공한다면, 그 항목을 단순 거리 점수보다 강한 신호로 취급하되 주변에 복수 후보가 있으면 picker를 표시하는 정책을 유지할 수 있다.

평가 데이터에도 다음 필드가 필요하다.

- `map_zoom_level`
- `is_direct_poi_tap`
- 가능하면 `tapped_provider_place_id`

### 5. 평가 하네스 확장

`tools/run_algorithm.py::_candidate_names`에서 category, ID, 좌표, search group을 버리지 않도록 변경한다. 후보 제한도 현재 snapshot의 top-3가 아니라 full wide 결과에서 적용해야 한다.

평가는 최소 세 개를 분리한다.

1. **retrieval coverage:** 정답 POI가 후보에 들어왔는가
2. **automatic single accuracy:** 자동 선택한 1위가 정답인가
3. **picker recall:** ambiguous일 때 표시된 후보 안에 정답이 있는가

`ambiguous`를 오답으로만 세면 picker를 통해 오선택을 줄이는 제품 정책을 제대로 평가할 수 없다.

## 랜드마크 전용 경로에 대한 권장사항

구조는 재현할 수 있지만 한국 전용 예외 키워드는 해외로 복사하지 않는 것이 맞다.

- `첨성대` bbox/키워드 복구는 한국 도메인 규칙으로 유지
- 해외에서는 특정 장소 hardcode 대신 provider ID, reverse-geocoded building name, locale-aware keyword fallback을 일반화
- 랜드마크와 음식점·카페의 35m 비교는 그대로 시작할 수 있지만, MapKit 랜드마크 좌표 오차 분포를 별도로 측정해야 함

즉 범용 랭커와 장소별 emergency recovery를 분리해야 한다. 장소별 예외가 랭커 본체에 섞이면 해외 도시가 늘어날수록 유지보수와 회귀 검증이 어려워진다.

## 현실적인 실행 순서

### Phase 1 — 재현 가능한 데이터 확보

1. full MapKit 후보 JSONL 저장
2. category, identifier, 좌표 보존
3. strict/wide 및 검색 그룹 기록
4. 기존 비한국 좌표에 재프로브

### Phase 2 — Kakao식 랭커 이식

1. 내부 카테고리 정규화
2. 제외·감점 규칙 구현
3. effective distance 계산
4. single/ambiguous 결과와 후보 목록 출력

### Phase 3 — 비교 평가

동일 eval set에서 다음을 비교한다.

- A: 현재 MapKit 거리순 + 22m
- B: 해외 category-weighted + 38m
- C: landmark 우선 경로 포함
- D: 직접 탭 picker 정책 포함

주요 지표:

- 자동 선택 정확도
- 잘못된 자동 선택률
- ambiguous 비율
- picker top-8/top-20 recall
- 카테고리별 성능
- 국가·도시별 성능

### Phase 4 — 파라미터 보정

현재 Kakao 배수와 gap을 고정된 정답으로 취급하지 말고 초기값으로만 사용한다. 비한국 GT에서 grid search 또는 학습/검증 분리를 통해 다음을 보정한다.

- 카테고리 배수
- 부속시설 배수
- 일반/랜드마크 gap
- 카테고리별 검색 반경

## 최종 판단

현재 장비와 MapKit API는 구현에 충분하다. 그러나 **현재 후보 snapshot은 필요한 category/ID/좌표를 이미 잃은 상태**이므로 그 파일 위에 랭커만 얹는 방식으로는 정직하게 재현했다고 할 수 없다.

가장 작은 올바른 변경은 다음이다.

> MapKit 프로브가 full candidate의 category, identifier, 좌표, distance를 보존하게 만든 뒤, 공급자 중립 카테고리 매핑을 거쳐 Kakao식 필터·보정·모호성 판정을 실행한다.

이 전제라면 한국을 제외한 해외에 대해 알고리즘의 **구조와 제품 동작은 재현 가능**하다. 다만 결과는 Kakao와 동일한 것이 아니라 MapKit 데이터에 맞춘 해외 버전이며, 배수와 35/36/38m 기준은 해외 GT로 다시 검증해야 한다.
