"""
눌림목 진입 40건 3개월 시각화 — BTC. 일봉게이트 음영 + 1분 SMA240 ±2σ + 진입마커.
"""
import sys, os, bisect
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
plt.rcParams['font.family']='Malgun Gothic'; plt.rcParams['axes.unicode_minus']=False
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40; COOLDOWN=60; SCAN_DAYS=90
SYM="BTCUSDT"

def rsi(close,p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()

def kst(ms): return datetime.utcfromtimestamp(ms/1000)+timedelta(hours=9)

# --- daily gate ---
d=fetch_klines_bybit(SYM,"D",days=1095)
H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
ds=pd.Series((H+L+Cc)/3); dsma=ds.rolling(30).mean(); dsd=ds.rolling(30).std(ddof=0)
dz=((ds-dsma)/dsd).to_numpy()
dupper=(dsma+KD*dsd).to_numpy(); dlower=(dsma-KD*dsd).to_numpy(); dsma=dsma.to_numpy()
dr=rsi(Cc,RSI_P); dst=[x['start'] for x in d]; dg=[0]*len(d)
for i in range(len(d)):
    if np.isfinite(dz[i]) and np.isfinite(dr[i]):
        if dz[i]>=KD and dr[i]>RSI_HI: dg[i]=+1
        elif dz[i]<=-KD and dr[i]<RSI_LO: dg[i]=-1

# --- 1min ---
m=fetch_klines_bybit(SYM,"1",days=1095)
Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
s=pd.Series((Hi+Lo+C)/3); sma=s.rolling(MWIN).mean(); sd=s.rolling(MWIN).std(ddof=0)
z=((s-sma)/sd).to_numpy(); upper=(sma+KMIN*sd).to_numpy(); lower=(sma-KMIN*sd).to_numpy(); sma=sma.to_numpy()

start=int(np.searchsorted(ts, ts[-1]-SCAN_DAYS*DAY))
def gate(t):
    j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0

# --- 진입 스캔 ---
i=max(MWIN,start); armed=True; last=-10**9; entL=[]; entS=[]
while i<len(C):
    v=z[i]
    if not np.isfinite(v): i+=1; continue
    g=gate(ts[i])
    if armed and g!=0 and (i-last)>=COOLDOWN:
        if g==1 and v<=-KMIN: entL.append(i); last=i; armed=False
        elif g==-1 and v>=KMIN: entS.append(i); last=i; armed=False
    if abs(v)<KMIN: armed=True
    i+=1

# --- plot ---
x=[kst(t) for t in ts[start:]]
fig,ax=plt.subplots(figsize=(20,9))
# 게이트 음영: 적용게이트 dg[k]는 [dst[k]+DAY, dst[k+1]+DAY)
for k in range(len(dst)):
    a=dst[k]+DAY; b=(dst[k+1] if k+1<len(dst) else dst[k]+2*DAY)+DAY
    if b<ts[start] or a>ts[-1] or dg[k]==0: continue
    ax.axvspan(kst(max(a,ts[start])),kst(min(b,ts[-1])),color=('#d6f5d6' if dg[k]==1 else '#f9d6d6'),zorder=0)
ax.fill_between(x,lower[start:],upper[start:],color='#cfe2ff',alpha=0.55,zorder=1,label='1분 SMA240 ±2σ')
ax.plot(x,sma[start:],color='#3b6fb0',lw=0.7,zorder=2,label='1분 SMA240')
# 일봉 SMA30 ±2σ (추세 게이트 기준)
dk=[k for k in range(len(dst)) if ts[start]-DAY<=dst[k]<=ts[-1]]
dx=[kst(dst[k]) for k in dk]
ax.fill_between(dx,[dlower[k] for k in dk],[dupper[k] for k in dk],color='#ffe0b0',alpha=0.30,step='post',zorder=1,label='일봉 SMA30 ±2σ')
ax.plot(dx,[dupper[k] for k in dk],color='#e08a1e',lw=1.0,ls='--',drawstyle='steps-post',zorder=2)
ax.plot(dx,[dlower[k] for k in dk],color='#e08a1e',lw=1.0,ls='--',drawstyle='steps-post',zorder=2)
ax.plot(dx,[dsma[k] for k in dk],color='#e08a1e',lw=1.2,drawstyle='steps-post',zorder=2,label='일봉 SMA30')
ax.plot(x,C[start:],color='#222',lw=0.6,zorder=3,label='BTC 종가')
ax.scatter([kst(ts[j]) for j in entL],[C[j] for j in entL],marker='^',s=90,c='#0a8a0a',edgecolor='k',lw=0.5,zorder=5,label=f'LONG 진입 ({len(entL)})')
ax.scatter([kst(ts[j]) for j in entS],[C[j] for j in entS],marker='v',s=90,c='#cc1111',edgecolor='k',lw=0.5,zorder=5,label=f'SHORT 진입 ({len(entS)})')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
ax.set_title(f'{SYM} 최근 {SCAN_DAYS}일 — 눌림목 진입 {len(entL)+len(entS)}건 (초록음영=상승게이트, 빨강음영=하락게이트)',fontproperties=None)
ax.legend(loc='upper left',fontsize=10); ax.grid(alpha=0.25)
plt.tight_layout()
out=os.path.join(os.path.dirname(__file__),"..","figures","pullback_3mo.png")
os.makedirs(os.path.dirname(out),exist_ok=True)
plt.savefig(out,dpi=110); print("saved:",os.path.abspath(out)); print(f"LONG {len(entL)}  SHORT {len(entS)}")
