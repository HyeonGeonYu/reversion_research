"""
눌림목 TP/SL 그리드 — 고정%SL × (z회복 or %)TP, 6h 타임스톱. BTC 최근 3개월.
진입 동일: 일봉 볼린저z>=2 AND RSI15>60(상승)/거울, 1분 SMA240 ±2σ 눌림, 쿨다운60, 중복허용.
SL=고정%(진입가 기준), TP z타입=1분 z가 목표 회복 / %타입=고정%. 한 봉서 SL/TP 동시면 SL 우선(보수).
실현손익. net_tk=수수료 0.11%, net_mk=0.04%(상하한 bound). n=진입수(전부 동일).
"""
from __future__ import annotations
import sys, os, bisect
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
SYM="BTCUSDT"; SCAN_DAYS=90; COOLDOWN=60; TIMEOUT=360   # 6시간
FEE_TK=0.0011; FEE_MK=0.0004
SL_LIST=[0.004,0.006,0.008,0.010]
TP_LIST=[('z',0.5),('z',1.0),('pct',0.010),('pct',0.015)]

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
    s=pd.Series((Hi+Lo+C)/3); z=((s-s.rolling(MWIN).mean())/s.rolling(MWIN).std(ddof=0)).to_numpy()
    return Hi,Lo,C,ts,z,dst,dg

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

def simulate(Hi,Lo,C,z,ents,sl,tp):
    n=len(C); rets=[]; ex={'TP':0,'SL':0,'TO':0}; holds=[]
    typ,par=tp
    for i,g in ents:
        P0=C[i]; long=(g==1)
        slp=P0*(1-sl) if long else P0*(1+sl)
        tpp=(P0*(1+par) if long else P0*(1-par)) if typ=='pct' else None
        r=None; kind=None; k=i+1
        while k<n:
            if k-i>TIMEOUT:
                r=(C[k]-P0)/P0 if long else (P0-C[k])/P0; kind='TO'; break
            if long:
                if Lo[k]<=slp: r=-sl; kind='SL'; break
                if typ=='z':
                    if z[k]>=par: r=(C[k]-P0)/P0; kind='TP'; break
                else:
                    if Hi[k]>=tpp: r=par; kind='TP'; break
            else:
                if Hi[k]>=slp: r=-sl; kind='SL'; break
                if typ=='z':
                    if z[k]<=-par: r=(P0-C[k])/P0; kind='TP'; break
                else:
                    if Lo[k]<=tpp: r=par; kind='TP'; break
            k+=1
        if r is None:  # 데이터끝
            r=(C[-1]-P0)/P0 if long else (P0-C[-1])/P0; kind='TO'
        rets.append(r); ex[kind]+=1; holds.append(k-i)
    return np.array(rets), ex, np.mean(holds)

def main():
    Hi,Lo,C,ts,z,dst,dg=load()
    start=int(np.searchsorted(ts, ts[-1]-SCAN_DAYS*DAY))
    days=(ts[-1]-ts[start])/DAY
    ents=entries(C,ts,z,dst,dg,start)
    nL=sum(1 for _,g in ents if g==1); nS=len(ents)-nL
    print(f"눌림목 TP/SL 그리드 — {SYM} 최근 {days:.0f}일, 진입 {len(ents)}건(L{nL}/S{nS}), 쿨다운{COOLDOWN}분, 타임스톱{TIMEOUT//60}h")
    print(f"SL=고정%, TP z=평균너머 회복 / %=고정. net_tk(0.11%) net_mk(0.04%)\n")
    for tp in TP_LIST:
        lab=f"z->{tp[1]:.1f}" if tp[0]=='z' else f"+{tp[1]*100:.1f}%"
        print(f"=== TP={lab} ===")
        print(f"{'SL%':>5}{'승률':>8}{'평균익':>8}{'평균손':>8}{'gross':>9}{'net_tk':>9}{'net_mk':>9}{'TP/SL/TO':>11}{'보유':>7}")
        for sl in SL_LIST:
            r,ex,hold=simulate(Hi,Lo,C,z,ents,sl,tp)
            win=(r>0); wr=win.mean()
            aw=r[win].mean()*100 if win.any() else 0; al=r[~win].mean()*100 if (~win).any() else 0
            g=r.mean()*100
            print(f"{sl*100:>4.1f}%{wr*100:>7.1f}%{aw:>+7.2f}%{al:>+7.2f}%{g:>+8.3f}%{g-FEE_TK*100:>+8.3f}%{g-FEE_MK*100:>+8.3f}%{ex['TP']:>4}/{ex['SL']}/{ex['TO']:<3}{hold:>5.0f}분")
        print()

if __name__=="__main__":
    main()
