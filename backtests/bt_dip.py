"""
추세 눌림목 매매 — 강한 추세에서 1분 반대극단(눌림/되돌림) 진입. 4심볼+풀링, 3년.

게이트(일봉, 전일확정):
  롱(상승추세)  = 볼린저 z>=+2 AND RSI(15) > 70
  숏(하락추세)  = 볼린저 z<=-2 AND RSI(15) < 30   (거울)
트리거(1분, SMA10080±3.48σ, hlc3):
  상승추세面 1분 과매도(z<=-3.48) → 매수 (눌림목)
  하락추세면 1분 과매수(z>=+3.48) → 매도 (되돌림)
청산: ±c 무제한보유.  볼린저=hlc3, RSI=종가.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; FEE=0.0011; WIN=10080; RSI_P=15; RSI_HI=60; RSI_LO=40
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
C_LIST=[0.005,0.01,0.02,0.03]


def rsi(close, p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()


def load(sym):
    d=fetch_klines_bybit(sym,"D",days=1095)
    Cc=np.array([x['close'] for x in d])
    dr=rsi(Cc,RSI_P)
    dst=[x['start'] for x in d]
    dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(dr[i]):
            if dr[i]>RSI_HI: dg[i]=+1     # 상승추세(RSI>60)
            elif dr[i]<RSI_LO: dg[i]=-1   # 하락추세(RSI<40)
    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+C)/3); z=((s-s.rolling(WIN).mean())/s.rolling(WIN).std(ddof=0)).to_numpy()
    return Hi,Lo,C,ts,z,dst,dg


def trades(Hi,Lo,C,ts,z,dst,dg,c,km):
    n=len(C); out=[]; i=WIN; armed=True
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0:
            trig = (g==1 and v<=-km) or (g==-1 and v>=km)   # 추세속 1분 되돌림(눌림)
            if trig:
                longside=(g==1); P0=C[i]
                if longside: tp=P0*(1+c); sl=P0*(1-c)
                else:        tp=P0*(1-c); sl=P0*(1+c)
                res=None; xi=None; k=i+1
                while k<n:
                    if longside: ht=Hi[k]>=tp; hs=Lo[k]<=sl
                    else:        ht=Lo[k]<=tp; hs=Hi[k]>=sl
                    if ht and hs: res=-1;xi=k;break
                    if ht: res=1;xi=k;break
                    if hs: res=-1;xi=k;break
                    k+=1
                if res is None: break
                out.append((int(ts[i]),res>0)); armed=False; i=xi; continue
        if abs(v)<km: armed=True
        i+=1
    return out


def main():
    data={s:load(s) for s in SYMS}
    mids={s:data[s][3][len(data[s][3])//2] for s in SYMS}
    c=0.01
    print(f"추세 눌림목 (일봉 RSI{RSI_P}>{RSI_HI}/<{RSI_LO} 추세 + 1분 눌림 km), c={c*100:.0f}%, 4심볼 3년, 수수료 {FEE*100:.2f}%")
    print("(1분 눌림 깊이 km 스윕 — 얕을수록 자주)\n")
    print(f"{'km(σ)':>6}{'풀n':>6}{'승률':>8}{'z':>7}{'net':>9}{'IS':>7}{'OOS':>7}")
    for km in [0.5,1.0,1.5,2.0,2.5]:
        pool=[]
        for s in SYMS:
            Hi,Lo,C,ts,z,dst,dg=data[s]
            for et,w in trades(Hi,Lo,C,ts,z,dst,dg,c,km): pool.append((et<mids[s],w))
        n=len(pool)
        if n==0: print(f"{km:>5.1f}  거래없음"); continue
        pw=sum(1 for _,w in pool if w)/n
        isn=[w for t,w in pool if t]; on=[w for t,w in pool if not t]
        isr=sum(isn)/len(isn) if isn else 0; osr=sum(on)/len(on) if on else 0
        zz=(pw-0.5)/math.sqrt(0.25/n)
        print(f"{km:>5.1f}{n:>6}{pw*100:>7.1f}%{zz:>+6.2f}{((2*pw-1)*c-FEE)*100:>+8.3f}%{isr*100:>6.1f}%{osr*100:>6.1f}%")


if __name__=="__main__":
    main()
