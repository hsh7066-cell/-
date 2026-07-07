"""세금계산서·증빙사진 검증 대시보드 백엔드.

실행:
    export ANTHROPIC_API_KEY=발급받은_키
    cd tax-invoice-verification
    pip install -r requirements.txt
    uvicorn server.app:app --reload --port 8000

그 다음 브라우저에서 http://localhost:8000 접속.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import claude_vision

app = FastAPI(title="산업안전보건관리비 증빙 검증")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def _normalize_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return re.sub(r"[^0-9A-Za-z]", "", value).upper()


async def _read_upload(f: Optional[UploadFile]) -> Optional[tuple[bytes, str]]:
    if f is None:
        return None
    raw = await f.read()
    if not raw:
        return None
    return raw, (f.content_type or "")


@app.post("/api/analyze/invoice-set")
async def analyze_invoice_set(
    expected_branch: str = Form(""),
    expected_contract: str = Form(""),
    original_invoice: Optional[UploadFile] = File(None),
    issuance_check: Optional[UploadFile] = File(None),
    revised_invoice: Optional[UploadFile] = File(None),
):
    original = await _read_upload(original_invoice)
    issuance = await _read_upload(issuance_check)
    revised = await _read_upload(revised_invoice)

    if original is None:
        raise HTTPException(400, "원본 세금계산서 파일이 필요합니다.")

    try:
        fields = {}
        fields["original"] = claude_vision.extract_invoice_fields(*original, label="원본 세금계산서")
        if issuance is not None:
            fields["issuance_check"] = claude_vision.extract_invoice_fields(
                *issuance, label="홈택스 제3자 발급사실 조회 화면"
            )
        if revised is not None:
            fields["revised"] = claude_vision.extract_invoice_fields(*revised, label="수정(재발급) 세금계산서")
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc

    checks = []

    # Check 1a — 원본 vs 홈택스 발급사실 조회 승인번호 일치
    if "issuance_check" in fields:
        a = _normalize_number(fields["original"].get("approval_number"))
        b = _normalize_number(fields["issuance_check"].get("approval_number"))
        match = bool(a) and a == b
        checks.append(
            {
                "id": "issuance-match",
                "title": "원본 세금계산서 ↔ 홈택스 발급사실 조회 승인번호 일치",
                "status": "ok" if match else "fail",
                "detail": (
                    f"원본 승인번호 '{fields['original'].get('approval_number')}' vs "
                    f"조회화면 승인번호 '{fields['issuance_check'].get('approval_number')}' "
                    + ("— 일치, 정상 발급 확인" if match else "— 불일치, 발급사실 확인 필요")
                ),
            }
        )
    else:
        checks.append(
            {
                "id": "issuance-match",
                "title": "원본 세금계산서 ↔ 홈택스 발급사실 조회 승인번호 일치",
                "status": "warn",
                "detail": "홈택스 발급사실 조회 캡처화면이 첨부되지 않아 비교하지 못했습니다.",
            }
        )

    # Check 1b — 원본 vs 수정발급 승인번호 비교
    if "revised" in fields:
        a = _normalize_number(fields["original"].get("approval_number"))
        c = _normalize_number(fields["revised"].get("approval_number"))
        same_number = bool(a) and a == c
        checks.append(
            {
                "id": "revision-compare",
                "title": "원본 ↔ 수정발급 세금계산서 승인번호 비교",
                "status": "fail" if same_number else "ok",
                "detail": (
                    "두 문서의 승인번호가 동일합니다 — 별개의 발급 건이라면 승인번호가 같을 수 없어 이상 소견입니다."
                    if same_number
                    else f"원본 '{fields['original'].get('approval_number')}' / 수정발급 '{fields['revised'].get('approval_number')}' — 서로 다른 승인번호로 정상 재발급된 것으로 보입니다."
                ),
            }
        )
        amt_a = fields["original"].get("total_amount")
        amt_c = fields["revised"].get("total_amount")
        if amt_a is not None and amt_c is not None:
            checks.append(
                {
                    "id": "revision-amount",
                    "title": "원본 ↔ 수정발급 합계금액 비교",
                    "status": "ok" if amt_a == amt_c else "warn",
                    "detail": f"원본 {amt_a:,.0f}원 / 수정발급 {amt_c:,.0f}원"
                    + ("" if amt_a == amt_c else " — 금액이 달라 수정 사유를 확인하세요."),
                }
            )
    else:
        checks.append(
            {
                "id": "revision-compare",
                "title": "원본 ↔ 수정발급 세금계산서 승인번호 비교",
                "status": "warn",
                "detail": "수정(재발급) 세금계산서가 첨부되지 않았습니다 — 원본 단건만 존재하는 것으로 처리합니다.",
            }
        )

    # Check 3 — 비고란 지사명/계약명 표기 (Claude API로 의미 판단)
    remark = fields["original"].get("remark") or ""
    remark_checks = []
    if expected_branch or expected_contract:
        try:
            verdict = claude_vision.judge_remark_compliance(remark, expected_branch, expected_contract)
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

        if expected_branch:
            remark_checks.append(
                {
                    "id": "remark-branch",
                    "title": "비고란 지사명 표기",
                    "status": "ok" if verdict.get("branch_mentioned") else "fail",
                    "detail": f"비고란 '{remark}' — {verdict.get('reasoning', '')}",
                }
            )
        if expected_contract:
            remark_checks.append(
                {
                    "id": "remark-contract",
                    "title": "비고란 계약명 표기",
                    "status": "ok" if verdict.get("contract_mentioned") else "fail",
                    "detail": f"비고란 '{remark}' — {verdict.get('reasoning', '')}",
                }
            )
    else:
        remark_checks.append(
            {
                "id": "remark-branch",
                "title": "비고란 지사명·계약명 표기",
                "status": "warn",
                "detail": f"비교할 지사명/계약명을 입력하지 않았습니다. 비고란 원문: '{remark}'",
            }
        )

    all_checks = checks + remark_checks
    overall = "fail" if any(c["status"] == "fail" for c in all_checks) else (
        "warn" if any(c["status"] == "warn" for c in all_checks) else "ok"
    )

    return JSONResponse({"fields": fields, "checks": all_checks, "overall": overall})


@app.post("/api/analyze/photo")
async def analyze_photo(
    item_label: str = Form(""),
    photo: UploadFile = File(...),
):
    raw = await photo.read()
    if not raw:
        raise HTTPException(400, "사진 파일이 비어 있습니다.")
    try:
        result = claude_vision.judge_photo(raw, photo.content_type or "", item_label)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return JSONResponse(result)
