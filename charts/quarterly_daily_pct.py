"""
분기별 일봉 캔들 + '백분위 극단(P%)' 밴드 표시 — 3년치.

일봉 이격 d=(종가-MA100)/MA100 의 확장창 백분위로:
  하위 P% 임계(rare-low), 상위 (100-P)% 임계(rare-high)  → 밴드로 그림.
  종가가 그 밖이면 '드문 극단' 날 → ★ 표시. (백분위 게이트와 동일 기준)
"""
from __future__ import annotations
import sys, os, argparse, math
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fig_path, fetch_klines_bybit, _ma_hlc3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
    try:
        matplotlib.rcParams["font.family"] = _f; break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False

D_MINHIST = 250


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--win-days", type=int, default=90)
    ap.add_argument("--pct", type=float, default=2.0, help="극단 꼬리 %")
    ap.add_argument("--ma", type=int, default=100)
    ap.add_argument("--min-hist", type=int, default=100, help="백분위 최소 과거표본")
    ap.add_argument("--out", default="quarterly_daily_pct.png")
    args = ap.parse_args()
    P = args.pct
    minhist = args.min_hist

    daily = fetch_klines_bybit(args.symbol, "D", days=args.days)
    Oarr=[x['open'] for x in daily]; C=[x['close'] for x in daily]
    Hi=[x['high'] for x in daily]; Lo=[x['low'] for x in daily]
    ts=[x['start'] for x in daily]; ma=_ma_hlc3(daily, args.ma)
    n = len(C)

    # 이격 + 확장창 백분위 임계(하위P / 상위(100-P))를 각 일봉에 산출
    dev = [ (C[i]-ma[i])/ma[i] if ma[i] is not None else None for i in range(n) ]
    lo_thr = [None]*n; hi_thr = [None]*n   # deviation 임계값
    vals = []
    for i in range(n):
        if dev[i] is None:
            continue
        if len(vals) >= minhist:
            arr = np.array(vals)
            lo_thr[i] = float(np.percentile(arr, P))
            hi_thr[i] = float(np.percentile(arr, 100-P))
        vals.append(dev[i])

    first = next((i for i in range(n) if ma[i] is not None), n)
    qwin = args.win_days
    windows = []
    s = first
    while s + qwin <= n:
        windows.append((s, s+qwin)); s += qwin
    nq = len(windows)
    print(f"{args.symbol} 일봉 {n}개, 분기 {nq}개, 극단 꼬리 {P:.0f}%\n")

    cols = 3; rows = math.ceil(nq/cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols*5, rows*3.2))
    axes = axes.flatten() if nq > 1 else [axes]

    print(f"{'분기':>12} {'rare-low밴드':>11} {'rare-high밴드':>12} {'극단일수':>8}")
    for qi, (lo, hi) in enumerate(windows):
        xs = list(range(lo, hi)); K = list(range(len(xs)))
        dates = [datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc) for i in xs]
        opens=[Oarr[i] for i in xs]; highs=[Hi[i] for i in xs]; lows=[Lo[i] for i in xs]; close=[C[i] for i in xs]
        mas=[ma[i] for i in xs]
        # 밴드 (deviation 임계 → 가격)
        bl = [ (mas[k]*(1+lo_thr[xs[k]]) if lo_thr[xs[k]] is not None else None) for k in K ]
        bh = [ (mas[k]*(1+hi_thr[xs[k]]) if hi_thr[xs[k]] is not None else None) for k in K ]
        d0 = dates[0]

        ax = axes[qi]
        colors = ["#2ca02c" if close[k] >= opens[k] else "#d62728" for k in K]
        ax.vlines(K, lows, highs, colors=colors, lw=0.6, zorder=2)
        bottoms=[min(opens[k],close[k]) for k in K]; heights=[max(abs(close[k]-opens[k]),(highs[k]-lows[k])*0.001) for k in K]
        ax.bar(K, heights, bottom=bottoms, width=0.7, color=colors, edgecolor=colors, linewidth=0.3, zorder=3)
        ax.plot(K, mas, color="orange", lw=1.0, label=f"MA{args.ma}", zorder=4)
        if any(v is not None for v in bl):
            ax.plot(K, bl, color="blue", ls="--", lw=0.9, zorder=4, label=f"하위{P:.0f}%")
            ax.plot(K, bh, color="red", ls="--", lw=0.9, zorder=4, label=f"상위{P:.0f}%")
        # 극단일 표시
        ndays = 0
        for k in K:
            i = xs[k]
            if lo_thr[i] is None: continue
            if dev[i] <= lo_thr[i]:
                ax.scatter([k],[lows[k]], color="magenta", s=55, marker="*", edgecolor="black", linewidth=0.4, zorder=6); ndays += 1
            elif dev[i] >= hi_thr[i]:
                ax.scatter([k],[highs[k]], color="cyan", s=55, marker="*", edgecolor="black", linewidth=0.4, zorder=6); ndays += 1
        ticks=[k for k in K if dates[k].day <= 1 or k == 0]
        ax.set_xticks(ticks); ax.set_xticklabels([f"{dates[k]:%m/%d}" for k in ticks], fontsize=7)
        bl_pct = lo_thr[xs[-1]]*100 if lo_thr[xs[-1]] is not None else float('nan')
        bh_pct = hi_thr[xs[-1]]*100 if hi_thr[xs[-1]] is not None else float('nan')
        ax.set_title(f"{d0:%Y-%m}  극단일 {ndays}", fontsize=10)
        ax.tick_params(labelsize=7); ax.grid(alpha=0.2)
        if qi == 0:
            ax.legend(fontsize=7, loc="best")
        print(f"{d0:%Y-%m-%d}  {bl_pct:>9.1f}%  {bh_pct:>10.1f}%  {ndays:>6}")

    for j in range(nq, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{args.symbol} 분기별 일봉 + 백분위 극단밴드(꼬리 {P:.0f}%)  ★자홍=드문하락 ★시안=드문상승", fontsize=12)
    plt.tight_layout(rect=[0,0,1,0.98])
    plt.savefig(fig_path(args.out), dpi=120)
    print(f"\n저장 → {args.out}")


if __name__ == "__main__":
    main()
