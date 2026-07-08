# -*- coding: utf-8 -*-
"""
주간 퀀트 대시보드 — 데이터 수집기 (2단계)
pykrx로 코스피200 시세·PBR·지수를 수집해 market_data.json 생성

사용법:
    pip install pykrx

    ★ 최신 pykrx는 KRX 정보데이터시스템 무료 회원 로그인이 필요합니다.
      1) data.krx.co.kr 에서 무료 회원가입
      2) 환경변수 설정 후 실행:
         Windows(PowerShell):  $env:KRX_ID="아이디"; $env:KRX_PW="비밀번호"; python collect_data.py
         Mac/Linux:            KRX_ID="아이디" KRX_PW="비밀번호" python collect_data.py

    python collect_data.py
    → 같은 폴더에 market_data.json 생성
    → python -m http.server 8000 실행 후 브라우저에서
      http://localhost:8000/quant-dashboard-v2.html 접속

주의:
- KRX는 T+2 데이터 제공. 주 1회(예: 토요일 오전) 실행 권장.
- 전 종목 수집에 5~15분 소요 (KRX 서버 부하 방지를 위해 호출 간 지연 포함)
- ECOS 키 발급 전까지 기준금리는 아래 BASE_RATE_MANUAL 값을 사용.
  한국은행 홈페이지에서 확인 후 변경할 것.
"""
import json
import time
import datetime as dt

from pykrx import stock

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
import os as _os
try:
    with open("config.json", encoding="utf-8") as _f:
        _cfg = json.load(_f)
except FileNotFoundError:
    _cfg = {}
BASE_RATE_MANUAL = float(_cfg.get("base_rate_manual", 2.50))  # ECOS 연동 전 수동 기준금리
ECOS_API_KEY = _os.getenv("ECOS_API_KEY") or _cfg.get("ecos_api_key", "")  # 발급 후 config.json에 입력

DART_API_KEY = _os.getenv("DART_API_KEY") or _cfg.get("dart_api_key", "")  # config.json 또는 환경변수에서 로드 (저장소에 키를 넣지 않기 위함)
USE_DART_PBR = True        # True: DART 자본총계로 PBR 직접 계산 / False: pykrx PBR 사용

LOOKBACK_DAYS = 780        # 약 3년 (백테스트 2년 + 200일선 워밍업)
UNIVERSE_INDEX = "1028"    # 코스피200
TOP_BY_MCAP = 50           # 프로토타입: 시총 상위 50종목만 (전체 200개는 시간 오래 걸림)
SLEEP = 0.4                # KRX 서버 예의상 호출 간격(초)
OUT = "market_data.json"

# ──────────────────────────────────────────────
# 날짜 준비
# ──────────────────────────────────────────────
today = dt.date.today()
end = today.strftime("%Y%m%d")
start = (today - dt.timedelta(days=int(LOOKBACK_DAYS * 1.5))).strftime("%Y%m%d")
print(f"[1/5] 수집 기간: {start} ~ {end}")

# ──────────────────────────────────────────────
# 유니버스: 코스피200 구성종목 → 시총 상위 N
# ──────────────────────────────────────────────
tickers = stock.get_index_portfolio_deposit_file(UNIVERSE_INDEX)
print(f"[2/5] 코스피200 구성종목 {len(tickers)}개 확인")

cap_date = stock.get_nearest_business_day_in_a_week(end)
cap = stock.get_market_cap_by_ticker(cap_date)
cap = cap.loc[[t for t in tickers if t in cap.index]]
tickers = cap.sort_values("시가총액", ascending=False).head(TOP_BY_MCAP).index.tolist()
print(f"      시총 상위 {len(tickers)}개로 축소")

# DART 자본총계 (collect_fundamentals.py 산출물, 있으면 PBR 보조 계산에 사용)
try:
    with open("fundamentals.json", encoding="utf-8") as _f:
        dart_equity = json.load(_f)["data"]
    print(f"      DART 재무데이터 {len(dart_equity)}종목 로드")
except FileNotFoundError:
    dart_equity = {}

# PBR (기준일 스냅샷 — 분기 갱신이면 충분)
fund = stock.get_market_fundamental_by_ticker(cap_date)

# ──────────────────────────────────────────────
# 종목별 시세 수집
# ──────────────────────────────────────────────
stocks, ref_dates = [], None
for k, t in enumerate(tickers, 1):
    try:
        df = stock.get_market_ohlcv_by_date(start, end, t)
        if len(df) < 300:
            print(f"      [{k}/{len(tickers)}] {t} 데이터 부족({len(df)}일) → 제외")
            continue
        df = df.tail(LOOKBACK_DAYS)
        if ref_dates is None:
            ref_dates = [d.strftime("%Y-%m-%d") for d in df.index]
        pbr = float(fund.loc[t, "PBR"]) if t in fund.index else 0.0
        if pbr <= 0 and t in dart_equity:          # pykrx PBR 없으면 DART로 계산
            eq = dart_equity[t]["equity"]
            mcap = float(cap.loc[t, "시가총액"]) if t in cap.index else 0
            if eq > 0 and mcap > 0:
                pbr = mcap / eq
        stocks.append({
            "code": t,
            "name": stock.get_market_ticker_name(t),
            "pbr": round(pbr, 2) if pbr > 0 else None,
            "prices": [float(p) for p in df["종가"]],
        })
        print(f"      [{k}/{len(tickers)}] {t} {stocks[-1]['name']} ✓ ({len(df)}일)")
    except Exception as e:
        print(f"      [{k}/{len(tickers)}] {t} 실패: {e}")
    time.sleep(SLEEP)
print(f"[3/5] 종목 수집 완료: {len(stocks)}개")

# ──────────────────────────────────────────────
# 코스피200 지수 (국면 판정 + 벤치마크)
# ──────────────────────────────────────────────
idx = stock.get_index_ohlcv_by_date(start, end, UNIVERSE_INDEX).tail(LOOKBACK_DAYS)
index_series = [float(v) for v in idx["종가"]]
print(f"[4/5] 지수 수집 완료: {len(index_series)}일")

# ──────────────────────────────────────────────
# 기준금리: ECOS 키 있으면 자동, 없으면 수동값
# ──────────────────────────────────────────────
rate_history = None
if ECOS_API_KEY:
    try:
        import urllib.request
        s = (today - dt.timedelta(days=1200)).strftime("%Y%m")
        e = today.strftime("%Y%m")
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}"
               f"/json/kr/1/200/722Y001/M/{s}/{e}/0101000")
        with urllib.request.urlopen(url, timeout=20) as r:
            rows = json.load(r)["StatisticSearch"]["row"]
        rate_history = [{"month": x["TIME"], "rate": float(x["DATA_VALUE"])} for x in rows]
        print(f"[5/5] ECOS 기준금리 {len(rate_history)}개월 수집 완료")
    except Exception as e:
        print(f"[5/5] ECOS 실패({e}) → 수동값 {BASE_RATE_MANUAL}% 사용")
else:
    print(f"[5/5] ECOS 키 없음 → 수동값 {BASE_RATE_MANUAL}% 사용")

# ──────────────────────────────────────────────
# 저장
# ──────────────────────────────────────────────
out = {
    "generated": dt.datetime.now().isoformat(timespec="minutes"),
    "source": "pykrx (KRX/Naver 스크래핑, 참고용)",
    "dates": ref_dates,
    "base_rate_manual": BASE_RATE_MANUAL,
    "rate_history": rate_history,   # ECOS 연동 시 채워짐
    "index": index_series,
    "stocks": stocks,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print(f"완료 → {OUT} (종목 {len(stocks)}개, {len(index_series)}일)")
