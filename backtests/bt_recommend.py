"""
추천 픽 = 모멘텀 더블극단 (추세 지속 베팅). BTC, 3개월/1년/3년 비교.
일봉 볼린저z(SMA30,hlc3) >=+2 상승 / <=-2 하락.
1분 볼린저z(SMA10080,hlc3) 같은방향 극단(>=+3.48 상승서 LONG / <=-3.48 하락서 SHORT) = 모멘텀.
청산 대칭 ±2%(검증값). 쿨다운60, 중복허용. net=테이커0.11%.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=10080; KM=3.48; KD=2.0; COOLDOWN=60; C=0.02; FEE=0.0011
SYM="BTCUSDT"

def load():
    d=fetch_klines_bybit(SYM,"D",days=1095)
    H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
    ds=pd.Series((H+L+Cc)/3); dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dst=[x['start'] for x in d]; dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(dz[i]):
            if dz[i]>=KD: dg[i]=+1
            elif dz[i]<=-KD: dg[i]=-1
    m=fetch_klines_bybit(SYM,"1",days=1095)
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
            trig=(g==1 and v>=KM) or (g==-1 and v<=-KM)   # 같은방향 극단=모멘텀
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
    Hi,Lo,Cl,ts,z,dst,dg=load()
    print(f"추천픽: 모멘텀 더블극단 — {SYM}, 청산 대칭 ±{C*100:.0f}%, 쿨다운{COOLDOWN}분, net=테이커{FEE*100:.2f}%")
    print(f"(일봉볼린저z>=±2 + 1분볼린저z(SMA{MWIN})>=±{KM} 같은방향 → 지속 베팅)\n")
    print(f"{'기간':>8}{'거래수':>7}{'L/S':>9}{'승률':>8}{'net/거래':>10}{'IS':>7}{'OOS':>7}{'기간환산':>10}")
    for label,days in [("3개월",90),("1년",365),("3년",1095)]:
        start=int(np.searchsorted(ts, ts[-1]-days*DAY))
        tr=run(Hi,Lo,Cl,ts,z,dst,dg,start)
        n=len(tr)
        if n==0: print(f"{label:>8}{0:>7}  거래없음"); continue
        wins=[r>0 for _,_,r in tr]; wr=sum(wins)/n
        nL=sum(1 for _,g,_ in tr if g==1); net=(2*wr-1)*C-FEE
        span=(ts[-1]-ts[start])/DAY
        mid=ts[start]+(ts[-1]-ts[start])//2
        isn=[r>0 for t,_,r in tr if t<mid]; on=[r>0 for t,_,r in tr if t>=mid]
        isr=sum(isn)/len(isn)*100 if isn else float('nan'); osr=sum(on)/len(on)*100 if on else float('nan')
        print(f"{label:>8}{n:>7}{nL:>5}/{n-nL:<3}{wr*100:>7.1f}%{net*100:>+9.3f}%{isr:>6.1f}%{osr:>6.1f}%{n/(span/90):>7.1f}/3개월")

if __name__=="__main__":
    main()
