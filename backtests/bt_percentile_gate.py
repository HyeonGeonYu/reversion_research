"""
백분위 게이트 백테스트 — "드문 일봉 극단"에서만 1분봉 평균회귀 게임.

정의(둘 다 롤링 백분위 = 확률적 드문 극단):
  일봉 이격 d_D = (일봉종가 - 일봉MA100)/MA100.
    rare-low = d_D가 과거(확장창) 하위 P% / rare-high = 상위 P%.
  1분 이격 d_m = (가격 - 1분MA100)/MA100.
    트레일링 30일 분포의 하위 P%(thr_low)/상위 P%(thr_high) 임계값, 매일 재계산.
진입: 1분이 극단 꼬리 AND (게이트ON이면)일봉도 같은쪽 극단 → 회귀 베팅.
  LONG(아래극단): d_m<=thr_low AND d_D rare-low.  SHORT(위극단): 대칭.
청산: ±c 대칭(timeout 없음). 승=+c(회귀), 패=-c(지속).

게이트 ON(일봉 극단 동시) vs OFF(1분 극단만) 비교 → 일봉 게이트 효과 검증. IS/OOS 포함.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

DAY_MS = 86_400_000
MA_P = 100
M_WIN = 30*1440        # 1분 백분위 트레일링 창 = 30일
RECALC = 1440          # 1분 임계값 재계산 주기 = 1일
D_MINHIST = 250        # 일봉 백분위 최소 과거표본
FEE = 0.0011

P_GRID = [2.0, 5.0, 10.0]                  # 극단 꼬리 %
C_GRID = [0.005, 0.01, 0.02, 0.03]         # 브래킷


def dev_series(C, ma):
    return [ (C[i]-ma[i])/ma[i] if ma[i] is not None else None for i in range(len(C)) ]


def precompute_1m_thr(dev, P):
    """매 RECALC마다 트레일링 M_WIN 분포의 P/(100-P) 분위값. 반환 thr_low[i], thr_high[i]."""
    n = len(dev)
    lo_at = [None]*n; hi_at = [None]*n
    cur_lo = cur_hi = None; nxt = M_WIN
    for i in range(n):
        if i >= M_WIN and i >= nxt:
            w = np.array([x for x in dev[i-M_WIN:i] if x is not None])
            if len(w) > 500:
                cur_lo = np.percentile(w, P)
                cur_hi = np.percentile(w, 100-P)
            nxt = i + RECALC
        lo_at[i] = cur_lo; hi_at[i] = cur_hi
    return lo_at, hi_at


def precompute_daily_tail(dD, P):
    """확장창 백분위로 각 일봉의 rare-low / rare-high 플래그."""
    n = len(dD)
    low = [False]*n; high = [False]*n
    vals = []
    for i in range(n):
        if dD[i] is None:
            continue
        if len(vals) >= D_MINHIST:
            arr = np.array(vals)
            lo_thr = np.percentile(arr, P); hi_thr = np.percentile(arr, 100-P)
            if dD[i] <= lo_thr: low[i] = True
            if dD[i] >= hi_thr: high[i] = True
        vals.append(dD[i])
    return low, high


def simulate(C, Hi, Lo, dm, lo_at, hi_at, ts, dstarts, dlow, dhigh, c, lo, hi, gate):
    n = len(C); w = l = 0; i = max(M_WIN, lo); armed = True
    def daily_state(t):
        j = bisect.bisect_right(dstarts, t-DAY_MS)-1
        if j < 0: return (False, False)
        return (dlow[j], dhigh[j])
    while i < hi:
        d = dm[i]; tl = lo_at[i]; th = hi_at[i]
        if d is None or tl is None:
            i += 1; continue
        side = 0
        if d <= tl: side = 1       # 아래 극단 → LONG
        elif d >= th: side = -1    # 위 극단 → SHORT
        if armed and side != 0:
            if gate:
                dl, dh = daily_state(ts[i])
                if (side == 1 and not dl) or (side == -1 and not dh):
                    i += 1; continue
            P0 = C[i]
            tp = P0*(1+c) if side == 1 else P0*(1-c)
            sl = P0*(1-c) if side == 1 else P0*(1+c)
            res = None; xi = None; k = i+1
            while k < n:
                ht = (Hi[k] >= tp) if side == 1 else (Lo[k] <= tp)
                hs = (Lo[k] <= sl) if side == 1 else (Hi[k] >= sl)
                if ht and hs: res = -1; xi = k; break
                if ht: res = 1; xi = k; break
                if hs: res = -1; xi = k; break
                k += 1
            if res is None: break
            w += res > 0; l += res < 0; armed = False; i = xi; continue
        if side == 0:
            armed = True
        i += 1
    return w, l


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=1095)   # 3년치
    daily = fetch_klines_bybit(sym, "D", days=1095)
    C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
    ts=[x['start'] for x in c1]; ma=_ma_hlc3(c1, MA_P)
    dC=[x['close'] for x in daily]; dma=_ma_hlc3(daily, MA_P); dstarts=[x['start'] for x in daily]
    dm = dev_series(C, ma); dD = dev_series(dC, dma)
    n = len(C); mid = n//2; span = (ts[-1]-ts[0])/DAY_MS
    print(f"{sym} 1분봉 {n:,} (~{span:.0f}일), 일봉 {len(dC)}\n")

    for P in P_GRID:
        lo_at, hi_at = precompute_1m_thr(dm, P)
        dlow, dhigh = precompute_daily_tail(dD, P)
        for c in C_GRID:
            res = {}
            for gate, tag in [(True, "게이트ON"), (False, "OFF")]:
                w, l = simulate(C, Hi, Lo, dm, lo_at, hi_at, ts, dstarts, dlow, dhigh, c, M_WIN, n, gate)
                tot = w+l
                wr = w/tot if tot else 0; z = (wr-0.5)/math.sqrt(0.25/tot) if tot else 0
                iw, il = simulate(C, Hi, Lo, dm, lo_at, hi_at, ts, dstarts, dlow, dhigh, c, M_WIN, mid, gate)
                ow, ol = simulate(C, Hi, Lo, dm, lo_at, hi_at, ts, dstarts, dlow, dhigh, c, mid, n, gate)
                isr = iw/(iw+il) if (iw+il) else 0; osr = ow/(ow+ol) if (ow+ol) else 0
                res[tag] = (wr, tot, z, isr, osr)
            on = res["게이트ON"]; off = res["OFF"]
            print(f"P={P:>4.0f}% c={c*100:>4.1f}% | ON {on[0]*100:5.1f}%(n{on[1]:>4},z{on[2]:+.2f},IS{on[3]*100:.0f}/OOS{on[4]*100:.0f}) "
                  f"| OFF {off[0]*100:5.1f}%(n{off[1]:>5}) | 게이트효과 {(on[0]-off[0])*100:+.1f}%p")


if __name__ == "__main__":
    main()
