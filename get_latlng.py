# -*- coding: utf-8 -*-
"""
엑셀(주소 열 포함) -> 카카오 지오코딩 -> 위도/경도가 포함된 CSV 생성

사용법:
    1) 카카오 REST API 키를 환경변수로 지정
         Windows(cmd):  set KAKAO_REST_KEY=발급받은키
         Windows(PowerShell): $env:KAKAO_REST_KEY="발급받은키"
         macOS/Linux:   export KAKAO_REST_KEY=발급받은키
    2) IN_XLSX 경로를 본인 엑셀 파일 위치로 수정
    3) python get_latlng.py 실행
"""
import os
import time
import pandas as pd
import requests

KAKAO_REST_KEY = os.environ.get("KAKAO_REST_KEY", "")

# 입력 파일(엑셀), 출력 파일(CSV) - 본인 환경에 맞게 수정하세요
IN_XLSX = "apart_example.xlsx"
OUT_CSV = "data/apartment_data.csv"


def geocode_kakao(addr: str):
    """주소 -> (위도, 경도) 변환"""
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
        params = {"query": addr}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        docs = data.get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])  # y=위도, x=경도
    except Exception as e:
        print(f"[오류] {addr} -> {e}")
    return None, None


def main():
    if not KAKAO_REST_KEY:
        raise SystemExit(
            "KAKAO_REST_KEY 환경변수가 설정되지 않았습니다. "
            "카카오 개발자 사이트에서 발급받은 REST API 키를 환경변수로 지정한 뒤 다시 실행하세요."
        )

    df = pd.read_excel(IN_XLSX)

    if "주소" not in df.columns:
        raise KeyError("엑셀에 '주소' 열이 없습니다. 열 이름을 확인하세요.")

    lats, lngs = [], []
    for addr in df["주소"].fillna(""):
        lat, lng = geocode_kakao(addr)
        lats.append(lat)
        lngs.append(lng)
        print(addr, "->", lat, lng)
        time.sleep(0.2)  # 요청 제한 고려 (초당 5회 이하)

    df["위도"] = lats
    df["경도"] = lngs

    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print("완료:", OUT_CSV)


if __name__ == "__main__":
    main()
