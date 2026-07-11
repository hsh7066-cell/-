#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app-template.html에 pdf.js / ExcelJS / Tesseract(OCR) 라이브러리를 인라인해서
단일 실행 파일 quote-compare.html을 만든다.

사전 준비:  npm install pdfjs-dist@3.11.174 exceljs@4.4.0 tesseract.js@5.1.1 @tesseract.js-data/kor@1.0.0
사용법:     python3 build.py [node_modules 경로]
"""
import base64
import sys
from pathlib import Path

here = Path(__file__).parent
nm = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "node_modules"

libs = {
    "/*__PDFJS__*/": nm / "pdfjs-dist/legacy/build/pdf.min.js",
    "/*__PDFWORKER__*/": nm / "pdfjs-dist/legacy/build/pdf.worker.min.js",
    "/*__EXCELJS__*/": nm / "exceljs/dist/exceljs.min.js",
    "/*__TESSERACT__*/": nm / "tesseract.js/dist/tesseract.min.js",
    "/*__TESSWORKER__*/": nm / "tesseract.js/dist/worker.min.js",
    "/*__TESSCORESIMD__*/": nm / "tesseract.js-core/tesseract-core-simd-lstm.wasm.js",
    "/*__TESSCORE__*/": nm / "tesseract.js-core/tesseract-core-lstm.wasm.js",
}

html = (here / "app-template.html").read_text(encoding="utf-8")
for marker, path in libs.items():
    code = path.read_text(encoding="utf-8")
    assert "</script" not in code, f"{path} contains </script>"
    assert marker in html, f"marker {marker} missing"
    html = html.replace(marker, code)

for marker, path in {
    "__KORDATA__": nm / "@tesseract.js-data/kor/4.0.0_best_int/kor.traineddata.gz",
    "__ENGDATA__": nm / "@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz",
}.items():
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    assert marker in html
    html = html.replace(marker, data)

out = here.parent / "quote-compare.html"
out.write_text(html, encoding="utf-8")
print(f"생성 완료: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")
