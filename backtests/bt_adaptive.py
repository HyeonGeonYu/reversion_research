"""
적응형 임계값 백테스트 — 실제 봇처럼 b를 "7일간 ~5크로스" 롤링으로 산출.

- b(1분 진입 임계값) = 적응형: 트레일링 7일(10080봉) 윈도우에서 cross ~target(5)이 되는 threshold.
  (engines.py의 _count_cross / _find_optimal_threshold 포팅, 매일 재계산하여 그날 적용)
- a(일봉 이격) = 스윕 (무룩어헤드 일봉 확정봉 기준)
- c(브래킷) = kc * b_adaptive (적응형 임계값의 배수) 스윕, 청산 ±c, timeout 없음.

승률이 50%에서 일관/유의하게 벗어나는 (a, kc)를 찾는다.
"""
from __future__ import annotations
import sys, os, bisect, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

DAY_MS = 86_400_000
MA_P = 100
WIN = 10080            # 7일 윈도우(분봉)
TARGET = 5            # 주당 크로스 목표
MIN_THR, MAX_THR = 0.005, 0.07
MIN_INT = 60          # 크로스 최소간격(분) = 1시간
RECALC = 1440         # 임계값 재계산 주기(분) = 1일

A_GRID = [None, 0.0, 0.02, 0.05, 0.10]   # 일봉 이격(None=조건없음)
KC_GRID = [1.0, 1.5, 2.0, 3.0]           # c = kc * b_adaptive


def count_cross(C, Hi, Lo, ma, lo, hi, thr):
    cnt = 0; state = None; lastU = lastD = -10**9
    for i in range(lo, hi):
        m = ma[i]
        if m is None:
            continue
        up = m*(1+thr); dn = m*(1-thr)
        if state in ("below", "in") and Hi[i] > up and (i-lastU) > MIN_INT:
            cnt += 1; lastU = i
        if state in ("above", "in") and Lo[i] < dn and (i-lastD) > MIN_INT:
            cnt += 1; lastD = i
        cl = C[i]
        state = "above" if cl > up else ("below" if cl < dn else "in")
    return cnt


def adaptive_thr(C, Hi, Lo, ma, lo, hi):
    left, right = MIN_THR, MAX_THR; opt = right
    for _ in range(18):
        mid = (left+right)/2
        c = count_cross(C, Hi, Lo, ma, lo, hi, mid)
        if c > TARGET:
            left = mid
        else:
            opt = mid; right = mid
    return max(opt, MIN_THR)


def precompute_thresholds(C, Hi, Lo, ma):
    """각 봉 인덱스 → 그 시점 적용 임계값(매 RECALC마다 트레일링 WIN으로 재계산)."""
    n = len(C)
    thr_at = [None]*n
    cur = None
    next_calc = WIN
    for i in range(n):
        if i >= WIN and i >= next_calc:
            cur = adaptive_thr(C, Hi, Lo, ma, i-WIN, i)
            next_calc = i + RECALC
        thr_at[i] = cur
    return thr_at


def simulate(C, Hi, Lo, ma, ts, daily, mad, thr_at, a, kc, lo, hi):
    n = len(C)
    starts = [d["start"] for d in daily]
    def ddev(t):
        j = bisect.bisect_right(starts, t-DAY_MS)-1
        return None if (j < 0 or mad[j] is None) else (daily[j]["close"]-mad[j])/mad[j]

    w = l = 0; i = max(WIN, lo); armed = True
    while i < hi:
        m = ma[i]; b = thr_at[i]
        if m is None or b is None:
            i += 1; continue
        d = (C[i]-m)/m
        if armed and abs(d) >= b:
            side = 1 if d <= -b else -1
            if a is not None:
                dd = ddev(ts[i])
                if dd is None or not ((dd <= -a) if side == 1 else (dd >= a)):
                    i += 1; continue
            c = kc * b
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
            if res is None:
                break
            w += res > 0; l += res < 0; armed = False; i = xi; continue
        if abs(d) < b:
            armed = True
        i += 1
    return w, l


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=365)
    daily = fetch_klines_bybit(sym, "D", days=1095)
    C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
    ts=[x['start'] for x in c1]; ma=_ma_hlc3(c1, MA_P); mad=_ma_hlc3(daily, MA_P)
    days_span = (ts[-1]-ts[0])/DAY_MS
    n = len(C); mid = n//2

    print(f"{sym} {n:,}분봉 — 적응형 임계값(7일 {TARGET}크로스) 산출 중...")
    thr_at = precompute_thresholds(C, Hi, Lo, ma)
    valid = [t for t in thr_at if t is not None]
    print(f"  적응형 b 범위: {min(valid)*100:.2f}% ~ {max(valid)*100:.2f}% (평균 {sum(valid)/len(valid)*100:.2f}%)\n")

    print(f"{'a(일봉)':>8}{'kc':>5}{'승률':>7}{'n':>6}{'하루':>7}{'z':>7} | {'IS승률':>7}{'OOS승률':>8}")
    for a in A_GRID:
        for kc in KC_GRID:
            w, l = simulate(C, Hi, Lo, ma, ts, daily, mad, thr_at, a, kc, WIN, n)
            tot = w+l
            if tot < 30:
                continue
            wr = w/tot; z = (wr-0.5)/math.sqrt(0.25/tot)
            iw, il = simulate(C, Hi, Lo, ma, ts, daily, mad, thr_at, a, kc, WIN, mid)
            ow, ol = simulate(C, Hi, Lo, ma, ts, daily, mad, thr_at, a, kc, mid, n)
            isr = iw/(iw+il) if (iw+il) else 0
            osr = ow/(ow+ol) if (ow+ol) else 0
            al = "없음" if a is None else f"{a*100:.0f}%"
            print(f"{al:>8}{kc:>5.1f}{wr*100:>6.1f}%{tot:>6}{tot/days_span:>5.2f}/일{z:>+6.2f} | "
                  f"{isr*100:>6.1f}%{osr*100:>7.1f}%")


if __name__ == "__main__":
    main()
