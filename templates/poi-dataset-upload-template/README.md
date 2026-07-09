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

## manifest.csv 예시

```csv
photo,gt_input_raw,notes
photos/IMG_0001.jpg,Blue Bottle Coffee Shibuya,optional note
photos/IMG_0002.jpg,https://map.kakao.com/link/map/...,optional note
```

`capture_lat`, `capture_lon`, `timestamp`, `country`, `city`는 사용자가 직접 넣지 않는다. 도구가 이미지 EXIF와 좌표 기반 조회로 자동 추출/추정하고, 실패한 행만 보정 대상으로 표시한다.
