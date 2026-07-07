# 산업안전보건관리비 증빙 검증 대시보드

세금계산서와 물품 증빙사진을 Claude API(비전)로 직접 읽어 자동 검증하는 로컬 웹앱입니다.

## 검증 항목과 자동화 범위

| # | 항목 | 자동화 방식 |
|---|------|------|
| 1 | 세금계산서 발급대사 · 승인번호 비교 | 원본/홈택스 발급사실조회 캡처/수정발급 세금계산서를 업로드하면 Claude가 각 문서의 승인번호·금액을 읽어 서로 비교합니다. |
| 2 | 물품·시설 증빙사진 적정성 | Claude 비전이 사진대지 작성기준(현황판 사용, 박스 개봉, 근접촬영 금지 등)에 따라 적합/부적합을 판정합니다. |
| 3 | 비고란 지사명·계약명 표기 | Claude가 비고란 문구를 읽고 지정한 지사명·계약명이 실질적으로 식별 가능한지 판단합니다. |

**주의:** 국세청 홈택스 "제3자 발급사실 조회"는 사업자 인증서 로그인이 필요한 국세청
자체 시스템이라 이 도구가 대신 조회할 수 없습니다. 담당자가 홈택스에서 직접 조회한
화면을 캡처해서 업로드하면, 그 캡처 이미지 속 승인번호를 원본 세금계산서와 문서 대
문서로 비교합니다.

## 실행 방법

```bash
cd tax-invoice-verification
pip install -r requirements.txt

export ANTHROPIC_API_KEY=발급받은_키      # PowerShell: $env:ANTHROPIC_API_KEY="키"
uvicorn server.app:app --reload --port 8000
```

브라우저에서 http://localhost:8000 접속.

## 보안 참고

- `ANTHROPIC_API_KEY`는 환경변수로만 넣고 코드나 git에 절대 하드코딩하지 마세요.
- 업로드된 파일은 디스크에 저장하지 않고 메모리에서 처리 후 Claude API로 전송만
  합니다. 세금계산서에는 사업자등록번호 등 민감정보가 있으므로 사내에서만 접근
  가능한 환경에서 실행하세요.

## 파일 구성

- `server/app.py` — FastAPI 엔드포인트 (`/api/analyze/invoice-set`, `/api/analyze/photo`)
- `server/claude_vision.py` — Claude API 호출 및 이미지/PDF 전처리
- `web/index.html` — 업로드 폼과 결과 대시보드 (바닐라 JS, 별도 빌드 불필요)
