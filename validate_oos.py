"""
Out-of-sample 검증 — 대칭 브래킷 평균회귀 전략 (오프라인 read-only)

방법:
  1) 시간분할: 1년을 상반기(IS)/하반기(OOS)로 분할.
     IS에서 최적 (T, X, horizon) 탐색 → 그 값을 OOS에 그대로 적용.
     OOS에서도 net(테이커 수수료 차감)이 양수면 진짜 엣지, 무너지면 과적합.
  2) 심볼 교차: BTC-IS 최적값을 다른 심볼에 그대로 적용.

수수료: 테이커 왕복 0.11% 가정 (보수적).
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE_TK = float(os.environ.get("FEE", "0.0011"))  # 기본 테이커 왕복 0.11%, env FEE로 변경

T_GRID = [0.005, 0.0075, 0.01, 0.015]
X_GRID = [0.01, 0.02, 0.03, 0.05]
H_GRID = [60, 240, 720, 1440, 4320]   # 1h / 4h / 12h / 1d / 3d (보유기간도 최적화)
MIN_N = 60


def bracket_stats(C, Hi, Lo, ma, ma_period, T, X, horizon, lo, hi):
    """
    entry index가 [lo,hi)인 사건만. forward walk는 전체 배열 사용 가능.
    실제 실현손익 사용: TP=+X, SL=-X, 시간초과=실제 종가손익(소폭).
    """
    n = len(C)
    pnls = []
    ntp = nsl = nto = 0
    i = max(ma_period, lo)
    armed = True
    while i < hi:
        m = ma[i]
        if m is None:
            i += 1
            continue
        d = (C[i] - m) / m
        if armed and abs(d) >= T:
            side = 1 if d <= -T else -1
            P0 = C[i]
            if side == 1:
                tp = P0 * (1 + X); sl = P0 * (1 - X)
            else:
                tp = P0 * (1 - X); sl = P0 * (1 + X)
            end = min(i + horizon, n - 1)
            pnl = None; xi = None
            for k in range(i + 1, end + 1):
                if side == 1:
                    ht = Hi[k] >= tp; hs = Lo[k] <= sl
                else:
                    ht = Lo[k] <= tp; hs = Hi[k] >= sl
                if ht and hs:
                    pnl = -X; nsl += 1; xi = k; break   # 같은봉=보수적 손절먼저
                if ht:
                    pnl = X; ntp += 1; xi = k; break
                if hs:
                    pnl = -X; nsl += 1; xi = k; break
            if pnl is None:                              # 시간초과 → 실제 종가손익
                pnl = side * (C[end] - P0) / P0; nto += 1; xi = end
            pnls.append(pnl)
            armed = False
            i = xi
            continue
        if abs(d) < T:
            armed = True
        i += 1

    if not pnls:
        return None
    cnt = len(pnls)
    wr = sum(1 for p in pnls if p > 0) / cnt
    gross = sum(pnls) / cnt                               # 실제 평균 실현손익
    resolved = ntp + nsl
    wr_resolved = (ntp / resolved) if resolved else 0.0   # TP/SL로 끝난 것 중 승률
    return {"n": cnt, "wr": wr, "gross": gross, "net": gross - FEE_TK,
            "T": T, "X": X, "H": horizon,
            "tp": ntp / cnt, "sl": nsl / cnt, "to": nto / cnt,
            "wr_resolved": wr_resolved, "resolve_rate": resolved / cnt}


def grid_search(C, Hi, Lo, ma, lo, hi):
    best = None
    for T in T_GRID:
        for X in X_GRID:
            for H in H_GRID:
                s = bracket_stats(C, Hi, Lo, ma, 100, T, X, H, lo, hi)
                if s and s["n"] >= MIN_N and (best is None or s["net"] > best["net"]):
                    best = s
    return best


def load(sym):
    c = fetch_klines_bybit(sym, "1", days=365)
    return ([x["close"] for x in c], [x["high"] for x in c], [x["low"] for x in c],
            _ma_hlc3(c, 100), len(c))


def main():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    data = {}
    for s in symbols:
        data[s] = load(s)
        print(f"[{s}] {data[s][4]:,}봉 로드")

    print("\n" + "=" * 70)
    print("1) 시간분할 검증 (IS=상반기 최적 → OOS=하반기 적용)  [테이커 0.11%]")
    print("=" * 70)
    print(f"{'심볼':>8} | {'IS 최적 (T/X/보유)':>20} {'IS순기대':>9} {'IS승률':>7} | "
          f"{'OOS순기대':>9} {'OOS승률':>7} {'OOS건수':>7}  판정")
    btc_is_best = None
    for s in symbols:
        C, Hi, Lo, ma, n = data[s]
        mid = n // 2
        is_best = grid_search(C, Hi, Lo, ma, 100, mid)
        if s == "BTCUSDT":
            btc_is_best = is_best
        if not is_best:
            print(f"{s:>8} | IS 유효조합 없음")
            continue
        oos = bracket_stats(C, Hi, Lo, ma, 100, is_best["T"], is_best["X"], is_best["H"], mid, n)
        cfg = f"{is_best['T']*100:.2f}/{is_best['X']*100:.2f}/{is_best['H']//60}h"
        verdict = "✅ 유지" if (oos and oos["net"] > 0) else "❌ 붕괴(과적합)"
        if oos:
            print(f"{s:>8} | {cfg:>20} {is_best['net']*100:>+8.3f}% {is_best['wr']*100:>6.1f}% | "
                  f"{oos['net']*100:>+8.3f}% {oos['wr']*100:>6.1f}% {oos['n']:>7}  {verdict}")
            print(f"{'':>8} |   └ OOS 구성: 익절 {oos['tp']*100:.0f}% / 손절 {oos['sl']*100:.0f}% / "
                  f"시간초과 {oos['to']*100:.0f}%  | 결판율 {oos['resolve_rate']*100:.0f}%, "
                  f"결판승률 {oos['wr_resolved']*100:.1f}%")

    print("\n" + "=" * 70)
    print("2) 심볼 교차검증 (BTC-IS 최적값을 각 심볼 전체구간에 그대로 적용)")
    print("=" * 70)
    if btc_is_best:
        cfg = f"T={btc_is_best['T']*100:.2f}% X={btc_is_best['X']*100:.2f}% H={btc_is_best['H']//60}h"
        print(f"  적용 파라미터: {cfg}")
        print(f"{'심볼':>8} {'순기대':>9} {'승률':>7} {'건수':>7}  판정")
        for s in symbols:
            C, Hi, Lo, ma, n = data[s]
            r = bracket_stats(C, Hi, Lo, ma, 100, btc_is_best["T"], btc_is_best["X"], btc_is_best["H"], 100, n)
            if r:
                v = "✅" if r["net"] > 0 else "❌"
                print(f"{s:>8} {r['net']*100:>+8.3f}% {r['wr']*100:>6.1f}% {r['n']:>7}  {v}")


if __name__ == "__main__":
    main()
