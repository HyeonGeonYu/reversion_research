"""
MTF 백테스트 — 일봉 z게이트(방향 바이어스) + 1분 RSI 트리거(turn vs stretch).

일봉(상위): z_D=(종가-SMA100)/σ100. z_D<=-kD → 그날 롱 바이어스 / z_D>=+kD → 숏.
1분(하위):  RSI(period).
  turn(B):    롱 = RSI가 thr_lo 아래→위로 교차(꺾임). 숏 = thr_hi 위→아래.
  stretch(A): 롱 = RSI<=thr_lo (단순 과매도).
진입: 일봉 바이어스 방향 AND 해당 1분 트리거. 청산: ±c 대칭(timeout 없음).
비교: 게이트+turn / turn만(게이트OFF) / 게이트+stretch.  IS/OOS 포함.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY_MS = 86_400_000
FEE = 0.0011
N_D = 100           # 일봉 SMA/σ
KD = 2.0            # 일봉 z 게이트
RSI_P = 14          # 1분 RSI
THR_LO, THR_HI = 30.0, 70.0
C_GRID = [0.005, 0.01, 0.02, 0.03]


def rsi(close, period):
    s = pd.Series(close)
    d = s.diff()
    gain = d.clip(lower=0); loss = (-d).clip(lower=0)
    ag = gain.ewm(alpha=1/period, adjust=False).mean()
    al = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = ag/al.replace(0, np.nan)
    return (100 - 100/(1+rs)).to_numpy()


def daily_bias(daily):
    C = np.array([x['close'] for x in daily]); n = len(C)
    sma = np.full(n, np.nan); sd = np.full(n, np.nan)
    for i in range(N_D-1, n):
        w = C[i-N_D+1:i+1]; sma[i] = w.mean(); sd[i] = w.std()
    z = np.where(sd > 0, (C-sma)/sd, np.nan)
    bias = np.zeros(n, dtype=int)   # +1 long, -1 short
    for i in range(n):
        if np.isfinite(z[i]):
            if z[i] <= -KD: bias[i] = 1
            elif z[i] >= KD: bias[i] = -1
    return bias, [x['start'] for x in daily]


def simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, lo, hi, mode, gate):
    n = len(C); w = l = 0; i = max(1, lo); armed = True
    def bias_at(t):
        j = bisect.bisect_right(dstarts, t-DAY_MS)-1
        return dbias[j] if j >= 0 else 0
    while i < hi:
        r0 = R[i-1]; r1 = R[i]
        if not (np.isfinite(r0) and np.isfinite(r1)):
            i += 1; continue
        sig = 0
        if mode == "turn":
            if r0 <= THR_LO and r1 > THR_LO: sig = 1     # 과매도에서 위로 꺾임 → 롱
            elif r0 >= THR_HI and r1 < THR_HI: sig = -1
        else:  # stretch
            if r1 <= THR_LO: sig = 1
            elif r1 >= THR_HI: sig = -1
        if armed and sig != 0:
            if gate and bias_at(ts[i]) != sig:
                i += 1; continue
            side = sig; P0 = C[i]
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
        if THR_LO < r1 < THR_HI:
            armed = True       # RSI 중립 복귀 시 재무장
        i += 1
    return w, l


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=1095)
    daily = fetch_klines_bybit(sym, "D", days=1095)
    C=np.array([x['close'] for x in c1]); Hi=np.array([x['high'] for x in c1]); Lo=np.array([x['low'] for x in c1])
    ts=[x['start'] for x in c1]
    R = rsi(C, RSI_P)
    dbias, dstarts = daily_bias(daily)
    n = len(C); mid = n//2; span = (ts[-1]-ts[0])/DAY_MS
    print(f"{sym} 1분 {n:,} (~{span:.0f}일), RSI{RSI_P} {THR_LO:.0f}/{THR_HI:.0f}, 일봉 z게이트 ±{KD:.0f}σ, 수수료 {FEE*100:.2f}%\n")

    def stat(mode, gate, c):
        w, l = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, 1, n, mode, gate)
        tot = w+l; wr = w/tot if tot else 0; z = (wr-0.5)/math.sqrt(0.25/tot) if tot else 0
        iw, il = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, 1, mid, mode, gate)
        ow, ol = simulate(C, Hi, Lo, R, ts, dstarts, dbias, c, mid, n, mode, gate)
        isr = iw/(iw+il) if (iw+il) else 0; osr = ow/(ow+ol) if (ow+ol) else 0
        net = (2*wr-1)*c - FEE
        return wr, tot, z, isr, osr, net

    for c in C_GRID:
        print(f"--- c={c*100:.1f}% ---")
        for label, mode, gate in [("게이트+turn(추천)", "turn", True),
                                   ("turn만(게이트OFF)", "turn", False),
                                   ("게이트+stretch", "stretch", True)]:
            wr, tot, z, isr, osr, net = stat(mode, gate, c)
            print(f"  {label:<18} 승률 {wr*100:5.1f}% n{tot:>5} z{z:+.2f} | IS{isr*100:.0f}/OOS{osr*100:.0f} | 순기대 {net*100:+.3f}% | {tot/span:.2f}/일")
        print()


if __name__ == "__main__":
    main()
