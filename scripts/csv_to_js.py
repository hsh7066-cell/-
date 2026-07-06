# -*- coding: utf-8 -*-
"""
data/apartment_data.csv -> data/apartment_data.js 변환

지도 HTML(index.html)은 이 apartment_data.js 파일을 읽어서 지도를 그립니다.
고객 정보(CSV)가 바뀔 때마다 이 스크립트를 다시 실행한 뒤, 브라우저에서
index.html을 새로고침하면 최신 데이터가 반영됩니다.

사용법:
    python scripts/csv_to_js.py
"""
import csv
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_CSV = os.path.join(BASE_DIR, "data", "apartment_data.csv")
OUT_JS = os.path.join(BASE_DIR, "data", "apartment_data.js")


def main():
    with open(IN_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        raw_rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not raw_rows:
        raise SystemExit(f"{IN_CSV} 에 데이터가 없습니다.")

    headers = [h.strip() for h in raw_rows[0]]
    rows = []
    for raw in raw_rows[1:]:
        row = {}
        for i, h in enumerate(headers):
            row[h] = raw[i].strip() if i < len(raw) else ""
        rows.append(row)

    payload = json.dumps(
        {"headers": headers, "rows": rows}, ensure_ascii=False, indent=2
    ).replace("</", "<\\/")

    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("// 이 파일은 scripts/csv_to_js.py 로 자동 생성됩니다. 직접 수정하지 마세요.\n")
        f.write(f"const APT_DATA = {payload};\n")

    print(f"완료: {OUT_JS} ({len(rows)}건)")


if __name__ == "__main__":
    main()
