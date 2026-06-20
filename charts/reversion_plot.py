"""
회귀확률 시각화 — "각 값이 왜 이런 확률인지" 설명용 그래프 (오프라인 read-only)

패널:
  (1) 복귀확률 vs horizon(기다리는 봉수): 왜 30봉에선 낮고 길게보면 100%인지
  (2) 임계값 T별 복귀확률 (고정 horizon)
  (3) 임계값 T별 기대값
  (4) 실제 가격 + MA100 + ±T 밴드 + 이벤트 마커(복귀=초록/실패=빨강)
"""
from __future__ import annotations

import argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 한글 폰트 (Windows). 없으면 자동 폴백.
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
    try:
        matplotlib.rcParams["font.family"] = _f
        break
    except Exception:
        continue
matplotlib.rcParams["axes.unicode_minus"] = False

from reversion_calibrator import fig_path, fetch_klines_bybit, _ma_hlc3


def collect_revert_times(candles, ma, T, max_h):
    """
    각 이탈 이벤트의 'MA 첫 복귀까지 봉수'를 수집 (max_h 내 미복귀=None).
    반환: (revert_times[list], events[list of (entry_i, side, t_or_None)])
    """
    n = len(candles)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    revert_times = []
    events = []
    i = 0
    armed = True
    while i < n:
        m = ma[i]
        if m is None:
            i += 1
            continue
        d = (closes[i] - m) / m
        if armed and abs(d) >= T:
            side = "LONG" if d <= -T else "SHORT"
            P0 = closes[i]
            end = min(i + max_h, n - 1)
            t = None
            for k in range(i + 1, end + 1):
                if ma[k] is None:
                    continue
                if side == "LONG" and highs[k] >= ma[k]:
                    t = k - i
                    break
                if side == "SHORT" and lows[k] <= ma[k]:
                    t = k - i
                    break
            revert_times.append(t)
            events.append((i, side, t))
            armed = False
            i = (i + t) if t is not None else end
            continue
        if abs(d) < T:
            armed = True
        i += 1
    return revert_times, events


def cdf(revert_times, horizon):
    """P(복귀 by k) for k in 1..horizon"""
    total = len(revert_times)
    if total == 0:
        return [0.0] * (horizon + 1)
    out = []
    for k in range(horizon + 1):
        c = sum(1 for t in revert_times if (t is not None and t <= k))
        out.append(c / total)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--horizon", type=int, default=30, help="고정 horizon(봉) — 확률/기대값 패널 기준")
    ap.add_argument("--maxh", type=int, default=480, help="CDF용 최대 horizon(봉)")
    ap.add_argument("--ma", type=int, default=100)
    ap.add_argument("--out", default="tools/reversion_plot.png")
    args = ap.parse_args()

    thresholds = [0.005, 0.0075, 0.01, 0.015, 0.02]
    H = args.horizon

    print(f"[{args.symbol}] fetching {args.days}d 1m...")
    candles = fetch_klines_bybit(args.symbol, "1", days=args.days)
    ma = _ma_hlc3(candles, args.ma)
    print(f"  loaded {len(candles)} bars")

    # 임계값별 CDF / 통계
    cdfs = {}
    prob_at_H = {}
    exp_at_H = {}
    events_for_plot = None
    for T in thresholds:
        rts, events = collect_revert_times(candles, ma, T, args.maxh)
        cdfs[T] = cdf(rts, args.maxh)
        # horizon=H 기준 확률/기대값
        rev = [t for t in rts if (t is not None and t <= H)]
        n = len(rts)
        p = len(rev) / n if n else 0.0
        prob_at_H[T] = (p, n)
        # 간이 기대값: 복귀=+T, 실패=horizon end pnl 근사(여기선 -T*MAE근사 대신 수익=T로 단순화 표시용)
        exp_at_H[T] = p * T  # 표시용 근사(정밀 기대값은 calibrator 표 참조)
        if abs(T - 0.01) < 1e-9:
            events_for_plot = events  # T=1%를 가격패널에 표시

    # ── 그림 ──
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(f"{args.symbol} 1m 회귀확률 분석 (MA{args.ma}, {args.days}일)", fontsize=14)

    # (1) 복귀확률 vs horizon
    ax = axes[0][0]
    ks = list(range(args.maxh + 1))
    for T in thresholds:
        ax.plot(ks, [v * 100 for v in cdfs[T]], label=f"T={T*100:.2f}%")
    ax.axvline(H, color="red", ls="--", lw=1, label=f"horizon={H}봉")
    ax.set_title("(1) 복귀확률 vs 기다리는 봉수 — 왜 짧으면 낮고 길면 100%인가")
    ax.set_xlabel("기다리는 봉수 (분)")
    ax.set_ylabel("복귀확률 (%)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # (2) T별 복귀확률 (horizon=H)
    ax = axes[0][1]
    xs = [f"{T*100:.2f}%\n(n={prob_at_H[T][1]})" for T in thresholds]
    ys = [prob_at_H[T][0] * 100 for T in thresholds]
    ax.bar(xs, ys, color="steelblue")
    for x, y in zip(xs, ys):
        ax.text(x, y + 0.5, f"{y:.0f}%", ha="center", fontsize=9)
    ax.set_title(f"(2) 임계값별 복귀확률 (horizon={H}봉)")
    ax.set_ylabel("복귀확률 (%)")
    ax.grid(alpha=0.3, axis="y")

    # (3) T별 표시용 기대값(근사)
    ax = axes[1][0]
    ys2 = [exp_at_H[T] * 100 for T in thresholds]
    ax.bar([f"{T*100:.2f}%" for T in thresholds], ys2, color="seagreen")
    ax.set_title("(3) 임계값별 (확률×이탈폭) 근사 — 클수록 건당 기대 큼")
    ax.set_ylabel("근사 기대값 (%)")
    ax.grid(alpha=0.3, axis="y")

    # (4) 가격 + MA + 밴드 + 이벤트 (마지막 구간만)
    ax = axes[1][1]
    seg = 4320  # 마지막 3일
    s0 = max(0, len(candles) - seg)
    xs_idx = list(range(s0, len(candles)))
    closes = [candles[i]["close"] for i in xs_idx]
    mas = [ma[i] for i in xs_idx]
    ax.plot(xs_idx, closes, color="black", lw=0.6, label="price")
    ax.plot(xs_idx, mas, color="orange", lw=0.9, label=f"MA{args.ma}")
    Tband = 0.01
    upper = [(m * (1 + Tband)) if m else None for m in mas]
    lower = [(m * (1 - Tband)) if m else None for m in mas]
    ax.plot(xs_idx, upper, color="gray", ls=":", lw=0.6)
    ax.plot(xs_idx, lower, color="gray", ls=":", lw=0.6, label="±1% 밴드")
    if events_for_plot:
        for (ei, side, t) in events_for_plot:
            if ei < s0:
                continue
            color = "green" if (t is not None and t <= H) else "red"
            marker = "^" if side == "LONG" else "v"
            ax.scatter([ei], [candles[ei]["close"]], c=color, marker=marker, s=25, zorder=5)
    ax.set_title("(4) 실제 가격/MA/±1%밴드 + 이벤트 (초록=30봉내복귀, 빨강=실패)")
    ax.set_xlabel("봉 인덱스 (최근 3일)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(fig_path(args.out), dpi=110)
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
