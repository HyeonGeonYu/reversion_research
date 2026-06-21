"""
극단 발생 대표일 1분봉 차트 — SMA(W) ± kσ (hlc3 기준)로 과매수/과매도 사건이 난 날들.

- 평균/σ/z 모두 hlc3=(고+저+종)/3 기준.
- 하루 = KST 06:50 ~ 다음날 06:50 (= UTC 21:50 ~ 다음 21:50).
- 사건일(|z|>=k 발생일) 중 peak|z| 큰 순으로, 서로 3일 이상 떨어진 대표일 N개 선택.
- 각 날의 1분봉 캔들 + SMA + 닿은 밴드 + 극단 마커.
"""
from __future__ import annotations
import sys, os, argparse, math
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
DAY_MS = 86_400_000
DAY_START_OFF = (21*3600 + 50*60) * 1000   # UTC 21:50 = KST 06:50


def custom_day_start(ts):
    mid = (ts // DAY_MS) * DAY_MS
    cand = mid + DAY_START_OFF
    return cand if ts >= cand else cand - DAY_MS


def draw_candles(ax, O, H, L, C, x):
    n = len(C)
    col = ["#2ca02c" if C[k] >= O[k] else "#d62728" for k in range(n)]
    ax.vlines(x, L, H, colors=col, lw=0.5, zorder=2)
    bottoms = [min(O[k], C[k]) for k in range(n)]
    heights = [max(abs(C[k]-O[k]), (H[k]-L[k])*0.001) for k in range(n)]
    ax.bar(x, heights, bottom=bottoms, width=0.8, color=col, edgecolor=col, linewidth=0.2, zorder=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--window", type=int, default=10080, help="SMA/σ 기간(분) 7일=10080")
    ap.add_argument("--k", type=float, default=3.48)
    ap.add_argument("--search-days", type=int, default=365, help="사건 탐색 최근 일수")
    ap.add_argument("--max-days", type=int, default=6)
    ap.add_argument("--min-gap", type=int, default=3, help="선택일 간 최소 간격(일)")
    args = ap.parse_args()
    W, k = args.window, args.k

    c = fetch_klines_bybit(args.symbol, "1", days=1095)
    O=np.array([x['open'] for x in c]); H=np.array([x['high'] for x in c])
    L=np.array([x['low'] for x in c]); C=np.array([x['close'] for x in c]); ts=np.array([x['start'] for x in c])
    hlc3 = (H + L + C) / 3.0
    s = pd.Series(hlc3)
    sma = s.rolling(W).mean(); sd = s.rolling(W).std(ddof=0)
    z = ((s - sma)/sd).to_numpy()
    sma = sma.to_numpy(); sd = sd.to_numpy()
    n = len(C)

    # 사건(첫 교차, debounce) 탐색 — 최근 search-days 구간
    lo = max(W, n - args.search_days*1440)
    events = {}   # day_start -> [peak_abs_z, dir]
    armed = True
    for i in range(lo, n):
        v = z[i]
        if not np.isfinite(v): continue
        if abs(v) >= k:
            d0 = custom_day_start(int(ts[i]))
            cur = events.get(d0)
            di = 1 if v < 0 else -1  # z<0(과매도)=롱, z>0(과매수)=숏... dir표시용: long/short
            if cur is None or abs(v) > cur[0]:
                events[d0] = [abs(v), "long" if v < 0 else "short"]
            armed = False
        elif abs(v) < k:
            armed = True

    if not events:
        print("사건 없음"); return
    # peak|z| 큰 순, min-gap 떨어뜨려 대표일 선택
    ordered = sorted(events.items(), key=lambda kv: -kv[1][0])
    picked = []
    for d0, (pz, dr) in ordered:
        if all(abs(d0 - p[0]) >= args.min_gap*DAY_MS for p in picked):
            picked.append((d0, pz, dr))
        if len(picked) >= args.max_days:
            break
    picked.sort(key=lambda x: x[0])   # 시간순
    print(f"사건일 {len(events)}개 중 대표 {len(picked)}개 선택 (search {args.search_days}일, k={k}σ, hlc3)")

    cols = 3; rows = math.ceil(len(picked)/cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols*5.4, rows*3.4))
    axes = np.array(axes).flatten() if len(picked) > 1 else [axes]
    for qi, (d0, pz, dr) in enumerate(picked):
        sel = np.where((ts >= d0) & (ts < d0 + DAY_MS))[0]
        ax = axes[qi]
        if len(sel) == 0:
            ax.axis("off"); continue
        K = list(range(len(sel)))
        draw_candles(ax, O[sel], H[sel], L[sel], C[sel], K)
        csma = sma[sel]; up = csma + k*sd[sel]; dn = csma - k*sd[sel]
        ax.fill_between(K, dn, up, color="gray", alpha=0.08, zorder=1)
        ax.plot(K, csma, color="orange", lw=1.6, zorder=4, label="SMA10080(평균)")
        ax.plot(K, dn, color="magenta", ls="--", lw=0.9, zorder=4, label=f"-{k}σ")
        ax.plot(K, up, color="cyan", ls="--", lw=0.9, zorder=4, label=f"+{k}σ")
        if qi == 0: ax.legend(fontsize=6, loc="upper right")
        # 하루 내 SMA vs 밴드 변동폭 (증명용)
        band = dn if dr == "long" else up
        sma_rng = (np.nanmax(csma)-np.nanmin(csma))/np.nanmean(csma)*100
        band_rng = (np.nanmax(band)-np.nanmin(band))/np.nanmean(band)*100
        print(f"  {datetime.fromtimestamp(d0/1000,tz=KST):%Y-%m-%d}: 하루내 SMA 변동 {sma_rng:.2f}% / 밴드 변동 {band_rng:.2f}% (밴드가 {band_rng/max(sma_rng,1e-9):.1f}배)")
        nmark = 0
        for kk, gi in enumerate(sel):
            v = z[gi]
            if not np.isfinite(v): continue
            if v <= -k:
                ax.scatter([kk], [L[gi]], color="magenta", s=30, marker="^", zorder=6); nmark += 1
            elif v >= k:
                ax.scatter([kk], [H[gi]], color="cyan", s=30, marker="v", zorder=6); nmark += 1
        # y범위: 양쪽 밴드 전부 + 캔들 (평균 가운데, 밴드 양옆 = 정상 볼린저 모양)
        ylo = min(L[sel].min(), np.nanmin(dn))
        yhi = max(H[sel].max(), np.nanmax(up))
        pad = (yhi - ylo)*0.03
        ax.set_ylim(ylo - pad, yhi + pad)
        ks = datetime.fromtimestamp(d0/1000, tz=KST)
        tag = "과매도(롱)" if dr == "long" else "과매수(숏)"
        ax.set_title(f"{ks:%Y-%m-%d} KST06:50~  {tag} peak|z|={pz:.2f} 극단{nmark}분", fontsize=9)
        ax.tick_params(labelsize=6); ax.grid(alpha=0.2)
        hh = [kk for kk in K if kk % 240 == 0]
        ax.set_xticks(hh)
        ax.set_xticklabels([f"{datetime.fromtimestamp(ts[sel[kk]]/1000,tz=KST):%H:%M}" for kk in hh], fontsize=6)
    for j in range(len(picked), len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{args.symbol} 극단 발생 대표일 1분봉 (SMA{W}±{k}σ, hlc3, 하루=KST06:50~)  ▲과매도매수 ▼과매수매도", fontsize=12)
    plt.tight_layout(rect=[0,0,1,0.98]); plt.savefig(fig_path("mtf_event_days.png"), dpi=120); plt.close()
    print("저장 → figures/mtf_event_days.png")


if __name__ == "__main__":
    main()
