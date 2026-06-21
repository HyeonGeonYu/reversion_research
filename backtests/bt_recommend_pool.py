"""
추천픽 확정 — 모멘텀 더블극단, 4심볼 풀링(BTC/ETH/SOL/XRP), 1년+3년.
일봉 볼린저z(SMA30)>=±2 + 1분 볼린저z(SMA10080)>=±3.48 같은방향 → 지속 베팅. 청산 대칭±2%.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=10080; KM=3.48; KD=2.0; COOLDOWN=60; C=0.02; FEE=0.0011
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]

def load(sym):
    d=fetch_klines_bybit(sym,"D",days=1095)
    H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
    ds=pd.Series((H+L+Cc)/3); dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dst=[x['start'] for x in d]; dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(dz[i]):
            if dz[i]>=KD: dg[i]=+1
            elif dz[i]<=-KD: dg[i]=-1
    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);Cl=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+Cl)/3); z=((s-s.rolling(MWIN).mean())/s.rolling(MWIN).std(ddof=0)).to_numpy()
    return Hi,Lo,Cl,ts,z,dst,dg

def run(Hi,Lo,Cl,ts,z,dst,dg,start):
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    n=len(Cl); out=[]; i=max(MWIN,start); armed=True; last=-10**9
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0 and (i-last)>=COOLDOWN:
            trig=(g==1 and v>=KM) or (g==-1 and v<=-KM)
            if trig:
                long=(g==1); P0=Cl[i]
                tp=P0*(1+C) if long else P0*(1-C); sl=P0*(1-C) if long else P0*(1+C)
                r=None;k=i+1
                while k<n:
                    if long:
                        if Lo[k]<=sl: r=-C;break
                        if Hi[k]>=tp: r=+C;break
                    else:
                        if Hi[k]>=sl: r=-C;break
                        if Lo[k]<=tp: r=+C;break
                    k+=1
                if r is not None: out.append((int(ts[i]),g,r))
                last=i; armed=False
        if abs(v)<KM: armed=True
        i+=1
    return out

def main():
    data={s:load(s) for s in SYMS}
    print(f"추천픽 확정 — 모멘텀 더블극단, 4심볼 풀링, 청산 대칭±{C*100:.0f}%, net=테이커{FEE*100:.2f}%\n")
    for label,days in [("1년",365),("3년",1095)]:
        pool=[]; per={}
        for s in SYMS:
            Hi,Lo,Cl,ts,z,dst,dg=data[s]
            start=int(np.searchsorted(ts, ts[-1]-days*DAY)); mid=ts[start]+(ts[-1]-ts[start])//2
            tr=run(Hi,Lo,Cl,ts,z,dst,dg,start)
            per[s]=(len(tr), sum(1 for _,_,r in tr if r>0)/len(tr) if tr else 0)
            for t,g,r in tr: pool.append((t<mid,g,r>0))
        n=len(pool)
        if n==0: print(f"[{label}] 거래없음"); continue
        wr=sum(1 for _,_,w in pool if w)/n
        nL=sum(1 for _,g,_ in pool if g==1)
        isn=[w for t,_,w in pool if t]; on=[w for t,_,w in pool if not t]
        isr=sum(isn)/len(isn)*100 if isn else float('nan'); osr=sum(on)/len(on)*100 if on else float('nan')
        zz=(wr-0.5)/math.sqrt(0.25/n); net=(2*wr-1)*C-FEE
        print(f"[{label} 풀링] n={n} (L{nL}/S{n-nL})  승률 {wr*100:.1f}%  z={zz:+.2f}  net {net*100:+.3f}%/거래  IS {isr:.1f}% / OOS {osr:.1f}%")
        if label=="1년":
            for s in SYMS:
                cnt,w=per[s]; print(f"     - {s:8} n{cnt:>3}  승률 {w*100:5.1f}%")
        print()

if __name__=="__main__":
    main()
