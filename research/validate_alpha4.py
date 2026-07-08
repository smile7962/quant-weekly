# -*- coding: utf-8 -*-
"""
α4(추세 전환) 오프라인 검증 — 대시보드 로직 미러링
데이터: 저장소의 market_data.json (실데이터, 코스피200 시총상위 50)

검증 게이트:
  G1 중복성: α4 vs α1/α2/α3 단면 순위상관 (|ρ|>0.7이면 탈락)
  G2 단독 성과: α4 단독 롱온리 top10 백테스트 (2년)
  G3 결합 기여: 3-알파 기준선 vs 4-알파, In-sample/Out-of-sample 분리
  G4 국면별: 침체기(REC)에서 기여하는지

검증 결과 (2026-07-08, market_data.json 2023-04-25~2026-07-08):
  V1(모멘텀 가속 단독)  : G1 최대|ρ|=0.32 ✅ / G2 샤프 1.39 ✅
                          / G3 IS +13.8→+30.6%, OOS +81.0→+96.6%(샤프 1.68→1.73) ✅
                          / G4 REC 주간 +43.2→+85.9bp ✅  → 채택
  V2(가속+저점회복)     : 통과했으나 V1보다 독립성·REC 기여 낮음 → 보류
  V3(저점회복 단독)     : G1 vs α2 ρ=+0.739 ❌ (모멘텀과 중복) → 탈락
→ α4 = rank(20일 수익률 − 직전 20일 수익률) 로 대시보드 통합
"""
import json, math

D = json.load(open("market_data.json", encoding="utf-8"))
stocks = [s for s in D["stocks"] if s.get("pbr")]
index = D["index"]
N = len(index)
print(f"데이터: 종목 {len(stocks)}개, {N}일 ({D['dates'][0]} ~ {D['dates'][-1]})\n")

# ── 대시보드와 동일한 유틸 ──────────────────────
def rank(arr):
    idx = sorted(range(len(arr)), key=lambda i: arr[i])
    out = [0.0]*len(arr)
    for r, i in enumerate(idx):
        out[i] = r/(len(arr)-1) if len(arr) > 1 else 0.5
    return out

def ret(p, d, look, skip=0):
    a, b = p[d-skip], p[d-skip-look]
    return a/b-1 if b else 0.0

# ── 기존 3-알파 (index.html computeAlphas와 동일) ──
def alphas_base(d):
    r5  = [ret(s["prices"], d, 5) for s in stocks]
    r60 = [ret(s["prices"], d, 60, 5) for s in stocks]
    pbr = [s["pbr"] for s in stocks]
    a1 = [1-v for v in rank(r5)]
    a2 = rank(r60)
    a3 = [1-v for v in rank(pbr)]
    return a1, a2, a3

# ── α4 변형들 ──────────────────────────────────
def accel(d):     # 모멘텀 가속: 최근 20일 수익률 − 직전 20일 수익률
    return [ret(s["prices"], d, 20) - ret(s["prices"], d, 20, 20) for s in stocks]

def recovery(d):  # 60일 저점 대비 회복률
    out = []
    for s in stocks:
        w = s["prices"][d-59:d+1]
        lo = min(w)
        out.append(s["prices"][d]/lo - 1 if lo else 0.0)
    return out

def alpha4(d, variant):
    if variant == "V1": return rank(accel(d))
    if variant == "V3": return rank(recovery(d))
    ra, rr = rank(accel(d)), rank(recovery(d))
    return [(a+b)/2 for a, b in zip(ra, rr)]   # V2

# ── 국면 (index.html detectRegime; 금리축은 수동값이라 경기축만 유효) ──
def regime_key(d):
    def ma(dd, n): return sum(index[dd-n+1:dd+1])/n
    slope = (ma(d,200)-ma(d-20,200))/ma(d-20,200) if d >= 220 else 0
    return "EXP" if slope > 0 else "REC"

# ── 백테스트 (index.html backtest와 동일 규칙) ──
TOP_N, CAP, COST = 10, 0.15, 0.003
def build_pf(scores):
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:TOP_N]
    ws = [scores[i] for i in order]
    t = sum(ws); ws = [min(w/t, CAP) for w in ws]
    t2 = sum(ws); ws = [w/t2 for w in ws]
    return list(zip(order, ws))

def backtest(score_fn, d0, d1):
    eq, weekly, rkeys = 1.0, [], []
    for d in range(d0, d1-4, 5):
        pf = build_pf(score_fn(d))
        wr = sum(w*(stocks[i]["prices"][d+5]/stocks[i]["prices"][d]-1) for i, w in pf)
        wr -= COST*0.5
        eq *= 1+wr; weekly.append(wr); rkeys.append(regime_key(d))
    m = sum(weekly)/len(weekly)
    sd = math.sqrt(sum((x-m)**2 for x in weekly)/len(weekly))
    sharpe = m/sd*math.sqrt(52) if sd > 0 else 0
    peak, mdd, e = 0, 0, 1.0
    for x in weekly:
        e *= 1+x; peak = max(peak, e); mdd = min(mdd, e/peak-1)
    win = sum(1 for x in weekly if x > 0)/len(weekly)
    return dict(ret=eq-1, sharpe=sharpe, mdd=mdd, win=win, weekly=weekly, rkeys=rkeys)

def bench(d0, d1):
    return index[d1-((d1-d0)%5 or 5)+ (0 if (d1-d0)%5==0 else 0)]/index[d0]-1 if True else 0

# ── 기간 정의 ──────────────────────────────────
FULL0, FULL1 = N-501, N-1        # 최근 2년 (대시보드와 동일)
IS0, IS1 = FULL0, FULL0+250      # in-sample 1년
OS0, OS1 = FULL0+250, FULL1      # out-of-sample 1년

# ════ G1: 중복성 (단면 순위상관, 주간 평균) ════
def xcorr(v1, v2):
    n = len(v1); m1, m2 = sum(v1)/n, sum(v2)/n
    c = sum((a-m1)*(b-m2) for a, b in zip(v1, v2))
    s1 = math.sqrt(sum((a-m1)**2 for a in v1)); s2 = math.sqrt(sum((b-m2)**2 for b in v2))
    return c/(s1*s2) if s1*s2 else 0

print("═══ G1. 중복성: α4 변형 vs 기존 알파 (주간 단면 순위상관 평균) ═══")
for variant in ("V1", "V2", "V3"):
    cs = {"α1": [], "α2": [], "α3": []}
    for d in range(FULL0, FULL1-4, 5):
        a1, a2, a3 = alphas_base(d)
        a4 = alpha4(d, variant)
        cs["α1"].append(xcorr(a4, a1)); cs["α2"].append(xcorr(a4, a2)); cs["α3"].append(xcorr(a4, a3))
    line = "  ".join(f"vs {k}: {sum(v)/len(v):+.3f}" for k, v in cs.items())
    print(f"  {variant}: {line}")

# ════ G2: 단독 백테스트 ════
print("\n═══ G2. 단독 롱온리 top10 백테스트 (최근 2년) ═══")
base_fns = {
    "α1": lambda d: alphas_base(d)[0],
    "α2": lambda d: alphas_base(d)[1],
    "α3": lambda d: alphas_base(d)[2],
}
for name, fn in base_fns.items():
    r = backtest(fn, FULL0, FULL1)
    print(f"  {name}(기존): 수익 {r['ret']*100:+6.1f}%  샤프 {r['sharpe']:5.2f}  MDD {r['mdd']*100:6.1f}%  승률 {r['win']*100:.0f}%")
for variant in ("V1", "V2", "V3"):
    r = backtest(lambda d, v=variant: alpha4(d, v), FULL0, FULL1)
    print(f"  α4-{variant}   : 수익 {r['ret']*100:+6.1f}%  샤프 {r['sharpe']:5.2f}  MDD {r['mdd']*100:6.1f}%  승률 {r['win']*100:.0f}%")
bm = index[FULL1]/index[FULL0]-1
print(f"  KOSPI200 : 수익 {bm*100:+6.1f}%")

# ════ G3: 3-알파 vs 4-알파 (IS/OOS) ════
W3 = {"EXP": (0.3, 0.5, 0.2), "REC": (0.5, 0.1, 0.4)}          # 현행 (LO_* 기준 대표값)
W4 = {"EXP": (0.25, 0.45, 0.15, 0.15), "REC": (0.35, 0.10, 0.30, 0.25)}  # 제안

def score3(d):
    a1, a2, a3 = alphas_base(d); w = W3[regime_key(d)]
    return [w[0]*x+w[1]*y+w[2]*z for x, y, z in zip(a1, a2, a3)]

def make_score4(variant):
    def s(d):
        a1, a2, a3 = alphas_base(d); a4 = alpha4(d, variant); w = W4[regime_key(d)]
        return [w[0]*x+w[1]*y+w[2]*z+w[3]*u for x, y, z, u in zip(a1, a2, a3, a4)]
    return s

print("\n═══ G3. 결합: 3-알파 기준선 vs 4-알파 (IS 1년 / OOS 1년) ═══")
for label, d0, d1 in (("IS ", IS0, IS1), ("OOS", OS0, OS1), ("전체", FULL0, FULL1)):
    r3 = backtest(score3, d0, d1)
    row = f"  [{label}] 3-알파: {r3['ret']*100:+6.1f}% (샤프 {r3['sharpe']:.2f})"
    for variant in ("V1", "V2", "V3"):
        r4 = backtest(make_score4(variant), d0, d1)
        row += f" | +{variant}: {r4['ret']*100:+6.1f}% (샤프 {r4['sharpe']:.2f})"
    print(row)

# ════ G4: 국면별 주간 평균수익 기여 ════
print("\n═══ G4. 국면별 주간 평균수익 (bp/주) ═══")
r3f = backtest(score3, FULL0, FULL1)
rows = {"3-알파": r3f}
for variant in ("V1", "V2", "V3"):
    rows[f"4-알파+{variant}"] = backtest(make_score4(variant), FULL0, FULL1)
for name, r in rows.items():
    exp = [w for w, k in zip(r["weekly"], r["rkeys"]) if k == "EXP"]
    rec = [w for w, k in zip(r["weekly"], r["rkeys"]) if k == "REC"]
    f = lambda xs: f"{sum(xs)/len(xs)*1e4:+7.1f} ({len(xs)}주)" if xs else "   해당없음"
    print(f"  {name:12s}: EXP {f(exp)}   REC {f(rec)}")

n_exp = sum(1 for k in r3f["rkeys"] if k == "EXP")
print(f"\n  참고: 최근 2년 국면 분포 — EXP {n_exp}주 / REC {len(r3f['rkeys'])-n_exp}주")
print("  참고: 금리축은 수동값(2.5%)이라 경기축(200일선 기울기)만 유효")
