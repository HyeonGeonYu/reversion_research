"""
눌림목 z-기반 TP — 진입: 1분 SMA240 볼린저 z<=-2(상승추세 눌림)/z>=+2(하락추세 되돌림).
TP: 1분 z가 목표 {0, 0.5, 1}로 회귀하면 청산.
SL: z-공간 대칭 미러 (진입z0에서 TP까지 거리만큼 반대로) -> long SL z=2*z0-T, short SL z=2*z0+T.
청산이 z-기반이라 P&L%가 가변 -> 실현손익으로 측정. BTC만, 최근 3개월(1분 스캔), 중복진입+쿨다운.
일봉 게이트는 전체기간으로 워밍업(볼린저z>=2 AND RSI15>60 상승 / z<=-2 AND RSI<40 하락).
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; FEE=0.0011; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40
SYM="BTCUSDT"; SCAN_DAYS=90; COOLDOWN=60
TP_LIST=[-1.5,-1.0,-0.5,0.0]


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


def run(C,ts,z,dst,dg,T,cd,start):
    """실현손익 리스트 반환 + 타임아웃수. 진입z0 기준 TP/SL을 z로 판정, P&L은 종가로."""
    n=len(C); i=max(MWIN,start); armed=True; last=-10**9; out=[]; tmo=0
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        g=gate(ts[i])
        if armed and g!=0 and (i-last)>=cd:
            trig=(g==1 and v<=-KMIN) or (g==-1 and v>=KMIN)
            if trig:
                z0=v; longside=(g==1); P0=C[i]
                if longside: tpz=T;  slz=2*z0-T
                else:        tpz=-T; slz=2*z0+T
                res=None; k=i+1
                while k<n:
                    zz=z[k]
                    if np.isfinite(zz):
                        if longside:
                            if zz>=tpz or zz<=slz: res=(C[k]-P0)/P0; break
                        else:
                            if zz<=tpz or zz>=slz: res=(P0-C[k])/P0; break
                    k+=1
                if res is None: tmo+=1
                else: out.append((res,k-i))
                last=i; armed=False
        if abs(v)<KMIN: armed=True
        i+=1
    return out,tmo


def main():
    Hi,Lo,C,ts,z,dst,dg=load()
    start=int(np.searchsorted(ts, ts[-1]-SCAN_DAYS*DAY))
    days=(ts[-1]-ts[start])/DAY
    print(f"눌림목 z-기반 TP — {SYM} 최근 {days:.0f}일, 진입 1분 SMA{MWIN} ±{KMIN:.0f}σ, 쿨다운 {COOLDOWN}분, 수수료 {FEE*100:.2f}%")
    print(f"TP=z회귀목표, SL=z대칭미러. 실현손익 기준.\n")
    print(f"{'TP(z)':>6}{'n':>5}{'승률':>8}{'평균익':>8}{'평균손':>8}{'평균손익':>9}{'net/거래':>10}{'타임아웃':>8}{'평균보유':>9}")
    for T in TP_LIST:
        out,tmo=run(C,ts,z,dst,dg,T,COOLDOWN,start)
        n=len(out)
        if n==0: print(f"{T:>5.1f}  거래없음 (타임아웃 {tmo})"); continue
        rets=np.array([r for r,_ in out]); holds=np.array([h for _,h in out])
        win=(rets>0)
        wr=win.mean()
        aw=rets[win].mean()*100 if win.any() else 0
        al=rets[~win].mean()*100 if (~win).any() else 0
        mr=rets.mean()*100
        net=mr-FEE*100
        print(f"{T:>5.1f}{n:>5}{wr*100:>7.1f}%{aw:>+7.2f}%{al:>+7.2f}%{mr:>+8.3f}%{net:>+9.3f}%{tmo:>8}{holds.mean():>7.0f}분")


if __name__=="__main__":
    main()
