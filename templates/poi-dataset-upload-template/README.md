# POI dataset upload template

사용자는 이 폴더 구조를 유지한 뒤 ZIP으로 압축해서 업로드한다.

## 필수 입력

- `photos/`: 평가할 이미지 파일
- `manifest.csv`: 이미지와 사용자가 고른 GT 원문 매핑

## manifest.csv 최소 컬럼

| column | required | description |
|---|---:|---|
| `photo` | O | ZIP 루트 기준 이미지 상대 경로. 예: `photos/IMG_0001.jpg` |
| `gt_input_raw` | O | 사용자가 고른 정답 원문. 장소명, 지도 공유 URL, provider place id, 이름+주소 등 허용 |
| `notes` | 선택 | 사람이 남기는 참고 메모 |

## 선택 컬럼 (EXIF fallback)

기본적으로 `capture_lat`, `capture_lon`, `timestamp`, `country`, `city`는 사용자가 직접 넣지 않는다. 도구가 이미지 EXIF와 좌표 기반 조회로 자동 추출/추정하고, 실패한 행만 보정 대상으로 표시한다.

다만 사진에서 위치·촬영정보가 제거된 export(예: 지도 앱에서 재인코딩되어 EXIF GPS가 비어 있는 경우)라면, 아래 컬럼을 manifest에 직접 채워 넣을 수 있다. 값이 있으면 ingest가 그대로 사용하고(빈 값만 EXIF에서 보충), 없으면 기존대로 EXIF 추출을 시도한다.

| column | description |
|---|---|
| `capture_lat` / `capture_lon` | 촬영 위도/경도 (십진수). `lat`/`lon` 별칭도 허용 |
| `timestamp` | 촬영 시각 (ISO 8601, 예: `2026-07-05T00:25:23Z`) |

## manifest.csv 예시

```csv
photo,gt_input_raw,notes
photos/IMG_0001.jpg,Blue Bottle Coffee Shibuya,optional note
photos/IMG_0002.jpg,https://map.kakao.com/link/map/...,optional note
```

EXIF가 비어 있는 export를 좌표·촬영시각과 함께 올리는 경우:

```csv
photo,gt_input_raw,capture_lat,capture_lon,timestamp,notes
photos/0001.jpg,Shadow Lakes Golf Club,37.9298957,-121.7415443,2026-07-05T00:25:23Z,Golf
```
