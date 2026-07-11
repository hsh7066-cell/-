#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
견적서 PDF -> 비교 엑셀 생성기

사용법:
    # PDF 1개 (페이지별로 견적1, 견적2, ...)
    python3 quote_compare.py 견적서.pdf -o 견적비교.xlsx

    # PDF 여러 개 (파일별로 견적1, 견적2, ...)
    python3 quote_compare.py 업체A.pdf 업체B.pdf -o 견적비교.xlsx

    # 샘플 데이터로 형식만 확인
    python3 quote_compare.py --demo -o 견적비교_샘플.xlsx

출력:
    Sheet1(견적내용): 견적1, 견적2 품목표를 나란히 배치
    Sheet2(비교):     품명별 금액 비교 + MIN(최저가) 수식
"""
import argparse
import difflib
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 견적서 표에서 인식할 헤더 키워드
NAME_KEYS = ["품명", "품목", "제품명", "상품명", "내역", "공사명", "항목"]
SPEC_KEYS = ["규격", "사양", "스펙", "모델"]
QTY_KEYS = ["수량", "물량"]
UNIT_KEYS = ["단가"]
AMOUNT_KEYS = ["금액", "공급가액", "합계금액", "공급가"]
SKIP_ROW_KEYS = ["합계", "소계", "총계", "부가세", "총액", "이하여백", "TOTAL"]


def parse_number(text):
    """'1,234,500원' 같은 문자열에서 숫자를 추출한다."""
    if text is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(text))
    if s in ("", "-", "."):
        return None
    try:
        v = float(s)
        return int(v) if v == int(v) else v
    except ValueError:
        return None


def find_col(header, keys):
    for i, cell in enumerate(header):
        cell = (cell or "").replace(" ", "")
        for k in keys:
            if k in cell:
                return i
    return None


def extract_items_from_table(table):
    """pdfplumber 표 하나에서 [{품명, 규격, 수량, 단가, 금액}] 목록을 뽑는다."""
    if not table or len(table) < 2:
        return []
    header = [(c or "").strip() for c in table[0]]
    ci_name = find_col(header, NAME_KEYS)
    ci_amount = find_col(header, AMOUNT_KEYS)
    if ci_name is None or ci_amount is None:
        return []
    ci_spec = find_col(header, SPEC_KEYS)
    ci_qty = find_col(header, QTY_KEYS)
    ci_unit = find_col(header, UNIT_KEYS)

    items = []
    for row in table[1:]:
        row = [(c or "").strip() for c in row]
        name = row[ci_name] if ci_name < len(row) else ""
        if not name:
            continue
        if any(k in name.replace(" ", "") for k in SKIP_ROW_KEYS):
            continue
        amount = parse_number(row[ci_amount]) if ci_amount < len(row) else None
        items.append({
            "품명": name,
            "규격": row[ci_spec] if ci_spec is not None and ci_spec < len(row) else "",
            "수량": parse_number(row[ci_qty]) if ci_qty is not None and ci_qty < len(row) else None,
            "단가": parse_number(row[ci_unit]) if ci_unit is not None and ci_unit < len(row) else None,
            "금액": amount,
        })
    return items


def extract_quotes_from_pdfs(pdf_paths):
    """PDF들에서 견적 목록을 뽑는다. PDF 1개면 페이지별, 여러 개면 파일별 견적."""
    import pdfplumber

    quotes = []  # [(견적이름, items)]
    single = len(pdf_paths) == 1
    for path in pdf_paths:
        with pdfplumber.open(path) as pdf:
            for pageno, page in enumerate(pdf.pages, start=1):
                items = []
                for table in page.extract_tables():
                    items.extend(extract_items_from_table(table))
                if not items:
                    continue
                if single:
                    label = f"견적{len(quotes) + 1} (Page{pageno})"
                else:
                    stem = re.sub(r"\.pdf$", "", path.split("/")[-1], flags=re.I)
                    label = f"견적{len(quotes) + 1} ({stem})"
                quotes.append((label, items))
    return quotes


def demo_quotes():
    q1 = [
        {"품명": "LED 조명 50W", "규격": "매입형", "수량": 20, "단가": 35000, "금액": 700000},
        {"품명": "전선 HIV 2.5sq", "규격": "300m", "수량": 3, "단가": 45000, "금액": 135000},
        {"품명": "분전반 교체", "규격": "20회로", "수량": 1, "단가": 850000, "금액": 850000},
        {"품명": "콘센트 매입형", "규격": "2구", "수량": 15, "단가": 8000, "금액": 120000},
    ]
    q2 = [
        {"품명": "LED조명 50W", "규격": "매입형", "수량": 20, "단가": 32000, "금액": 640000},
        {"품명": "전선 HIV 2.5SQ", "규격": "300m", "수량": 3, "단가": 48000, "금액": 144000},
        {"품명": "분전반교체", "규격": "20회로", "수량": 1, "단가": 900000, "금액": 900000},
        {"품명": "스위치 교체", "규격": "3로", "수량": 5, "단가": 12000, "금액": 60000},
    ]
    return [("견적1 (Page1)", q1), ("견적2 (Page2)", q2)]


def norm_name(name):
    return re.sub(r"[\s\-_/()]+", "", name).lower()


def match_items(quotes, threshold=0.75):
    """여러 견적의 품명을 비슷한 것끼리 한 행으로 묶는다.

    반환: [(대표품명, {견적index: item})]
    """
    rows = []  # (대표품명, 정규화명, {qi: item})
    for qi, (_, items) in enumerate(quotes):
        for item in items:
            key = norm_name(item["품명"])
            best, best_ratio = None, 0.0
            for row in rows:
                if qi in row[2]:  # 같은 견적의 품목끼리는 안 묶음
                    continue
                ratio = difflib.SequenceMatcher(None, key, row[1]).ratio()
                if ratio > best_ratio:
                    best, best_ratio = row, ratio
            if best is not None and best_ratio >= threshold:
                best[2][qi] = item
            else:
                rows.append((item["품명"], key, {qi: item}))
    return [(r[0], r[2]) for r in rows]


# ---------- 엑셀 스타일 ----------
THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
TITLE_FILL = PatternFill("solid", fgColor="4472C4")
MIN_FILL = PatternFill("solid", fgColor="C6EFCE")
NUM_FMT = "#,##0"


def style_cell(cell, bold=False, fill=None, center=False, numfmt=None):
    cell.border = BORDER
    if bold:
        cell.font = Font(bold=True, color="FFFFFF" if fill is TITLE_FILL else "000000")
    if fill is not None:
        cell.fill = fill
    if center:
        cell.alignment = Alignment(horizontal="center", vertical="center")
    if numfmt:
        cell.number_format = numfmt


def write_sheet1(ws, quotes):
    """견적별 품목표를 옆으로 나란히 배치."""
    cols = ["품명", "규격", "수량", "단가", "금액"]
    block_w = len(cols)
    for qi, (label, items) in enumerate(quotes):
        c0 = 1 + qi * (block_w + 1)  # 블록 사이 1열 간격
        # 견적 제목
        ws.merge_cells(start_row=1, start_column=c0, end_row=1, end_column=c0 + block_w - 1)
        tcell = ws.cell(row=1, column=c0, value=label)
        style_cell(tcell, bold=True, fill=TITLE_FILL, center=True)
        for c in range(c0, c0 + block_w):
            ws.cell(row=1, column=c).border = BORDER
            ws.cell(row=1, column=c).fill = TITLE_FILL
        # 헤더
        for j, h in enumerate(cols):
            cell = ws.cell(row=2, column=c0 + j, value=h)
            style_cell(cell, bold=True, fill=HEADER_FILL, center=True)
        # 데이터
        for i, item in enumerate(items):
            r = 3 + i
            for j, h in enumerate(cols):
                v = item.get(h)
                cell = ws.cell(row=r, column=c0 + j, value=v)
                style_cell(cell, numfmt=NUM_FMT if h in ("수량", "단가", "금액") else None)
        # 합계
        r = 3 + len(items)
        cell = ws.cell(row=r, column=c0, value="합계")
        style_cell(cell, bold=True, fill=HEADER_FILL, center=True)
        for j in range(1, block_w - 1):
            style_cell(ws.cell(row=r, column=c0 + j), fill=HEADER_FILL)
        amt_col = get_column_letter(c0 + block_w - 1)
        cell = ws.cell(row=r, column=c0 + block_w - 1,
                       value=f"=SUM({amt_col}3:{amt_col}{r - 1})")
        style_cell(cell, bold=True, fill=HEADER_FILL, numfmt=NUM_FMT)
        # 열 너비
        widths = [22, 12, 7, 11, 13]
        for j, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(c0 + j)].width = w
        ws.column_dimensions[get_column_letter(c0 + block_w)].width = 2


def write_sheet2(ws, quotes, matched):
    """품명별 금액 비교 + MIN 수식."""
    n = len(quotes)
    headers = ["품명"] + [label for label, _ in quotes] + ["비교 MIN(최저가)", "최저 견적"]
    for j, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=j, value=h)
        style_cell(cell, bold=True, fill=HEADER_FILL, center=True)

    for i, (name, by_quote) in enumerate(matched):
        r = 2 + i
        style_cell(ws.cell(row=r, column=1, value=name))
        for qi in range(n):
            item = by_quote.get(qi)
            cell = ws.cell(row=r, column=2 + qi, value=item["금액"] if item else None)
            style_cell(cell, numfmt=NUM_FMT)
        first = get_column_letter(2)
        last = get_column_letter(1 + n)
        min_cell = ws.cell(row=r, column=2 + n, value=f"=MIN({first}{r}:{last}{r})")
        style_cell(min_cell, bold=True, fill=MIN_FILL, numfmt=NUM_FMT)
        # 최저가 견적 번호 표시: =MATCH(MIN셀, 범위, 0)
        min_col = get_column_letter(2 + n)
        vendor = ws.cell(
            row=r, column=3 + n,
            value=f'=IF(COUNT({first}{r}:{last}{r})=0,"","견적"&MATCH({min_col}{r},{first}{r}:{last}{r},0))',
        )
        style_cell(vendor, center=True)

    # 합계 행
    r = 2 + len(matched)
    cell = ws.cell(row=r, column=1, value="합계")
    style_cell(cell, bold=True, fill=HEADER_FILL, center=True)
    for j in range(2, 3 + n):
        col = get_column_letter(j)
        cell = ws.cell(row=r, column=j, value=f"=SUM({col}2:{col}{r - 1})")
        style_cell(cell, bold=True, fill=HEADER_FILL, numfmt=NUM_FMT)
    style_cell(ws.cell(row=r, column=3 + n), fill=HEADER_FILL)

    ws.column_dimensions["A"].width = 24
    for j in range(2, 3 + n):
        ws.column_dimensions[get_column_letter(j)].width = 15
    ws.column_dimensions[get_column_letter(3 + n)].width = 11
    ws.freeze_panes = "B2"


def build_workbook(quotes, out_path, threshold=0.75):
    matched = match_items(quotes, threshold)
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "견적내용"
    write_sheet1(ws1, quotes)
    ws2 = wb.create_sheet("비교")
    write_sheet2(ws2, quotes, matched)
    wb.save(out_path)


def main():
    ap = argparse.ArgumentParser(description="견적서 PDF -> 비교 엑셀 생성")
    ap.add_argument("pdfs", nargs="*", help="견적서 PDF 파일 (1개면 페이지별, 여러 개면 파일별 견적)")
    ap.add_argument("-o", "--output", default="견적비교.xlsx", help="출력 엑셀 파일명")
    ap.add_argument("--demo", action="store_true", help="샘플 데이터로 형식 확인")
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="품명 유사도 매칭 기준 (0~1, 기본 0.75)")
    args = ap.parse_args()

    if args.demo:
        quotes = demo_quotes()
    elif args.pdfs:
        quotes = extract_quotes_from_pdfs(args.pdfs)
        if not quotes:
            sys.exit("PDF에서 견적 표를 찾지 못했습니다. 표 형식(품명/금액 헤더)이 있는지 확인하세요.")
    else:
        ap.print_help()
        sys.exit(1)

    build_workbook(quotes, args.output, args.threshold)
    print(f"저장 완료: {args.output}")
    for label, items in quotes:
        print(f"  - {label}: 품목 {len(items)}개")


if __name__ == "__main__":
    main()
