"""
더블극단 모멘텀 + RSI 게이트, 청산 ±c 스윕, 승률. 4심볼 풀링 3년.

게이트(일봉, 전일확정): 볼린저 z>=+2 AND RSI(15)>60 → 상승추세 / z<=-2 AND RSI(15)<40 → 하락추세.
트리거(1분, SMA10080±3.48σ, hlc3): 같은방향 극단.
방향=모멘텀(추세추종): 상승추세+1분 과매수극단 → 롱 / 하락추세+1분 과매도극단 → 숏.
청산: ±c (이익+c / 손해-c) 무제한보유. c 스윕.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; FEE=0.0011; WIN=10080; KM=3.48; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
C_LIST=[0.005,0.01,0.015,0.02,0.025,0.03]


def rsi(close,p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()


def load(sym):
    d=fetch_klines_bybit(sym,"D",days=1095)
    H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
    ds=pd.Series((H+L+Cc)/3); dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dr=rsi(Cc,RSI_P); dst=[x['start'] for x in d]; dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(dz[i]) and np.isfinite(dr[i]):
            if dz[i]>=KD and dr[i]>RSI_HI: dg[i]=+1
            elif dz[i]<=-KD and dr[i]<RSI_LO: dg[i]=-1
    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+C)/3); z=((s-s.rolling(WIN).mean())/s.rolling(WIN).std(ddof=0)).to_numpy()
    return Hi,Lo,C,ts,z,dst,dg


def trades(Hi,Lo,C,ts,z,dst,dg,c):
    n=len(C); out=[]; i=WIN; armed=True
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0:
            # 모멘텀: 상승추세(g=+1)면 1분 과매수극단(z>=+3.48)에 롱
            trig=(g==1 and v>=KM) or (g==-1 and v<=-KM)
            if trig:
                longside=(g==1); P0=C[i]
                if longside: tp=P0*(1+c); sl=P0*(1-c)
                else:        tp=P0*(1-c); sl=P0*(1+c)
                res=None;xi=None;k=i+1
                while k<n:
                    if longside: ht=Hi[k]>=tp; hs=Lo[k]<=sl
                    else:        ht=Lo[k]<=tp; hs=Hi[k]>=sl
                    if ht and hs: res=-1;xi=k;break
                    if ht: res=1;xi=k;break
                    if hs: res=-1;xi=k;break
                    k+=1
                if res is None: break
                out.append((int(ts[i]),res>0)); armed=False; i=xi; continue
        if abs(v)<KM: armed=True
        i+=1
    return out


def main():
    data={s:load(s) for s in SYMS}
    mids={s:data[s][3][len(data[s][3])//2] for s in SYMS}
    print(f"더블극단 모멘텀 + RSI{RSI_P}>{RSI_HI} 게이트, 1분 3.48σ 고정, 청산 ±c 스윕, 4심볼 3년, 수수료 {FEE*100:.2f}%\n")
    print(f"{'c':>6}{'풀n':>6}{'승률':>8}{'z':>7}{'net':>9}{'IS승률':>8}{'OOS승률':>8}{'연거래':>7}")
    span=(data['BTCUSDT'][3][-1]-data['BTCUSDT'][3][0])/DAY
    for c in C_LIST:
        pool=[]
        for s in SYMS:
            Hi,Lo,C,ts,z,dst,dg=data[s]
            for et,w in trades(Hi,Lo,C,ts,z,dst,dg,c): pool.append((et<mids[s],w))
        n=len(pool)
        if n==0: print(f"{c*100:>5.1f}%  거래없음"); continue
        pw=sum(1 for _,w in pool if w)/n
        isn=[w for t,w in pool if t]; on=[w for t,w in pool if not t]
        isr=sum(isn)/len(isn) if isn else 0; osr=sum(on)/len(on) if on else 0
        zz=(pw-0.5)/math.sqrt(0.25/n)
        print(f"{c*100:>5.1f}%{n:>6}{pw*100:>7.1f}%{zz:>+6.2f}{((2*pw-1)*c-FEE)*100:>+8.3f}%{isr*100:>7.1f}%{osr*100:>7.1f}%{n/4/(span/365):>6.1f}")


if __name__=="__main__":
    main()
