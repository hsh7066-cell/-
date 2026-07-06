# 지역난방 고객 지도

강남/서초 지역 아파트(지역난방 고객) 위치를 지도에 표시합니다. 세대수에 따라 원 크기가,
내구연수에 따라 원 색상이 달라집니다. 서버 없이 `index.html`을 더블클릭해서 바로 사용할 수
있습니다.

## 파일 구성

- `index.html` — 지도 페이지. 열면 `data/apartment_data.js`를 자동으로 읽어 지도를 그립니다.
- `data/apartment_data.csv` — 고객 정보 원본(사람이 수정하는 파일).
- `data/apartment_data.js` — 위 CSV를 지도가 읽을 수 있게 변환한 파일(자동 생성, 직접 수정 금지).
- `scripts/csv_to_js.py` — CSV → JS 변환 스크립트.
- `get_latlng.py` — 엑셀(주소 열 포함) → 카카오 지오코딩 → CSV 생성 스크립트.
- `lib/leaflet/` — 지도 라이브러리(Leaflet)를 로컬에 내려받아 둔 것. 인터넷이 없어도
  지도 화면·마커·팝업이 정상 동작합니다. 다만 배경 지도 이미지(타일)는 OpenStreetMap
  서버에서 받아오므로, 배경 지도까지 보려면 인터넷 연결이 필요합니다.

## 고객 정보를 주기적으로 업데이트하는 방법

지도 화면(`index.html`)은 그대로 두고, 데이터만 갱신하면 됩니다.

1. (필요 시) 엑셀에 새 주소가 있으면 위도/경도를 구합니다.
   ```
   set KAKAO_REST_KEY=발급받은_카카오_REST_키   (PowerShell: $env:KAKAO_REST_KEY="키")
   python get_latlng.py
   ```
   `get_latlng.py` 상단의 `IN_XLSX` 경로를 본인 엑셀 파일 위치로 바꿔주세요.
2. `data/apartment_data.csv`를 열어 세대수, 내구연수, 기계실등급, 비고 등을 직접 수정해도 됩니다.
   (열 이름: 아파트명, 주소, lat, lng, 구, 세대수, 내구연수, 기계실등급, 비고)
3. 변환 스크립트를 실행합니다.
   ```
   python scripts/csv_to_js.py
   ```
4. 이미 열어둔 `index.html` 탭을 새로고침(F5)하면 최신 데이터가 반영됩니다.

CSV만 임시로 다른 파일을 확인하고 싶다면, 지도 페이지 상단의 "다른 CSV 불러오기" 버튼으로
직접 파일을 선택해서 볼 수도 있습니다(이 경우 `data/apartment_data.csv`는 바뀌지 않습니다).

## 색상 / 크기 기준 조정

`index.html` 안의 `LIFE_RANGES`(내구연수 색상 구간)와 `hhToRadius()`(세대수별 원 크기)
함수에서 구간과 색상을 직접 수정할 수 있습니다.

## 보안 참고

`get_latlng.py`는 카카오 REST API 키를 환경변수(`KAKAO_REST_KEY`)로 읽습니다. 코드에
키를 직접 하드코딩해서 git에 커밋하지 마세요.
