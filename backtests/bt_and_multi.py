"""
AND게이트 + ±c 추세(momentum) — 4심볼 + 풀링, 3년, IS/OOS.

진입: 일봉SMA30±2σ(전일 게이트) AND 1분SMA10080±3.48σ, 같은방향, hlc3.
방향: 과매도극단→숏 / 과매수극단→롱 (추세추종). 청산 ±c 무제한보유.
"""
from __future__ import annotations
import sys, os, bisect, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; FEE=0.0011; WIN=10080; KM=3.48; KD=2.0
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
C_LIST=[0.01,0.02,0.03]


def hlc3(r):
    H=np.array([x['high'] for x in r]);L=np.array([x['low'] for x in r]);C=np.array([x['close'] for x in r]); return (H+L+C)/3


def load(sym):
    d=fetch_klines_bybit(sym,"D",days=1095); ds=pd.Series(hlc3(d))
    dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dst=[x['start'] for x in d]
    dg=[ (-1 if dz[i]<=-KD else (1 if dz[i]>=KD else 0)) if np.isfinite(dz[i]) else 0 for i in range(len(d)) ]
    m=fetch_klines_bybit(sym,"1",days=1095)
    Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
    s=pd.Series((Hi+Lo+C)/3); z=((s-s.rolling(WIN).mean())/s.rolling(WIN).std(ddof=0)).to_numpy()
    return Hi,Lo,C,ts,z,dst,dg


def trades(Hi,Lo,C,ts,z,dst,dg,c):
    n=len(C); out=[]; i=WIN; armed=True
    def gate(t):
        j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0
    while i<n:
        v=z[i]
        if not np.isfinite(v): i+=1; continue
        if armed and abs(v)>=KM:
            mdir=-1 if v<=-KM else 1
            if gate(ts[i])==mdir:
                longside=(mdir==1)   # momentum: 과매수극단→롱
                P0=C[i]
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
                out.append((int(ts[i]), res>0)); armed=False; i=xi; continue
        if abs(v)<KM: armed=True
        i+=1
    return out


def wr(tr):
    n=len(tr); return (n, sum(1 for _,w in tr if w)/n if n else 0)


def main():
    data={s:load(s) for s in SYMS}
    mids={s: data[s][3][len(data[s][3])//2] for s in SYMS}
    print(f"AND게이트 + ±c 추세(momentum), 4심볼 3년, 수수료 {FEE*100:.2f}%\n")
    for c in C_LIST:
        print(f"==== c={c*100:.0f}% ====")
        pool=[]
        for s in SYMS:
            Hi,Lo,C,ts,z,dst,dg=data[s]
            tr=trades(Hi,Lo,C,ts,z,dst,dg,c)
            for et,w in tr: pool.append((et < mids[s], w))   # (IS?, win)
            n,w=wr(tr)
            print(f"  {s:8} n{n:>4} 승률 {w*100:5.1f}%  net {((2*w-1)*c-FEE)*100:+.3f}%")
        n=len(pool); pw=sum(1 for _,w in pool if w)/n if n else 0
        isn=[w for t,w in pool if t]; on=[w for t,w in pool if not t]
        isr=sum(isn)/len(isn) if isn else 0; osr=sum(on)/len(on) if on else 0
        z_=(pw-0.5)/math.sqrt(0.25/n) if n else 0
        print(f"  {'POOL':8} n{n:>4} 승률 {pw*100:5.1f}% (z{z_:+.2f})  net {((2*pw-1)*c-FEE)*100:+.3f}%  | IS {isr*100:.1f}%(n{len(isn)}) OOS {osr*100:.1f}%(n{len(on)})")
        print()


if __name__ == "__main__":
    main()
