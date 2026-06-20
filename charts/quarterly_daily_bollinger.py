"""
분기별 일봉 캔들 + 볼린저(z-score) 극단밴드 — 3년치.

z = (종가 - SMA(N)) / 롤링표준편차(N).  밴드 = SMA ± k·σ.
극단: z <= -k (과매도/롱) ★자홍,  z >= +k (과매수/숏) ★시안.
변동성 정규화라 상/하 대칭이고, 250일 백분위 베이스라인 불필요(롤링창만 있으면 됨).
"""
from __future__ import annotations
import sys, os, argparse, math
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fig_path, fetch_klines_bybit

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
    try:
        matplotlib.rcParams["font.family"] = _f; break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--win-days", type=int, default=90)
    ap.add_argument("--ma", type=int, default=100, help="중심 SMA/σ 기간")
    ap.add_argument("--k", type=float, default=2.0, help="σ 배수(극단 기준)")
    ap.add_argument("--out", default="quarterly_daily_bollinger.png")
    args = ap.parse_args()
    N = args.ma; K = args.k

    daily = fetch_klines_bybit(args.symbol, "D", days=args.days)
    Oarr=np.array([x['open'] for x in daily]); C=np.array([x['close'] for x in daily])
    Hi=np.array([x['high'] for x in daily]); Lo=np.array([x['low'] for x in daily])
    ts=[x['start'] for x in daily]
    n = len(C)

    # 롤링 SMA / 표준편차 (종가 기준, 표준 볼린저)
    sma = np.full(n, np.nan); sd = np.full(n, np.nan)
    for i in range(N-1, n):
        w = C[i-N+1:i+1]
        sma[i] = w.mean(); sd[i] = w.std()
    z = np.where(sd > 0, (C - sma)/sd, np.nan)

    first = N-1
    qwin = args.win_days
    windows = []
    s = first
    while s + qwin <= n:
        windows.append((s, s+qwin)); s += qwin
    nq = len(windows)
    print(f"{args.symbol} 일봉 {n}개, 분기 {nq}개, 볼린저 SMA{N}±{K:.0f}σ\n")

    cols = 3; rows = math.ceil(nq/cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols*5, rows*3.2))
    axes = axes.flatten() if nq > 1 else [axes]

    print(f"{'분기':>12} {'과매도일':>8} {'과매수일':>8} {'min z':>7} {'max z':>7}")
    tot_os = tot_ob = 0
    for qi, (lo, hi) in enumerate(windows):
        xs = list(range(lo, hi)); Kx = list(range(len(xs)))
        dates = [datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc) for i in xs]
        opens=[Oarr[i] for i in xs]; highs=[Hi[i] for i in xs]; lows=[Lo[i] for i in xs]; close=[C[i] for i in xs]
        mas=[sma[i] for i in xs]
        bu=[sma[i]+K*sd[i] for i in xs]; bd=[sma[i]-K*sd[i] for i in xs]
        zq=[z[i] for i in xs]
        d0 = dates[0]

        ax = axes[qi]
        colors = ["#2ca02c" if close[k] >= opens[k] else "#d62728" for k in Kx]
        ax.vlines(Kx, lows, highs, colors=colors, lw=0.6, zorder=2)
        bottoms=[min(opens[k],close[k]) for k in Kx]; heights=[max(abs(close[k]-opens[k]),(highs[k]-lows[k])*0.001) for k in Kx]
        ax.bar(Kx, heights, bottom=bottoms, width=0.7, color=colors, edgecolor=colors, linewidth=0.3, zorder=3)
        ax.plot(Kx, mas, color="orange", lw=1.0, label=f"SMA{N}", zorder=4)
        ax.plot(Kx, bu, color="red", ls="--", lw=0.9, label=f"+{K:.0f}σ", zorder=4)
        ax.plot(Kx, bd, color="blue", ls="--", lw=0.9, label=f"-{K:.0f}σ", zorder=4)
        ax.fill_between(Kx, bd, bu, color="gray", alpha=0.06, zorder=1)
        nos = nob = 0
        for k in Kx:
            if not np.isfinite(zq[k]): continue
            if zq[k] <= -K:
                ax.scatter([k],[lows[k]], color="magenta", s=55, marker="*", edgecolor="black", linewidth=0.4, zorder=6); nos += 1
            elif zq[k] >= K:
                ax.scatter([k],[highs[k]], color="cyan", s=55, marker="*", edgecolor="black", linewidth=0.4, zorder=6); nob += 1
        tot_os += nos; tot_ob += nob
        ticks=[k for k in Kx if dates[k].day <= 1 or k == 0]
        ax.set_xticks(ticks); ax.set_xticklabels([f"{dates[k]:%m/%d}" for k in ticks], fontsize=7)
        ax.set_title(f"{d0:%Y-%m}  과매도{nos} 과매수{nob}", fontsize=10)
        ax.tick_params(labelsize=7); ax.grid(alpha=0.2)
        if qi == 0: ax.legend(fontsize=7, loc="best")
        zmin = np.nanmin(zq); zmax = np.nanmax(zq)
        print(f"{d0:%Y-%m-%d}  {nos:>6}  {nob:>6}  {zmin:>6.2f}  {zmax:>6.2f}")

    for j in range(nq, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{args.symbol} 분기별 일봉 + 볼린저(SMA{N}±{K:.0f}σ)  ★자홍=과매도(z≤-{K:.0f}) ★시안=과매수(z≥+{K:.0f})  [총 과매도{tot_os}/과매수{tot_ob}]", fontsize=11)
    plt.tight_layout(rect=[0,0,1,0.98])
    plt.savefig(fig_path(args.out), dpi=120)
    print(f"\n총 과매도 {tot_os}일 / 과매수 {tot_ob}일  → 저장 {args.out}")


if __name__ == "__main__":
    main()
