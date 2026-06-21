"""
AND 게이트 + ±c 대칭 브래킷 백테스트 (무제한 보유, 3년).

진입: 일봉 SMA30±2σ 게이트(전일 확정 일봉, 무룩어헤드) AND 1분 SMA10080±3.48σ, 같은방향. hlc3.
  일봉 과매도 & 1분 과매도 → 롱 / 일봉 과매수 & 1분 과매수 → 숏.
청산: 진입가 ±c (timeout 없음). +c 먼저=승, -c 먼저=패. 같은봉 동시=보수적 손절.
c 스윕 → 승률 / 기대값(수수료후) / 평균보유 / 거래수 / IS·OOS.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY = 86_400_000
FEE = 0.0011
WIN = 10080
MODE = os.environ.get("MODE", "reversion")   # reversion(회귀) / momentum(추세)
KM = 3.48      # 1분 σ
KD = 2.0       # 일봉 σ
C_LIST = [0.005, 0.01, 0.015, 0.02, 0.03, 0.04]


def hlc3(rows):
    H=np.array([x['high'] for x in rows]); L=np.array([x['low'] for x in rows]); C=np.array([x['close'] for x in rows])
    return (H+L+C)/3


def main():
    sym="BTCUSDT"
    d=fetch_klines_bybit(sym,"D",days=1095)
    dh=hlc3(d); ds=pd.Series(dh)
    dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dstarts=[x['start'] for x in d]
    dgate=[ (-1 if dz[i]<=-KD else (1 if dz[i]>=KD else 0)) if np.isfinite(dz[i]) else 0 for i in range(len(d)) ]
    # -1: 과매도(롱 게이트) / +1: 과매수(숏 게이트)

    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]); Lo=np.array([x['low'] for x in m]); C=np.array([x['close'] for x in m]); ts=np.array([x['start'] for x in m])
    mh=(Hi+Lo+C)/3; s=pd.Series(mh)
    z=((s-s.rolling(WIN).mean())/s.rolling(WIN).std(ddof=0)).to_numpy()
    n=len(m); mid=n//2; span=(ts[-1]-ts[0])/DAY

    def gate_at(t):
        j=bisect.bisect_right(dstarts, int(t)-DAY)-1
        return dgate[j] if j>=0 else 0

    def sim(c, lo, hi):
        w=l=0; holds=[]; i=max(WIN,lo); armed=True
        while i<hi:
            v=z[i]
            if not np.isfinite(v): i+=1; continue
            if armed and abs(v)>=KM:
                mdir = -1 if v<=-KM else 1   # -1 과매도(롱) / +1 과매수(숏)
                if gate_at(ts[i])==mdir:
                    # reversion: 과매도→롱(mdir==-1) / momentum: 과매도→숏
                    longside = (mdir==-1) if MODE=="reversion" else (mdir==1)
                    P0=C[i]
                    if longside: tp=P0*(1+c); sl=P0*(1-c)
                    else:        tp=P0*(1-c); sl=P0*(1+c)
                    res=None; xi=None; k=i+1
                    while k<n:
                        if longside: ht=Hi[k]>=tp; hs=Lo[k]<=sl
                        else:        ht=Lo[k]<=tp; hs=Hi[k]>=sl
                        if ht and hs: res=-1; xi=k; break
                        if ht: res=1; xi=k; break
                        if hs: res=-1; xi=k; break
                        k+=1
                    if res is None: break
                    w+= res>0; l+= res<0; holds.append((xi-i)); armed=False; i=xi; continue
            if abs(v)<KM: armed=True
            i+=1
        tot=w+l
        return tot, (w/tot if tot else 0), (np.mean(holds) if holds else 0)

    print(f"{sym} 3년 — AND게이트 + ±c 무제한보유, 방향={MODE}, 수수료 {FEE*100:.2f}%\n")
    print(f"{'c':>6}{'거래수':>7}{'승률':>8}{'평균보유':>9}{'기대값(net)':>12}{'IS승률':>8}{'OOS승률':>8}{'연거래':>7}")
    for c in C_LIST:
        tot,wr,hold = sim(c, WIN, n)
        if tot<5:
            print(f"{c*100:>5.1f}%  거래 {tot}개(부족)"); continue
        net=(2*wr-1)*c - FEE
        _,isr,_=sim(c,WIN,mid); _,osr,_=sim(c,mid,n)
        hh = hold/60.0  # 분→시간
        hs = f"{hh:.1f}h" if hh<48 else f"{hh/24:.1f}d"
        print(f"{c*100:>5.1f}%{tot:>7}{wr*100:>7.1f}%{hs:>9}{net*100:>+11.3f}%{isr*100:>7.1f}%{osr*100:>7.1f}%{tot/(span/365):>6.1f}")


if __name__ == "__main__":
    main()
