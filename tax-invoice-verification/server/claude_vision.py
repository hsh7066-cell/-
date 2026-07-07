"""Claude API(비전)를 이용해 세금계산서/증빙사진을 읽고 판정하는 헬퍼 모듈.

이 파일이 다루지 않는 것: 국세청 홈택스 실시간 발급사실 조회(제3자 발급사실 조회)는
사업자 인증서 로그인이 필요한 국세청 자체 시스템이라 외부에서 API로 대신 조회할 수
없다. 대신 사용자가 홈택스에서 직접 조회한 화면을 캡처해 업로드하면, 그 캡처 이미지에
적힌 승인번호를 세금계산서 승인번호와 문서 대 문서로 비교한다.
"""
from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from typing import Any

import anthropic
import fitz  # PyMuPDF
from PIL import Image

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@dataclass
class PreparedImage:
    media_type: str
    b64: str


def prepare_image(raw_bytes: bytes, content_type: str) -> PreparedImage:
    """업로드된 파일(이미지 또는 PDF)을 Claude에 보낼 수 있는 base64 이미지로 변환.

    PDF는 1페이지만 렌더링한다 — 증빙사진/세금계산서는 통상 1장짜리 문서이므로.
    """
    content_type = (content_type or "").lower()

    if content_type == "application/pdf" or raw_bytes[:4] == b"%PDF":
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        png_bytes = pix.tobytes("png")
        return PreparedImage("image/png", base64.b64encode(png_bytes).decode())

    if content_type in _SUPPORTED_IMAGE_TYPES:
        return PreparedImage(content_type, base64.b64encode(raw_bytes).decode())

    # 지원하지 않는 이미지 포맷(예: HEIC, BMP)은 PNG로 다시 인코딩
    im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return PreparedImage("image/png", base64.b64encode(buf.getvalue()).decode())


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "터미널에서 export ANTHROPIC_API_KEY=발급받은_키 를 실행한 뒤 서버를 다시 시작하세요."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_tool(
    images: list[PreparedImage],
    tool_name: str,
    tool_schema: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for img in images:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type, "data": img.b64},
            }
        )
    content.append({"type": "text", "text": user_prompt})

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=1500,
        system=system_prompt,
        tools=[{"name": tool_name, "description": tool_schema.get("description", ""), "input_schema": tool_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": content}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input

    raise RuntimeError("Claude 응답에서 판정 결과(tool_use)를 찾지 못했습니다.")


# ---------------------------------------------------------------------------
# Check 1 & 3 — 세금계산서 필드 추출 (승인번호/금액/비고 등)
# ---------------------------------------------------------------------------

_INVOICE_TOOL_SCHEMA = {
    "description": "이미지에 담긴 세금계산서 또는 홈택스 발급사실 조회 화면에서 핵심 필드를 추출한다.",
    "type": "object",
    "properties": {
        "document_kind": {
            "type": "string",
            "description": "문서 종류 추정",
            "enum": ["세금계산서", "홈택스_발급사실조회화면", "기타"],
        },
        "approval_number": {"type": ["string", "null"], "description": "승인번호 (하이픈 포함 원문 그대로)"},
        "issue_date": {"type": ["string", "null"], "description": "작성일자 또는 발급일자 (YYYY-MM-DD)"},
        "supply_amount": {"type": ["number", "null"], "description": "공급가액"},
        "tax_amount": {"type": ["number", "null"], "description": "세액"},
        "total_amount": {"type": ["number", "null"], "description": "합계금액"},
        "supplier_name": {"type": ["string", "null"], "description": "공급자 상호"},
        "buyer_name": {"type": ["string", "null"], "description": "공급받는자 상호"},
        "remark": {"type": ["string", "null"], "description": "비고란에 적힌 원문 전체"},
        "modification_reason": {"type": ["string", "null"], "description": "수정사유란 내용(없으면 null)"},
        "is_issued": {
            "type": ["boolean", "null"],
            "description": "발급사실조회 화면인 경우, 정상 발급된 것으로 표시되는지 여부",
        },
        "notes": {"type": "string", "description": "판독이 애매하거나 읽기 어려운 부분에 대한 메모"},
    },
    "required": ["document_kind", "approval_number", "notes"],
}

_INVOICE_SYSTEM_PROMPT = (
    "당신은 공공기관의 산업안전보건관리비 실적정산 증빙을 검토하는 회계감사 보조원입니다. "
    "제공된 이미지는 전자세금계산서 사본이거나 국세청 홈택스 '제3자 발급사실 조회' 결과 화면입니다. "
    "이미지에 실제로 보이는 내용만 정확히 읽어 추출하고, 보이지 않는 값은 null로 남기세요. "
    "추측하거나 임의로 채우지 마세요."
)


def extract_invoice_fields(raw_bytes: bytes, content_type: str, label: str) -> dict[str, Any]:
    img = prepare_image(raw_bytes, content_type)
    user_prompt = (
        f"첨부한 이미지는 '{label}' 문서입니다. submit 도구에 정의된 필드를 이미지에서 그대로 읽어 채워주세요."
    )
    return _call_tool([img], "submit_invoice_fields", _INVOICE_TOOL_SCHEMA, _INVOICE_SYSTEM_PROMPT, user_prompt)


# ---------------------------------------------------------------------------
# Check 2 — 물품/시설 증빙사진 적정성 판정
# ---------------------------------------------------------------------------

_PHOTO_TOOL_SCHEMA = {
    "description": "산업안전보건관리비 증빙사진 1장을 사진대지 작성기준에 따라 판정한다.",
    "type": "object",
    "properties": {
        "item_guess": {"type": "string", "description": "사진 속 품목/시설물이 무엇으로 보이는지"},
        "status_board_present": {
            "type": "boolean",
            "description": "촬영일자·수량(또는 시공일자·구간)을 명기한 현황판이 사진 안에 보이는지",
        },
        "quantity_countable": {
            "type": "boolean",
            "description": "현황판 없이도 사진만으로 정확한 수량 파악이 가능한지",
        },
        "box_opened_if_boxed": {
            "type": ["boolean", "null"],
            "description": "박스포장 품목인 경우 개봉 후 내용물 확인이 가능한지 (박스포장 품목이 아니면 null)",
        },
        "close_up_violation": {
            "type": "boolean",
            "description": "적용 품목 전체가 한 프레임에 나타나지 않을 정도의 근접촬영인지",
        },
        "usage_purpose_clear": {
            "type": "boolean",
            "description": "사용목적(용도)을 사진만으로 분간할 수 있는지",
        },
        "verdict": {"type": "string", "enum": ["적합", "부적합"]},
        "violation_reasons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "부적합 사유 목록(적합이면 빈 배열)",
        },
        "notes": {"type": "string", "description": "판정에 참고한 그 밖의 관찰 내용"},
    },
    "required": ["item_guess", "status_board_present", "verdict", "violation_reasons", "notes"],
}

_PHOTO_SYSTEM_PROMPT = (
    "당신은 공공기관의 산업안전보건관리비 실적정산 증빙사진을 검토하는 안전관리 감사 보조원입니다. "
    "다음 '산업안전보건관리비 사진대지 작성방법' 기준으로만 판정하세요:\n"
    "1) 품목별 촬영시 현황판으로 촬영일자 및 수량을 명기해야 한다(현황판 없이 찍힌 사진은 부적합).\n"
    "2) 박스포장 품목은 개봉 후 내용물 확인이 가능하도록 촬영해야 한다.\n"
    "3) 적용품목이 한 장의 사진에 다 나타나야 한다(너무 근접 촬영하여 일부만 보이면 부적합).\n"
    "4) 시설물 사진은 사용목적에 맞게, 용도를 분간할 수 있도록 촬영해야 한다.\n"
    "실제 사진에서 관찰되는 사실만 근거로 판정하고, 확인할 수 없는 항목은 사실대로 서술하세요."
)


def judge_photo(raw_bytes: bytes, content_type: str, item_label: str = "") -> dict[str, Any]:
    img = prepare_image(raw_bytes, content_type)
    hint = f" (제출 시 기재된 품목명: {item_label})" if item_label else ""
    user_prompt = f"이 증빙사진을 기준에 따라 판정해 submit 도구로 결과를 제출하세요{hint}."
    return _call_tool([img], "submit_photo_judgement", _PHOTO_TOOL_SCHEMA, _PHOTO_SYSTEM_PROMPT, user_prompt)


# ---------------------------------------------------------------------------
# Check 3 — 비고란 지사명·계약명 표기 판정 (단순 문자열 일치가 아니라 의미 판단)
# ---------------------------------------------------------------------------

_REMARK_TOOL_SCHEMA = {
    "description": "세금계산서 비고란 문구에 지사명과 계약명이 실질적으로 식별 가능하게 적혀 있는지 판정한다.",
    "type": "object",
    "properties": {
        "branch_mentioned": {
            "type": "boolean",
            "description": "비고란만 보고도 어느 지사 건인지 식별 가능한지. 상위기관명만 있고 지사명이 없으면 false.",
        },
        "contract_mentioned": {
            "type": "boolean",
            "description": "비고란만 보고도 어떤 계약/공사 건인지 식별 가능한지.",
        },
        "reasoning": {"type": "string", "description": "판정 근거를 한두 문장으로"},
    },
    "required": ["branch_mentioned", "contract_mentioned", "reasoning"],
}

_REMARK_SYSTEM_PROMPT = (
    "당신은 공공기관 감사 보조원입니다. 감사 재발방지대책에 따라 '전자세금계산서 발행시 비고란에 지사명, "
    "계약명 표기 여부'를 확인해야 합니다. 단순 문자열 일치가 아니라, 실무자가 비고란 문구만 보고 어느 지사의 "
    "어떤 계약(공사/용역) 건인지 실제로 식별할 수 있는지를 기준으로 엄격하게 판단하세요. 상위기관명(예: "
    "한국지역난방공사)만 적혀 있고 구체적 지사명이 없으면 지사명은 미표기로 판단합니다."
)


def judge_remark_compliance(remark: str, expected_branch: str, expected_contract: str) -> dict[str, Any]:
    user_prompt = (
        f"비고란 원문: '{remark or '(비고란 공란)'}'\n"
        f"기대하는 지사명: '{expected_branch or '(미입력)'}'\n"
        f"기대하는 계약명: '{expected_contract or '(미입력)'}'\n"
        "submit 도구로 판정 결과를 제출하세요."
    )
    return _call_tool([], "submit_remark_judgement", _REMARK_TOOL_SCHEMA, _REMARK_SYSTEM_PROMPT, user_prompt)
