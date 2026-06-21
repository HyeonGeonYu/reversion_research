"""
AND일 1분봉 차트 — 일봉 SMA30±2σ AND 1분 SMA10080±3.48σ (같은방향) 충족일.

각 날(KST 06:50~다음날 06:50)의 1분봉 캔들 + 1분 볼린저(SMA10080±3.48σ, hlc3) 밴드/평균
+ 게이트 방향 극단 마커 (과매도일→매수▲ / 과매수일→매도▼).
"""
from __future__ import annotations
import sys, os, math
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, fig_path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
    try:
        matplotlib.rcParams["font.family"] = _f; break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False

KST = timezone(timedelta(hours=9))
DAY = 86_400_000
DAY_OFF = (21*3600 + 50*60) * 1000   # UTC 21:50 = KST 06:50
KM = 3.48   # 1분 σ
KD = 2.0    # 일봉 σ
WIN = 10080


def custom_day_start(ts):
    mid = (ts // DAY) * DAY
    cand = mid + DAY_OFF
    return cand if ts >= cand else cand - DAY


def hlc3(rows):
    H=np.array([x['high'] for x in rows]); L=np.array([x['low'] for x in rows]); C=np.array([x['close'] for x in rows])
    return (H+L+C)/3


def draw_candles(ax, O, H, L, C, x):
    n=len(C); col=["#2ca02c" if C[k]>=O[k] else "#d62728" for k in range(n)]
    ax.vlines(x, L, H, colors=col, lw=0.4, zorder=2)
    bot=[min(O[k],C[k]) for k in range(n)]; ht=[max(abs(C[k]-O[k]),(H[k]-L[k])*0.001) for k in range(n)]
    ax.bar(x, ht, bottom=bot, width=0.8, color=col, edgecolor=col, linewidth=0.15, zorder=3)


def main():
    sym="BTCUSDT"; search_days=365
    d=fetch_klines_bybit(sym,"D",days=1095)
    dh=hlc3(d); ds=pd.Series(dh)
    dz=((ds-ds.rolling(30).mean())/ds.rolling(30).std(ddof=0)).to_numpy()
    dstart=np.array([x['start'] for x in d])
    daily_dir={}
    for i in range(len(d)):
        if np.isfinite(dz[i]):
            if dz[i]>=KD: daily_dir[int(dstart[i])]=+1   # 과매수→숏
            elif dz[i]<=-KD: daily_dir[int(dstart[i])]=-1  # 과매도→롱

    m=fetch_klines_bybit(sym,"1",days=1095)
    O=np.array([x['open'] for x in m]); H=np.array([x['high'] for x in m]); L=np.array([x['low'] for x in m]); C=np.array([x['close'] for x in m])
    ts=np.array([x['start'] for x in m]); mh=(H+L+C)/3
    s=pd.Series(mh); sma=s.rolling(WIN).mean().to_numpy(); sd=s.rolling(WIN).std(ddof=0).to_numpy()
    z=(mh-sma)/sd
    n=len(m); lo=n-search_days*1440

    # AND일 찾기 (1분 극단 사건이 그날 UTC 일봉게이트 방향과 일치)
    and_days={}  # cds -> dir
    armed=True
    for i in range(lo,n):
        v=z[i]
        if not np.isfinite(v): continue
        if abs(v)>=KM:
            if armed:
                armed=False
                dir_m = -1 if v<=-KM else +1
                ud=(int(ts[i])//DAY)*DAY
                if daily_dir.get(ud)==dir_m:
                    and_days[custom_day_start(int(ts[i]))]=dir_m
        elif abs(v)<KM:
            armed=True

    days=sorted(and_days)
    print(f"AND일 {len(days)}개 (롱 {sum(1 for k in days if and_days[k]==-1)} / 숏 {sum(1 for k in days if and_days[k]==+1)})")
    if not days: return

    cols=4; rows=math.ceil(len(days)/cols)
    fig,axes=plt.subplots(rows,cols,figsize=(cols*5.0,rows*3.2))
    axes=np.array(axes).flatten()
    for qi,cds in enumerate(days):
        dr=and_days[cds]
        sel=np.where((ts>=cds)&(ts<cds+DAY))[0]
        ax=axes[qi]
        if len(sel)==0: ax.axis("off"); continue
        K=list(range(len(sel)))
        draw_candles(ax,O[sel],H[sel],L[sel],C[sel],K)
        cs=sma[sel]; up=cs+KM*sd[sel]; dn=cs-KM*sd[sel]
        ax.fill_between(K,dn,up,color="gray",alpha=0.08,zorder=1)
        ax.plot(K,cs,color="orange",lw=1.3,zorder=4)
        ax.plot(K,dn,color="magenta",ls="--",lw=0.8,zorder=4)
        ax.plot(K,up,color="cyan",ls="--",lw=0.8,zorder=4)
        nm=0
        for kk,gi in enumerate(sel):
            v=z[gi]
            if not np.isfinite(v): continue
            if dr==-1 and v<=-KM: ax.scatter([kk],[L[gi]],color="magenta",s=26,marker="^",zorder=6); nm+=1
            elif dr==+1 and v>=KM: ax.scatter([kk],[H[gi]],color="cyan",s=26,marker="v",zorder=6); nm+=1
        ylo=min(L[sel].min(),np.nanmin(dn)); yhi=max(H[sel].max(),np.nanmax(up)); pad=(yhi-ylo)*0.03
        ax.set_ylim(ylo-pad,yhi+pad)
        ks=datetime.fromtimestamp(cds/1000,tz=KST)
        tag="과매도→롱▲" if dr==-1 else "과매수→숏▼"
        ax.set_title(f"{ks:%Y-%m-%d} KST06:50~ {tag} 진입{nm}",fontsize=8)
        ax.tick_params(labelsize=6); ax.grid(alpha=0.2)
        hh=[kk for kk in K if kk%240==0]
        ax.set_xticks(hh); ax.set_xticklabels([f"{datetime.fromtimestamp(ts[sel[kk]]/1000,tz=KST):%H:%M}" for kk in hh],fontsize=6)
    for j in range(len(days),len(axes)): axes[j].axis("off")
    fig.suptitle(f"{sym} AND일 1분봉 (일봉SMA30±2σ AND 1분SMA10080±3.48σ, hlc3, 하루=KST06:50~)",fontsize=12)
    plt.tight_layout(rect=[0,0,1,0.98]); plt.savefig(fig_path("mtf_and_days.png"),dpi=120); plt.close()
    print("저장 → figures/mtf_and_days.png")


if __name__ == "__main__":
    main()
