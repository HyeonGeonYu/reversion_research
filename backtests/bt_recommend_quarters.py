"""
추천픽 분기별 성적 — 모멘텀 더블극단, 4심볼 풀링, 전체 3년. 분기=KST 달력분기.
"""
from __future__ import annotations
import sys, os, bisect
import numpy as np, pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
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

def run(Hi,Lo,Cl,ts,z,dst,dg):
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    n=len(Cl); out=[]; i=MWIN; armed=True; last=-10**9
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0 and (i-last)>=COOLDOWN:
            if (g==1 and v>=KM) or (g==-1 and v<=-KM):
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

def q_of(ms):
    dt=datetime.utcfromtimestamp(ms/1000)+timedelta(hours=9)
    return f"{dt.year}-Q{(dt.month-1)//3+1}"

def main():
    allt=[]
    for s in SYMS:
        allt+= run(*load(s))
    by=defaultdict(list)
    for t,g,r in allt: by[q_of(t)].append((g,r))
    print(f"추천픽 분기별 — 모멘텀 더블극단, 4심볼 풀링, 청산±{C*100:.0f}%, net=테이커{FEE*100:.2f}%\n")
    print(f"{'분기':>9}{'n':>5}{'L/S':>8}{'승률':>8}{'net/거래':>10}{'분기합net':>10}")
    cum=0.0
    for q in sorted(by):
        rows=by[q]; n=len(rows); wr=sum(1 for g,r in rows if r>0)/n
        nL=sum(1 for g,r in rows if g==1); net=(2*wr-1)*C-FEE; tot=net*n; cum+=tot
        print(f"{q:>9}{n:>5}{nL:>4}/{n-nL:<3}{wr*100:>7.1f}%{net*100:>+9.3f}%{tot*100:>+9.2f}%")
    n=len(allt); wr=sum(1 for _,_,r in allt if r>0)/n
    print(f"\n전체 {n}건  승률 {wr*100:.1f}%  net {((2*wr-1)*C-FEE)*100:+.3f}%/거래  누적합 {cum*100:+.1f}%(거래당 명목, 복리·비중 무시)")

if __name__=="__main__":
    main()
