"""
분기별(3개월) 1일봉 차트 — 가격 + MA100 + ±T 밴드 (T = 그 분기 '1터치' 임계값).

각 90일 윈도우마다, 일봉 종가가 MA100 ±T 밴드를 딱 1번 터치하는 T를 이분탐색으로 구하고,
서브플롯에 가격/MA100/±T밴드/터치점을 그려 눈으로 확인.
"""
from __future__ import annotations
import sys, os, argparse, math
from datetime import datetime, timezone
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

MIN_INT = 3   # 터치 최소간격(일) — 같은 이탈을 2번 세지 않도록


def count_cross(C, Hi, Lo, ma, lo, hi, thr):
    cnt = 0; state = None; lastU = lastD = -10**9
    touches = []   # (idx, 'up'/'down')
    for i in range(lo, hi):
        m = ma[i]
        if m is None:
            continue
        up = m*(1+thr); dn = m*(1-thr)
        if state in ("below", "in") and Hi[i] > up and (i-lastU) > MIN_INT:
            cnt += 1; lastU = i; touches.append((i, "up"))
        if state in ("above", "in") and Lo[i] < dn and (i-lastD) > MIN_INT:
            cnt += 1; lastD = i; touches.append((i, "down"))
        cl = C[i]; state = "above" if cl > up else ("below" if cl < dn else "in")
    return cnt, touches


def find_T(C, Hi, Lo, ma, lo, hi, target, maxthr=0.6):
    left, right = 0.0, maxthr; opt = right
    for _ in range(34):
        mid = (left+right)/2
        c, _ = count_cross(C, Hi, Lo, ma, lo, hi, mid)
        if c > target:
            left = mid
        else:
            opt = mid; right = mid
    return opt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--win-days", type=int, default=90)
    ap.add_argument("--target", type=int, default=1)
    ap.add_argument("--ma", type=int, default=100)
    ap.add_argument("--out", default="quarterly_daily_chart.png")
    args = ap.parse_args()

    daily = fetch_klines_bybit(args.symbol, "D", days=args.days)
    Oarr=[x['open'] for x in daily]; C=[x['close'] for x in daily]
    Hi=[x['high'] for x in daily]; Lo=[x['low'] for x in daily]
    ts=[x['start'] for x in daily]; ma=_ma_hlc3(daily, args.ma)
    n = len(C)

    # MA100 가능한 첫 인덱스부터 분기 분할
    first = next((i for i in range(n) if ma[i] is not None), n)
    qwin = args.win_days
    windows = []
    s = first
    while s + qwin <= n:
        windows.append((s, s+qwin)); s += qwin
    print(f"{args.symbol} 일봉 {n}개, MA{args.ma} 가능 시작 idx={first}, 분기 {len(windows)}개\n")

    nq = len(windows)
    cols = 3; rows = math.ceil(nq/cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols*5, rows*3.2))
    axes = axes.flatten() if nq > 1 else [axes]

    print(f"{'분기':>14} {'T(1터치)':>9}")
    for qi, (lo, hi) in enumerate(windows):
        T = find_T(C, Hi, Lo, ma, lo, hi, args.target)
        cc, touches = count_cross(C, Hi, Lo, ma, lo, hi, T)
        xs = list(range(lo, hi))
        K = list(range(len(xs)))                    # 분기 내 0-기준 인덱스(캔들 x축)
        dates = [datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc) for i in xs]
        opens=[Oarr[i] for i in xs]; highs=[Hi[i] for i in xs]; lows=[Lo[i] for i in xs]; close=[C[i] for i in xs]
        mas = [ma[i] for i in xs]
        up = [m*(1+T) for m in mas]; dn = [m*(1-T) for m in mas]
        d0 = dates[0]
        print(f"{d0:%Y-%m-%d}  {T*100:>7.2f}%")

        ax = axes[qi]
        # 캔들스틱: 위크(고-저) + 몸통(시-종)
        colors = ["#2ca02c" if close[k] >= opens[k] else "#d62728" for k in K]
        ax.vlines(K, lows, highs, colors=colors, lw=0.6, zorder=2)
        bottoms = [min(opens[k], close[k]) for k in K]
        heights = [max(abs(close[k]-opens[k]), (highs[k]-lows[k])*0.001) for k in K]
        ax.bar(K, heights, bottom=bottoms, width=0.7, color=colors, edgecolor=colors, linewidth=0.3, zorder=3)
        # MA / 밴드
        ax.plot(K, mas, color="orange", lw=1.0, label=f"MA{args.ma}", zorder=4)
        ax.plot(K, up, color="red", ls="--", lw=0.9, zorder=4)
        ax.plot(K, dn, color="blue", ls="--", lw=0.9, zorder=4)
        ax.fill_between(K, dn, up, color="gray", alpha=0.07, zorder=1)
        # 터치점: 위는 고가, 아래는 저가에 표시
        for ti, dirc in touches:
            kk = ti - lo
            yv = Hi[ti] if dirc == "up" else Lo[ti]
            ax.scatter([kk], [yv], color="magenta", s=55, zorder=6, marker="*", edgecolor="black", linewidth=0.4)
        # x축 날짜 라벨 (월 단위 몇 개)
        ticks = [k for k in K if dates[k].day <= 1 or k == 0]
        ax.set_xticks(ticks); ax.set_xticklabels([f"{dates[k]:%m/%d}" for k in ticks], fontsize=7)
        ax.set_title(f"{d0:%Y-%m}  T={T*100:.1f}% (터치 {cc}회)", fontsize=10)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.2)
        if qi == 0:
            ax.legend(fontsize=7, loc="best")

    for j in range(nq, len(axes)):
        axes[j].axis("off")

    fig.suptitle(f"{args.symbol} 분기별 1일봉 + MA{args.ma} + ±T밴드 (T=분기 1터치 임계값)", fontsize=13)
    plt.tight_layout(rect=[0, 0, 1, 0.98])
    plt.savefig(fig_path(args.out), dpi=120)
    print(f"\n저장 → {args.out}")


if __name__ == "__main__":
    main()
