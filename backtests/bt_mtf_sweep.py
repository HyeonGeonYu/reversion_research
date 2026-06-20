"""
일봉 볼린저 기간 × k 스윕 — 1분 게임(게이트+RSI turn)이 가장 잘 되는 일봉 설정 찾기. (BTC 3년)
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY_MS = 86_400_000
FEE = 0.0011
RSI_P = 14
THR_LO, THR_HI = 30.0, 70.0

PERIODS = [10, 20, 50, 100, 200]
KS = [1.5, 2.0, 2.5]
C_LIST = [0.01, 0.02]


def rsi(close, period):
    s = pd.Series(close); d = s.diff()
    ag = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    al = (-d).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    rs = ag/al.replace(0, np.nan)
    return (100 - 100/(1+rs)).to_numpy()


def daily_bias(dC, N_D, KD):
    n = len(dC); sma = np.full(n, np.nan); sd = np.full(n, np.nan)
    for i in range(N_D-1, n):
        w = dC[i-N_D+1:i+1]; sma[i] = w.mean(); sd[i] = w.std()
    z = np.where(sd > 0, (dC-sma)/sd, np.nan)
    bias = np.zeros(n, dtype=int)
    bias[z <= -KD] = 1; bias[z >= KD] = -1
    return bias


def simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, lo, hi):
    n = len(C); w = l = 0; i = max(1, lo); armed = True
    def bias_at(t):
        j = bisect.bisect_right(dstarts, t-DAY_MS)-1
        return dbias[j] if j >= 0 else 0
    while i < hi:
        r0 = R[i-1]; r1 = R[i]
        if not (np.isfinite(r0) and np.isfinite(r1)):
            i += 1; continue
        sig = 0
        if r0 <= THR_LO and r1 > THR_LO: sig = 1
        elif r0 >= THR_HI and r1 < THR_HI: sig = -1
        if armed and sig != 0:
            if bias_at(ts[i]) != sig:
                i += 1; continue
            side = sig; P0 = C[i]
            tp = P0*(1+c) if side == 1 else P0*(1-c); sl = P0*(1-c) if side == 1 else P0*(1+c)
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
        if THR_LO < r1 < THR_HI:
            armed = True
        i += 1
    return w, l


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=1095)
    daily = fetch_klines_bybit(sym, "D", days=1095)
    C=np.array([x['close'] for x in c1]); Hi=np.array([x['high'] for x in c1]); Lo=np.array([x['low'] for x in c1])
    ts=[x['start'] for x in c1]; dC=np.array([x['close'] for x in daily]); dstarts=[x['start'] for x in daily]
    R = rsi(C, RSI_P)
    n = len(C); mid = n//2; span = (ts[-1]-ts[0])/DAY_MS
    print(f"{sym} 1분 {n:,} (~{span:.0f}일), 트리거 RSI{RSI_P} turn, 수수료 {FEE*100:.2f}%")
    print("일봉 볼린저 기간×k 스윕 → 게이트+turn 게임\n")

    for c in C_LIST:
        print(f"==== c={c*100:.0f}% ====")
        print(f"{'일봉기간':>7}{'k':>5}{'승률':>8}{'n':>6}{'z':>7}{'IS/OOS':>10}{'순기대':>9}{'/일':>7}")
        for N_D in PERIODS:
            for KD in KS:
                dbias = daily_bias(dC, N_D, KD)
                w, l = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, 1, n)
                tot = w+l
                if tot < 20:
                    print(f"{N_D:>6}일{KD:>5.1f}   (표본부족 n={tot})"); continue
                wr = w/tot; z = (wr-0.5)/math.sqrt(0.25/tot)
                iw, il = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, 1, mid)
                ow, ol = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, mid, n)
                isr = iw/(iw+il) if (iw+il) else 0; osr = ow/(ow+ol) if (ow+ol) else 0
                net = (2*wr-1)*c - FEE
                star = " *" if (wr > 0.5 and z >= 1.5) else ""
                print(f"{N_D:>6}일{KD:>5.1f}{wr*100:>7.1f}%{tot:>6}{z:>+6.2f}{isr*100:>5.0f}/{osr*100:<4.0f}{net*100:>+7.3f}%{tot/span:>5.2f}{star}")
        print()


if __name__ == "__main__":
    main()
