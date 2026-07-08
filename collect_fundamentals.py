# -*- coding: utf-8 -*-
"""
주간 퀀트 대시보드 — 재무데이터 수집기 (분기 1회 실행)
DART 오픈API로 자본총계를 수집해 fundamentals.json 생성
→ collect_data.py가 이를 읽어 PBR = 시가총액 / 자본총계 계산에 사용

사용법:
    pip install requests
    python collect_fundamentals.py

실행 주기: 분기 1회 (사업/분기보고서 공시 후 — 대략 4월·5월·8월·11월 중순)

주의:
- DART 개인키는 일 20,000건 한도. 이 스크립트는 종목당 1~2건 호출로 여유 충분.
- ★ API 키는 config.json(gitignore 처리됨) 또는 환경변수로 관리 — 저장소에 올라가지 않음
"""
import io
import json
import time
import zipfile
import datetime as dt
import xml.etree.ElementTree as ET

import requests

# ──────────────────────────────────────────────
# API 키는 config.json 또는 환경변수에서 로드 (저장소에 키를 넣지 않기 위함)
import os
def _load_config():
    try:
        with open("config.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
_cfg = _load_config()
DART_API_KEY = os.getenv("DART_API_KEY") or _cfg.get("dart_api_key", "")
if not DART_API_KEY:
    raise SystemExit("DART 키 없음: config.json에 dart_api_key를 넣거나 환경변수 DART_API_KEY를 설정하세요. (config.example.json 참고)")
TICKERS_FILE = "market_data.json"   # collect_data.py 산출물에서 종목 목록을 읽음
OUT = "fundamentals.json"
SLEEP = 0.25
# ──────────────────────────────────────────────

BASE = "https://opendart.fss.or.kr/api"


def get_corp_code_map():
    """전체 상장사 고유번호 zip 다운로드 → {종목코드: corp_code}"""
    print("[1/3] DART 고유번호 매핑 다운로드…")
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=30)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read("CORPCODE.xml"))
    m = {}
    for e in root.iter("list"):
        stock_code = (e.findtext("stock_code") or "").strip()
        if stock_code:
            m[stock_code] = e.findtext("corp_code").strip()
    print(f"      상장사 {len(m)}개 매핑 완료")
    return m


def latest_report_params():
    """가장 최근에 확정됐을 정기보고서 (연도, 보고서코드) 후보 목록.
    11011=사업, 11014=3분기, 11012=반기, 11013=1분기"""
    now = dt.date.today()
    y, m = now.year, now.month
    cands = []
    if m >= 11:   cands = [(y, "11014"), (y, "11012"), (y, "11013"), (y - 1, "11011")]
    elif m >= 8:  cands = [(y, "11012"), (y, "11013"), (y - 1, "11011")]
    elif m >= 5:  cands = [(y, "11013"), (y - 1, "11011")]
    else:         cands = [(y - 1, "11011"), (y - 1, "11014")]
    return cands


def get_equity(corp_code, cands):
    """단일회사 주요계정에서 자본총계(지배기업 소유주지분 우선) 추출. 억→원 단위 그대로."""
    for year, rpt in cands:
        try:
            r = requests.get(f"{BASE}/fnlttSinglAcnt.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": rpt}, timeout=20)
            j = r.json()
            if j.get("status") != "000":
                continue
            rows = j.get("list", [])
            # 연결(CFS) 우선, 없으면 개별(OFS)
            for fs in ("CFS", "OFS"):
                for row in rows:
                    if row.get("fs_div") == fs and row.get("account_nm") == "자본총계":
                        amt = row.get("thstrm_amount", "").replace(",", "")
                        if amt and amt not in ("-",):
                            return int(amt), f"{year}/{rpt}/{fs}"
        except Exception:
            continue
    return None, None


def main():
    corp_map = get_corp_code_map()

    # 종목 목록: market_data.json이 있으면 그걸 사용, 없으면 안내
    try:
        with open(TICKERS_FILE, encoding="utf-8") as f:
            md = json.load(f)
        tickers = [(s["code"], s["name"]) for s in md["stocks"]]
        print(f"[2/3] {TICKERS_FILE}에서 종목 {len(tickers)}개 로드")
    except FileNotFoundError:
        print(f"[2/3] {TICKERS_FILE} 없음 → collect_data.py를 먼저 실행하세요.")
        return

    cands = latest_report_params()
    print(f"      조회 대상 보고서 후보: {cands}")

    out = {}
    for k, (code, name) in enumerate(tickers, 1):
        cc = corp_map.get(code)
        if not cc:
            print(f"      [{k}/{len(tickers)}] {code} {name}: corp_code 없음 → 건너뜀")
            continue
        eq, src = get_equity(cc, cands)
        if eq:
            out[code] = {"name": name, "equity": eq, "report": src}
            print(f"      [{k}/{len(tickers)}] {code} {name}: 자본총계 {eq/1e12:.2f}조 ({src})")
        else:
            print(f"      [{k}/{len(tickers)}] {code} {name}: 자본총계 조회 실패")
        time.sleep(SLEEP)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated": dt.datetime.now().isoformat(timespec="minutes"),
                   "data": out}, f, ensure_ascii=False, indent=1)
    print(f"[3/3] 완료 → {OUT} ({len(out)}개 종목)")


if __name__ == "__main__":
    main()
