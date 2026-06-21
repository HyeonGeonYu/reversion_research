"""
한 에피소드 확대 — 1분 SMA240 ±2σ(눌림 타이밍) + 일봉 SMA30 상/하단 + 진입마커.
ZOOM_FROM~ZOOM_TO (KST 날짜) 구간만.
"""
import sys, os, bisect
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
plt.rcParams['font.family']='Malgun Gothic'; plt.rcParams['axes.unicode_minus']=False
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit

DAY=86_400_000; MWIN=240; KMIN=2.0; KD=2.0; RSI_P=15; RSI_HI=60; RSI_LO=40; COOLDOWN=60
SYM="BTCUSDT"
ZOOM_FROM="2026-05-06"; ZOOM_TO="2026-05-10"   # 5/7 천장 LONG 에피소드

def rsi(close,p):
    s=pd.Series(close); d=s.diff()
    ag=d.clip(lower=0).ewm(alpha=1/p,adjust=False).mean(); al=(-d).clip(lower=0).ewm(alpha=1/p,adjust=False).mean()
    rs=ag/al.replace(0,np.nan); return (100-100/(1+rs)).to_numpy()
def kst(ms): return datetime.utcfromtimestamp(ms/1000)+timedelta(hours=9)
def ms_of(datestr): return int((datetime.strptime(datestr,"%Y-%m-%d")-datetime(1970,1,1)-timedelta(hours=9)).total_seconds()*1000)

d=fetch_klines_bybit(SYM,"D",days=1095)
H=np.array([x['high'] for x in d]);L=np.array([x['low'] for x in d]);Cc=np.array([x['close'] for x in d])
ds=pd.Series((H+L+Cc)/3); dsma=ds.rolling(30).mean(); dsd=ds.rolling(30).std(ddof=0)
dz=((ds-dsma)/dsd).to_numpy(); dupper=(dsma+KD*dsd).to_numpy(); dlower=(dsma-KD*dsd).to_numpy(); dsma=dsma.to_numpy()
dr=rsi(Cc,RSI_P); dst=[x['start'] for x in d]; dg=[0]*len(d)
for i in range(len(d)):
    if np.isfinite(dz[i]) and np.isfinite(dr[i]):
        if dz[i]>=KD and dr[i]>RSI_HI: dg[i]=+1
        elif dz[i]<=-KD and dr[i]<RSI_LO: dg[i]=-1

m=fetch_klines_bybit(SYM,"1",days=1095)
Hi=np.array([x['high'] for x in m]);Lo=np.array([x['low'] for x in m]);C=np.array([x['close'] for x in m]);ts=np.array([x['start'] for x in m])
s=pd.Series((Hi+Lo+C)/3); sma=s.rolling(MWIN).mean(); sd=s.rolling(MWIN).std(ddof=0)
z=((s-sma)/sd).to_numpy(); upper=(sma+KMIN*sd).to_numpy(); lower=(sma-KMIN*sd).to_numpy(); sma=sma.to_numpy()
def gate(t):
    j=bisect.bisect_right(dst,int(t)-DAY)-1; return dg[j] if j>=0 else 0

# 진입스캔 (전체) 후 구간필터
i=MWIN; armed=True; last=-10**9; entL=[]; entS=[]
while i<len(C):
    v=z[i]
    if not np.isfinite(v): i+=1; continue
    g=gate(ts[i])
    if armed and g!=0 and (i-last)>=COOLDOWN:
        if g==1 and v<=-KMIN: entL.append(i); last=i; armed=False
        elif g==-1 and v>=KMIN: entS.append(i); last=i; armed=False
    if abs(v)<KMIN: armed=True
    i+=1

a=ms_of(ZOOM_FROM); b=ms_of(ZOOM_TO)
lo=int(np.searchsorted(ts,a)); hi=int(np.searchsorted(ts,b))
x=[kst(t) for t in ts[lo:hi]]
fig,ax=plt.subplots(figsize=(20,9))
for k in range(len(dst)):
    aa=dst[k]+DAY; bb=(dst[k+1] if k+1<len(dst) else dst[k]+2*DAY)+DAY
    if bb<a or aa>b or dg[k]==0: continue
    ax.axvspan(kst(max(aa,a)),kst(min(bb,b)),color=('#d6f5d6' if dg[k]==1 else '#f9d6d6'),zorder=0)
ax.fill_between(x,lower[lo:hi],upper[lo:hi],color='#9ecbff',alpha=0.55,zorder=1,label='1분 SMA240 ±2σ')
ax.plot(x,sma[lo:hi],color='#3b6fb0',lw=1.0,zorder=2,label='1분 SMA240')
ax.plot(x,C[lo:hi],color='#111',lw=1.0,zorder=3,label='BTC 종가')
# 일봉 상/하단 (구간내)
dk=[k for k in range(len(dst)) if a-DAY<=dst[k]<=b]
dx=[kst(dst[k]) for k in dk]
ax.plot(dx,[dupper[k] for k in dk],color='#e08a1e',lw=1.4,ls='--',drawstyle='steps-post',zorder=2,label='일봉 SMA30 +2σ(상단)')
ax.plot(dx,[dlower[k] for k in dk],color='#e0b01e',lw=1.2,ls=':',drawstyle='steps-post',zorder=2,label='일봉 SMA30 -2σ(하단)')
eL=[j for j in entL if lo<=j<hi]; eS=[j for j in entS if lo<=j<hi]
ax.scatter([kst(ts[j]) for j in eL],[C[j] for j in eL],marker='^',s=130,c='#0a8a0a',edgecolor='k',lw=0.6,zorder=5,label=f'LONG 진입 ({len(eL)})')
ax.scatter([kst(ts[j]) for j in eS],[C[j] for j in eS],marker='v',s=130,c='#cc1111',edgecolor='k',lw=0.6,zorder=5,label=f'SHORT 진입 ({len(eS)})')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
ax.set_title(f'{SYM} {ZOOM_FROM}~{ZOOM_TO} 확대 — 가격이 일봉 상단(주황) 부근 과매수 + 1분 하단(파랑) 눌림에서 LONG 진입')
ax.legend(loc='upper right',fontsize=10); ax.grid(alpha=0.25); plt.xticks(rotation=20)
plt.tight_layout()
out=os.path.join(os.path.dirname(__file__),"..","figures","pullback_zoom.png")
plt.savefig(out,dpi=110); print("saved:",os.path.abspath(out)); print(f"구간내 LONG {len(eL)} SHORT {len(eS)}")
