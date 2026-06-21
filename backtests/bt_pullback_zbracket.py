"""
눌림목 z-환산 고정%브래킷 — 진입시 z0에서 목표z(T)까지 회복거리를 그때 밴드폭(σ)으로 %환산,
그 %를 TP/SL 대칭 브래킷으로 고정(라이브z 아님). 목표 T를 스윕. BTC 최근 3개월.
롱: 거리=(T - z0)σ, pct=거리/P0, TP=P0(1+pct) SL=P0(1-pct).  숏 거울: 거리=(z0 + T)σ.
한 봉서 TP/SL 동시면 SL 우선(보수). 실현=±pct. net_tk=0.11% net_mk=0.04%.
진입 동일: 일봉 볼린저z>=2 AND RSI15>60(상승)/거울, 1분 SMA240 ±2σ 눌림, 쿨다운60, 중복허용.
"""
from __future__ import annotations
import sys, os, bisect
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
SYM="BTCUSDT"; SCAN_DAYS=365; COOLDOWN=60; TIMEOUT=2880   # 48h 안전망
FEE_TK=0.0011; FEE_MK=0.0004
T_LIST=[0.0,0.5,1.0,1.5,2.0,2.5]

def rsi(close,p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()

def load():
    d=fetch_klines_bybit(SYM,"D",days=1095)
    H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
    ds=pd.Series((H+L+Cc)/3); dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dr=rsi(Cc,RSI_P); dst=[x['start'] for x in d]; dg=[0]*len(d)
    for i in range(len(d)):
        if np.isfinite(dz[i]) and np.isfinite(dr[i]):
            if dz[i]>=KD and dr[i]>RSI_HI: dg[i]=+1
            elif dz[i]<=-KD and dr[i]<RSI_LO: dg[i]=-1
    m=fetch_klines_bybit(SYM,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+C)/3); sd=s.rolling(MWIN).std(ddof=0); sma=s.rolling(MWIN).mean()
    z=((s-sma)/sd).to_numpy(); sd=sd.to_numpy()
    return Hi,Lo,C,ts,z,sd,dst,dg

def entries(C,ts,z,dst,dg,start):
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    i=max(MWIN,start); armed=True; last=-10**9; out=[]
    while i<len(C):
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0 and (i-last)>=COOLDOWN:
            if (g==1 and v<=-KMIN) or (g==-1 and v>=KMIN):
                out.append((i,g)); last=i; armed=False
        if abs(v)<KMIN: armed=True
        i+=1
    return out

def simulate(Hi,Lo,C,ts,z,sd,ents,T):
    n=len(C); rets=[]; pcts=[]; holds=[]; ets=[]; tmo=0
    for i,g in ents:
        P0=C[i]; sig=sd[i]; long=(g==1); z0=z[i]
        dist=(T-z0) if long else (z0+T)        # σ 단위 회복거리(>0)
        pct=dist*sig/P0
        if pct<=0: continue
        tp=P0*(1+pct) if long else P0*(1-pct); sl=P0*(1-pct) if long else P0*(1+pct)
        r=None; k=i+1
        while k<n:
            if k-i>TIMEOUT:
                r=(C[k]-P0)/P0 if long else (P0-C[k])/P0; tmo+=1; break
            if long:
                if Lo[k]<=sl: r=-pct; break
                if Hi[k]>=tp: r=+pct; break
            else:
                if Hi[k]>=sl: r=-pct; break
                if Lo[k]<=tp: r=+pct; break
            k+=1
        if r is None:
            r=(C[-1]-P0)/P0 if long else (P0-C[-1])/P0; tmo+=1
        rets.append(r); pcts.append(pct); holds.append(k-i); ets.append(int(ts[i]))
    return np.array(rets), np.array(pcts), np.mean(holds), tmo, np.array(ets)

def main():
    Hi,Lo,C,ts,z,sd,dst,dg=load()
    start=int(np.searchsorted(ts, ts[-1]-SCAN_DAYS*DAY))
    days=(ts[-1]-ts[start])/DAY
    ents=entries(C,ts,z,dst,dg,start)
    nL=sum(1 for _,g in ents if g==1)
    mid=ts[start]+(ts[-1]-ts[start])//2
    print(f"눌림목 z-환산 고정%브래킷 — {SYM} 최근 {days:.0f}일, 진입 {len(ents)}건(L{nL}/S{len(ents)-nL}), 쿨다운{COOLDOWN}분")
    print(f"진입z->목표T 회복거리를 진입시 σ로 %고정, TP/SL 대칭. net=테이커0.11%. IS/OOS=상/하반기 net_tk\n")
    print(f"{'목표T':>6}{'평균±%':>9}{'n':>5}{'승률':>8}{'평균익':>8}{'평균손':>8}{'gross':>9}{'net_tk':>9}{'net_mk':>9}{'IS_tk':>8}{'OOS_tk':>8}{'TO':>4}{'보유':>7}")
    for T in T_LIST:
        r,pcts,hold,tmo,ets=simulate(Hi,Lo,C,ts,z,sd,ents,T)
        n=len(r)
        if n==0: print(f"{T:>5.1f}  거래없음"); continue
        win=(r>0); wr=win.mean()
        aw=r[win].mean()*100 if win.any() else 0; al=r[~win].mean()*100 if (~win).any() else 0
        g=r.mean()*100; br=pcts.mean()*100
        ism=ets<mid; isr=(r[ism].mean()*100-FEE_TK*100) if ism.any() else 0
        osr=(r[~ism].mean()*100-FEE_TK*100) if (~ism).any() else 0
        print(f"{T:>5.1f}{br:>+8.3f}%{n:>5}{wr*100:>7.1f}%{aw:>+7.2f}%{al:>+7.2f}%{g:>+8.3f}%{g-FEE_TK*100:>+8.3f}%{g-FEE_MK*100:>+8.3f}%{isr:>+7.3f}%{osr:>+7.3f}%{tmo:>4}{hold:>5.0f}분")

if __name__=="__main__":
    main()
