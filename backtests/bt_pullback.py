"""
추세 눌림목 — 일봉 추세 + 1분 단기눌림(SMA240,4h). 4심볼 풀링 3년. 청산 ±c 스윕.

추세(일봉, 전일확정): 볼린저 z>=+2 AND RSI(15)>60 → 상승 / z<=-2 AND RSI(15)<40 → 하락.
눌림(1분, SMA240 ±2σ, hlc3): 상승추세+1분 z<=-2(눌림) → 매수 / 하락추세+1분 z>=+2(되돌림) → 매도.
청산: ±c (이익+c / 손해-c) 무제한보유. c 스윕.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; FEE=0.0011; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
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
    s=pd.Series((Hi+Lo+C)/3); z=((s-s.rolling(MWIN).mean())/s.rolling(MWIN).std(ddof=0)).to_numpy()
    return Hi,Lo,C,ts,z,dst,dg


def trades(Hi,Lo,C,ts,z,dst,dg,c,cooldown):
    """중복진입 허용(청산 안 기다림) + 쿨다운(분). 각 거래는 독립적으로 ±c 결판."""
    n=len(C); out=[]; i=MWIN; armed=True; last=-10**9
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0 and (i-last)>=cooldown:
            trig=(g==1 and v<=-KMIN) or (g==-1 and v>=KMIN)
            if trig:
                longside=(g==1); P0=C[i]
                if longside: tp=P0*(1+c); sl=P0*(1-c)
                else:        tp=P0*(1-c); sl=P0*(1+c)
                res=None;k=i+1
                while k<n:
                    if longside: ht=Hi[k]>=tp; hs=Lo[k]<=sl
                    else:        ht=Lo[k]<=tp; hs=Hi[k]>=sl
                    if ht and hs: res=-1;break
                    if ht: res=1;break
                    if hs: res=-1;break
                    k+=1
                if res is not None:                 # 끝까지 미결판이면 제외
                    out.append((int(ts[i]),res>0))
                last=i; armed=False                  # i는 그대로 +1 (중복 허용)
        if abs(v)<KMIN: armed=True
        i+=1
    return out


def stat(pool,c,n_sym,years):
    n=len(pool)
    if n==0: return None
    pw=sum(1 for _,w in pool if w)/n
    isn=[w for t,w in pool if t]; on=[w for t,w in pool if not t]
    isr=sum(isn)/len(isn) if isn else 0; osr=sum(on)/len(on) if on else 0
    zz=(pw-0.5)/math.sqrt(0.25/n)
    net=((2*pw-1)*c-FEE)*100
    return n,pw,zz,net,isr,osr,n/n_sym/years


def main():
    data={s:load(s) for s in SYMS}
    mids={s:data[s][3][len(data[s][3])//2] for s in SYMS}
    years=(data['BTCUSDT'][3][-1]-data['BTCUSDT'][3][0])/DAY/365
    print(f"추세 눌림목 [중복진입 허용 + 쿨다운] (일봉 볼린저z≥2 AND RSI{RSI_P}>{RSI_HI} + 1분 SMA{MWIN} ±{KMIN:.0f}σ 눌림), 4심볼 3년, 수수료 {FEE*100:.2f}%\n")

    # === Part1: 쿨다운 스윕 (c=2% 고정) — 거래수 vs 승률 ===
    print(f"[쿨다운 스윕, c=2% 고정]")
    print(f"{'쿨다운':>7}{'풀n':>7}{'승률':>8}{'z':>7}{'net':>9}{'IS':>7}{'OOS':>7}{'연거래/심볼':>11}")
    for cd in [15,30,60,120,240,480]:
        pool=[]
        for s in SYMS:
            Hi,Lo,C,ts,z,dst,dg=data[s]
            for et,w in trades(Hi,Lo,C,ts,z,dst,dg,0.02,cd): pool.append((et<mids[s],w))
        r=stat(pool,0.02,len(SYMS),years)
        if r: n,pw,zz,net,isr,osr,yr=r; print(f"{cd:>5}분{n:>7}{pw*100:>7.1f}%{zz:>+6.2f}{net:>+8.3f}%{isr*100:>6.1f}%{osr*100:>6.1f}%{yr:>9.1f}")

    # === Part2: c 스윕 (쿨다운=60분 고정) ===
    CD=60
    print(f"\n[c 스윕, 쿨다운={CD}분 고정]")
    print(f"{'c':>6}{'풀n':>7}{'승률':>8}{'z':>7}{'net':>9}{'IS':>7}{'OOS':>7}{'연거래/심볼':>11}")
    for c in C_LIST:
        pool=[]
        for s in SYMS:
            Hi,Lo,C,ts,z,dst,dg=data[s]
            for et,w in trades(Hi,Lo,C,ts,z,dst,dg,c,CD): pool.append((et<mids[s],w))
        r=stat(pool,c,len(SYMS),years)
        if r: n,pw,zz,net,isr,osr,yr=r; print(f"{c*100:>5.1f}%{n:>7}{pw*100:>7.1f}%{zz:>+6.2f}{net:>+8.3f}%{isr*100:>6.1f}%{osr*100:>6.1f}%{yr:>9.1f}")

    # === BTC 심볼별 (c=2%, 쿨다운=60) 3개월 환산 ===
    print(f"\n[심볼별 c=2% 쿨다운={CD}분]")
    for s in SYMS:
        Hi,Lo,C,ts,z,dst,dg=data[s]; tr=trades(Hi,Lo,C,ts,z,dst,dg,0.02,CD)
        n=len(tr); w=sum(1 for _,x in tr if x)/n if n else 0
        print(f"  {s:8} n{n:>5} 승률 {w*100:5.1f}%  3개월 {n/(years*4):.1f}회")


if __name__=="__main__":
    main()
