"""
숏온리 + 느슨화 — 모멘텀 더블극단의 숏 다리만, 임계값(일봉z, 1분z) 낮춰 빈도↑.
일봉 z<=-KD (하락) + 1분 z<=-KM 같은방향 → SHORT(지속). 청산 대칭±2%. 4심볼 풀링.
느슨 스윕(totals) + 선택 설정 분기별.
"""
from __future__ import annotations
import sys, os, bisect
import numpy as np, pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=10080; COOLDOWN=60; C=0.02; FEE=0.0011
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]

def load(sym):
    d=fetch_klines_bybit(sym,"D",days=1095)
    H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
    ds=pd.Series((H+L+Cc)/3); dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dst=np.array([x['start'] for x in d])
    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);Cl=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+Cl)/3); z=((s-s.rolling(MWIN).mean())/s.rolling(MWIN).std(ddof=0)).to_numpy()
    return Hi,Lo,Cl,ts,z,dst,dz

def run_short(Hi,Lo,Cl,ts,z,dst,dz,KD,KM):
    def gz(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dz[j] if j>=0 else np.nan
    n=len(Cl); out=[]; i=MWIN; armed=True; last=-10**9
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gz(ts[i])
        if armed and (i-last)>=COOLDOWN and np.isfinite(g) and g<=-KD and v<=-KM:
            P0=Cl[i]; tp=P0*(1-C); sl=P0*(1+C); r=None; k=i+1
            while k<n:
                if Hi[k]>=sl: r=-C;break
                if Lo[k]<=tp: r=+C;break
                k+=1
            if r is not None: out.append((int(ts[i]),r))
            last=i; armed=False
        if v>-KM: armed=True
        i+=1
    return out

def q_of(ms):
    dt=datetime.utcfromtimestamp(ms/1000)+timedelta(hours=9); return f"{dt.year}-Q{(dt.month-1)//3+1}"

def main():
    data={s:load(s) for s in SYMS}
    print(f"숏온리 느슨 스윕 — 4심볼 풀링 3년, 청산 대칭±{C*100:.0f}%, net=테이커{FEE*100:.2f}%\n")
    print(f"{'일봉z':>6}{'1분z':>7}{'n':>6}{'승률':>8}{'net/거래':>10}{'IS':>7}{'OOS':>7}{'분기빈도':>9}")
    configs=[(2.0,3.48),(2.0,3.0),(2.0,2.5),(1.5,3.48),(1.5,3.0),(1.5,2.5)]
    results={}
    for KD,KM in configs:
        pool=[]
        for s in SYMS:
            for t,r in run_short(*data[s],KD,KM): pool.append((t,r))
        pool.sort(); results[(KD,KM)]=pool
        n=len(pool);
        if n==0: print(f"{-KD:>5.1f}{-KM:>7.2f}  거래없음"); continue
        wr=sum(1 for _,r in pool if r>0)/n; mid=pool[n//2][0]
        isn=[r>0 for t,r in pool if t<mid]; on=[r>0 for t,r in pool if t>=mid]
        isr=sum(isn)/len(isn)*100; osr=sum(on)/len(on)*100; net=(2*wr-1)*C-FEE
        print(f"{-KD:>5.1f}{-KM:>7.2f}{n:>6}{wr*100:>7.1f}%{net*100:>+9.3f}%{isr:>6.1f}%{osr:>6.1f}%{n/12:>8.1f}")
    # 분기별: 기준 + 느슨 2개
    for KD,KM in [(2.0,3.48),(2.0,3.0),(1.5,3.0)]:
        pool=results[(KD,KM)]
        by=defaultdict(list)
        for t,r in pool: by[q_of(t)].append(r)
        print(f"\n[분기별 숏온리 — 일봉z<=-{KD} / 1분z<=-{KM}]  (총 {len(pool)}건)")
        print(f"{'분기':>9}{'n':>5}{'승률':>8}{'net/거래':>10}")
        for q in sorted(by):
            rr=by[q]; nn=len(rr); wr=sum(1 for r in rr if r>0)/nn; net=(2*wr-1)*C-FEE
            print(f"{q:>9}{nn:>5}{wr*100:>7.1f}%{net*100:>+9.3f}%")

if __name__=="__main__":
    main()
