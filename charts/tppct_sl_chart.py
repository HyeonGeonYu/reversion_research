"""
TP=Bσ환산% / SL=대칭% 전략을 1년치(기본) 1분봉 차트로 시각화.

진입: 일봉 SMA30 ±(daily_k)σ + 1분봉 10080봉 ±(m1_k)σ
청산: 진입시 z=Bσ 복귀 가격%(tp_pct) → TP +tp_pct / SL -tp_pct (대칭, 고정)
표시: 종가 + MA10080 + ±m1_kσ 진입밴드, ▲롱/▼숏 진입, ●초록수익/빨강손실,
      각 트레이드 TP선(초록)·SL선(빨강) 가로 표시.

사용:
  python charts/tppct_sl_chart.py --symbol BTCUSDT --daily-k 1 --band 1.5 --days 365
"""
from __future__ import annotations
import sys, os, argparse
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fig_path, _load_cache

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
for _f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
    try:
        matplotlib.rcParams["font.family"] = _f; break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False


def rolling_mean_std(x, w):
    n = len(x)
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
    mean = np.full(n, np.nan); std = np.full(n, np.nan)
    s = cs[w:] - cs[:-w]; s2 = cs2[w:] - cs2[:-w]
    mm = s / w; var = np.maximum(s2 / w - mm * mm, 0.0)
    mean[w - 1:] = mm; std[w - 1:] = np.sqrt(var)
    return mean, std


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--daily-ma", type=int, default=30)
    ap.add_argument("--daily-k", type=float, default=1.0)
    ap.add_argument("--m1-win", type=int, default=10080)
    ap.add_argument("--m1-k", type=float, default=3.48)
    ap.add_argument("--band", type=float, default=1.5)
    ap.add_argument("--fee", type=float, default=0.00055)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--start", default=None, help="시작일 YYYY-MM-DD(기본=최근 days일)")
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--no-daily", action="store_true", help="일봉 게이트 제거")
    ap.add_argument("--out", default="tppct_sl_1y.png")
    args = ap.parse_args()
    K1, Kd, B = args.m1_k, args.daily_k, args.band

    m1 = _load_cache(args.symbol, "1"); daily = _load_cache(args.symbol, "D")
    C = np.array([c["close"] for c in m1], dtype=float)
    H = np.array([c["high"] for c in m1], dtype=float)
    L = np.array([c["low"] for c in m1], dtype=float)
    ts = np.array([c["start"] for c in m1], dtype=np.int64)
    n = len(C)
    m, sd = rolling_mean_std(C, args.m1_win)
    z1 = np.where(sd > 0, (C - m) / sd, np.nan)
    Cd = np.array([c["close"] for c in daily], dtype=float)
    md, sdd = rolling_mean_std(Cd, args.daily_ma)
    zd = np.where(sdd > 0, (Cd - md) / sdd, np.nan)
    day2idx = {int(d): i for i, d in
               enumerate(np.array([c["start"] for c in daily]) // 86_400_000)}
    prev_idx = np.array([day2idx.get(int(d) - 1, -1) for d in (ts // 86_400_000)])
    zd_at = np.where(prev_idx >= 0, zd[np.clip(prev_idx, 0, len(zd) - 1)], np.nan)
    if args.no_daily:
        dlong = np.ones(n, bool); dshort = np.ones(n, bool)
    else:
        dlong = (zd_at <= -Kd); dshort = (zd_at >= Kd)

    # ── 백테스트 (인덱스·레벨 기록)
    trades = []  # (side, ei, xi, ret, win, tp_p, sl_p)
    pos = 0; epx = 0.0; ei = 0; tp_p = 0.0; sl_p = 0.0; pct = 0.0; fee2 = 2*args.fee
    for i in range(args.m1_win, n):
        zi = z1[i]
        if not np.isfinite(zi):
            continue
        if pos == 0:
            if zi <= -K1 and dlong[i]:
                pos = 1; epx = C[i]; ei = i
                tp_p = m[i] - B*sd[i]; pct = tp_p/epx - 1; sl_p = epx*(1-pct)
            elif zi >= K1 and dshort[i] and not args.long_only:
                pos = -1; epx = C[i]; ei = i
                tp_p = m[i] + B*sd[i]; pct = epx/tp_p - 1; sl_p = epx*(1+pct)
        elif pos == 1:
            if L[i] <= sl_p:
                trades.append((1, ei, i, -pct-fee2, False, tp_p, sl_p)); pos = 0
            elif H[i] >= tp_p:
                trades.append((1, ei, i, pct-fee2, True, tp_p, sl_p)); pos = 0
        elif pos == -1:
            if H[i] >= sl_p:
                trades.append((-1, ei, i, -pct-fee2, False, tp_p, sl_p)); pos = 0
            elif L[i] <= tp_p:
                trades.append((-1, ei, i, pct-fee2, True, tp_p, sl_p)); pos = 0

    # ── 구간 선택
    if args.start:
        t0 = int(datetime.strptime(args.start, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp()*1000)
        s0 = int(np.searchsorted(ts, t0))
    else:
        s0 = max(args.m1_win, n - args.days*1440)
    s1 = min(s0 + args.days*1440, n)

    bu = m + K1*sd; bd = m - K1*sd
    step = 10
    xs = np.arange(s0, s1, step)
    dts = [datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc) for i in xs]

    fig, ax = plt.subplots(figsize=(17, 8))
    ax.plot(dts, C[xs], color="#333", lw=0.5, zorder=2, label="종가")
    ax.plot(dts, m[xs], color="orange", lw=0.9, zorder=3, label="MA10080")
    ax.plot(dts, bu[xs], color="red", ls="--", lw=0.6, zorder=3, label=f"±{K1}σ 진입")
    ax.plot(dts, bd[xs], color="blue", ls="--", lw=0.6, zorder=3)

    def D(i): return datetime.fromtimestamp(ts[min(i, n-1)]/1000, tz=timezone.utc)
    ntr = 0; wins = 0; cum = 1.0
    for (side, e, x, ret, win, tpp, slp) in trades:
        if not (s0 <= e < s1):
            continue
        ntr += 1; wins += win; cum *= (1+ret)
        de, dx = D(e), D(x)
        ax.scatter([de], [C[e]], marker=("^" if side == 1 else "v"),
                   s=70, color="black", zorder=7)
        ax.scatter([dx], [C[min(x,s1-1)]], marker="o", s=45,
                   color=("#2ca02c" if win else "#d62728"),
                   edgecolor="black", linewidth=0.4, zorder=7)
        # TP/SL 가로선 (진입~청산 구간)
        ax.hlines(tpp, de, dx, color="#2ca02c", lw=0.6, alpha=0.6, zorder=4)
        ax.hlines(slp, de, dx, color="#d62728", lw=0.6, alpha=0.6, zorder=4)

    d0, d1 = D(s0), D(s1-1)
    ax.set_title(f"{args.symbol}  {d0:%Y-%m-%d} ~ {d1:%Y-%m-%d}  "
                 f"TP={B}σ환산%/SL대칭%  (일봉{Kd}σ+1분봉{K1}σ 진입)  "
                 f"거래 {ntr}건 승률 {wins/ntr*100 if ntr else 0:.0f}% 누적 {(cum-1)*100:+.1f}%  "
                 f"▲롱▼숏 ●초록수익/빨강손실", fontsize=11)
    ax.legend(fontsize=8, loc="best"); ax.grid(alpha=0.25); ax.set_ylabel("Price")
    plt.tight_layout()
    out = fig_path(args.out)
    plt.savefig(out, dpi=120)
    print(f"저장: {out}  (구간 거래 {ntr}건, 승률 {wins/ntr*100 if ntr else 0:.0f}%, 누적 {(cum-1)*100:+.1f}%)")


if __name__ == "__main__":
    main()
