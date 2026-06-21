"""
밴드 복귀(바운스) 눌림목 — BTC 3개월.
롱: 일봉 종가>SMA30 AND RSI(15)>60 + 1분 하단2σ 터치/이탈 후 '밴드 안 복귀' 시 진입.
숏: 일봉 종가<SMA30 AND RSI(15)<40 + 1분 상단2σ 터치/이탈 후 '밴드 안 복귀' 시 진입.
TP=1분 평균(SMA240) 복귀.  SL=이탈 구간 최저(롱)/최고(숏) = 구조적 스탑.  타임스톱 48h.
밴드=hlc3 SMA240±2σ. 일봉 SMA30=종가. 한 봉서 SL/TP 동시면 SL 우선(보수).
"""
from __future__ import annotations
import sys, os, bisect
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=240; KMIN=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
SYM="BTCUSDT"; SCAN_DAYS=90; TIMEOUT=2880
FEE_TK=0.0011; FEE_MK=0.0004

def rsi(close,p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()

def load():
    d=fetch_klines_bybit(SYM,"D",days=1095)
    Cc=np.array([x['close'] for x in d])
    sma30=pd.Series(Cc).rolling(30).mean().to_numpy(); dr=rsi(Cc,RSI_P)
    dst=[x['start'] for x in d]; dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(sma30[i]) and np.isfinite(dr[i]):
            if Cc[i]>sma30[i] and dr[i]>RSI_HI: dg[i]=+1
            elif Cc[i]<sma30[i] and dr[i]<RSI_LO: dg[i]=-1
    m=fetch_klines_bybit(SYM,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+C)/3); mid=s.rolling(MWIN).mean(); sd=s.rolling(MWIN).std(ddof=0)
    lower=(mid-KMIN*sd).to_numpy(); upper=(mid+KMIN*sd).to_numpy(); mid=mid.to_numpy()
    return Hi,Lo,C,ts,mid,lower,upper,dst,dg

def find_entries(Hi,Lo,C,ts,mid,lower,upper,dst,dg,start):
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    n=len(C); out=[]; in_exc=0; ext=None
    for k in range(max(MWIN,start),n):
        if not np.isfinite(lower[k]): continue
        g=gate(ts[k])
        if in_exc==0:
            if g==1 and Lo[k]<=lower[k]: in_exc=1; ext=Lo[k]
            elif g==-1 and Hi[k]>=upper[k]: in_exc=-1; ext=Hi[k]
        elif in_exc==1:
            ext=min(ext,Lo[k])
            if C[k]>lower[k]:                       # 하단밴드 안으로 복귀
                if gate(ts[k])==1: out.append((k,1,ext))
                in_exc=0
        elif in_exc==-1:
            ext=max(ext,Hi[k])
            if C[k]<upper[k]:                       # 상단밴드 안으로 복귀
                if gate(ts[k])==-1: out.append((k,-1,ext))
                in_exc=0
    return out

def simulate(Hi,Lo,C,mid,ents):
    n=len(C); rows=[]
    for k0,side,slp in ents:
        P0=C[k0]; long=(side==1); k=k0+1; r=None; kind=None
        while k<n:
            if k-k0>TIMEOUT:
                r=(C[k]-P0)/P0 if long else (P0-C[k])/P0; kind='TO'; break
            if long:
                if Lo[k]<=slp: r=(slp-P0)/P0; kind='SL'; break
                if Hi[k]>=mid[k]: r=(mid[k]-P0)/P0; kind='TP'; break
            else:
                if Hi[k]>=slp: r=(P0-slp)/P0; kind='SL'; break
                if Lo[k]<=mid[k]: r=(P0-mid[k])/P0; kind='TP'; break
            k+=1
        if r is None:
            r=(C[-1]-P0)/P0 if long else (P0-C[-1])/P0; kind='TO'
        rows.append((side,r,k-k0,kind))
    return rows

def main():
    Hi,Lo,C,ts,mid,lower,upper,dst,dg=load()
    start=int(np.searchsorted(ts, ts[-1]-SCAN_DAYS*DAY)); days=(ts[-1]-ts[start])/DAY
    ents=find_entries(Hi,Lo,C,ts,mid,lower,upper,dst,dg,start)
    rows=simulate(Hi,Lo,C,mid,ents)
    if not rows: print("거래 없음"); return
    side=np.array([x[0] for x in rows]); r=np.array([x[1] for x in rows]); hold=np.array([x[2] for x in rows])
    kinds=[x[3] for x in rows]
    nL=(side==1).sum(); nS=(side==-1).sum()
    win=(r>0); wr=win.mean()
    aw=r[win].mean()*100 if win.any() else 0; al=r[~win].mean()*100 if (~win).any() else 0
    g=r.mean()*100
    tp=kinds.count('TP'); sl=kinds.count('SL'); to=kinds.count('TO')
    print(f"밴드 복귀 바운스 — {SYM} 최근 {days:.0f}일\n")
    print(f"  거래수    : {len(rows)}건  (롱 {nL} / 숏 {nS})")
    print(f"  승률      : {wr*100:.1f}%")
    print(f"  평균익/손 : +{aw:.2f}% / {al:.2f}%   (손익비 {abs(aw/al):.2f})" if al!=0 else "")
    print(f"  gross     : {g:+.3f}%/거래")
    print(f"  net 테이커: {g-FEE_TK*100:+.3f}%   net 메이커: {g-FEE_MK*100:+.3f}%")
    print(f"  청산내역  : TP {tp} / SL {sl} / 타임아웃 {to}")
    print(f"  평균보유  : {hold.mean():.0f}분 (중앙값 {np.median(hold):.0f}분)")
    print(f"  3개월 환산: {len(rows)/(days/90):.0f}건")
    # 롱/숏 따로
    for s,nm in [(1,'롱'),(-1,'숏')]:
        msk=side==s
        if msk.sum():
            ww=(r[msk]>0).mean()*100
            print(f"   - {nm}: {msk.sum()}건, 승률 {ww:.1f}%, gross {r[msk].mean()*100:+.3f}%")

if __name__=="__main__":
    main()
