"""밸브 조작요청 엑셀(.xlsx) → valves.csv 변환 스크립트.

사용법 (명령 프롬프트에서 valve_system 폴더로 이동 후):
    pip install openpyxl          (처음 한 번만, 인터넷 필요)
    python import_excel.py "엑셀파일경로.xlsx"

만들어진 valves.csv 는
  - 서버를 처음 실행할 때(밸브가 하나도 없을 때) 자동으로 등록되고,
  - 이후에는 관리자 화면의 [밸브 목록 불러오기]에서 올리면 됩니다.

엑셀 양식(1행 제목) 열 순서:
  S | 발행상태 | 순번(도면번호) | 기기번호(구역) | 기기명(밸브명) | 조작요청 내용 | 요청사항 |
  작업책임자 | 연락처 | 개방일자 | 개방시간 | 투입일자 | 투입시간 | 취소요청사유
"""
import csv
import datetime
import os
import sys

try:
    import openpyxl
except ImportError:
    print("openpyxl 이 필요합니다. 먼저 'pip install openpyxl' 을 실행하세요.")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "valves.csv")
COLUMNS = ["순번", "구역", "밸브명", "도면번호", "요구상태", "요청사항",
           "작업책임자", "연락처", "개방일시", "투입일시"]


def text(v):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def normalize_state(raw, row_no, warnings):
    s = raw.upper().replace(" ", "")
    if s in ("OPEN", "열림", "개방"):
        return "OPEN"
    if s in ("CLOSE", "CLOSED", "닫힘", "폐쇄"):
        return "CLOSE"
    if s.startswith("CLO") or s.startswith("CLS"):  # 'CLOE' 같은 오타
        warnings.append(f"  {row_no}행: '{raw}' → CLOSE 로 고쳐서 등록")
        return "CLOSE"
    if s.startswith("OP"):
        warnings.append(f"  {row_no}행: '{raw}' → OPEN 으로 고쳐서 등록")
        return "OPEN"
    warnings.append(f"  {row_no}행: 요구상태 '{raw}' 를 알 수 없음 → 빈칸으로 등록(관리자 확인 필요)")
    return ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    wb = openpyxl.load_workbook(sys.argv[1], data_only=True)
    ws = wb.worksheets[0]
    rows, warnings = [], []
    for row_no, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        r = list(r) + [None] * 14
        name = text(r[4])
        if not name:
            continue
        rows.append({
            "순번": text(r[0]),
            "구역": text(r[3]),
            "밸브명": name,
            "도면번호": text(r[2]),
            "요구상태": normalize_state(text(r[5]), row_no, warnings),
            "요청사항": "" if text(r[6]) == "-" else text(r[6]).replace("\n", " / "),
            "작업책임자": text(r[7]),
            "연락처": text(r[8]),
            "개방일시": (text(r[9]) + " " + text(r[10])).strip(),
            "투입일시": (text(r[11]) + " " + text(r[12])).strip(),
        })
    # utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않음
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"밸브 {len(rows)}개 → {OUT_CSV}")
    if warnings:
        print("자동 수정/확인 필요 항목:")
        print("\n".join(warnings))


if __name__ == "__main__":
    main()
