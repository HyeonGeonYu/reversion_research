"""
MTF 뷰 — 2장 (지표: 볼린저 z-score 기본, RSI 옵션).
  ① 3달치 일봉 캔들 + 일봉 과매수/과매도 표시 (+ 지표 서브플롯)
  ② 거래일(일봉 과매수/과매도)마다 그날 1분봉 캔들 + 방향 맞는 1분 진입점
     - 일봉 과매도일 → 1분 과매도에서 매수만 ★▲자홍
     - 일봉 과매수일 → 1분 과매수에서 매도만 ★▼시안

기본: 볼린저 z=(가격-SMA_N)/σ_N, 과매도 z<=-k / 과매수 z>=+k (변동성 정규화, 대칭).
"""
from __future__ import annotations
import sys, os, argparse, math
from datetime import datetime, timezone
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

DAY_MS = 86_400_000


def indicator(close, kind, period, k, lo, hi):
    """반환 (ind, lo_thr, hi_thr, 라벨, ylim, center, upper, lower).
    과매도=ind<=lo_thr / 과매수=ind>=hi_thr. center/upper/lower=가격 밴드(볼린저만, RSI는 None)."""
    s = pd.Series(close)
    if kind == "rsi":
        d = s.diff()
        ag = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
        al = (-d).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
        rs = ag/al.replace(0, np.nan)
        ind = (100 - 100/(1+rs)).to_numpy()
        return ind, lo, hi, f"RSI{period}", (0, 100), None, None, None
    # bollinger z + 가격 밴드
    sma = s.rolling(period).mean(); sd = s.rolling(period).std(ddof=0)
    z = ((s-sma)/sd).to_numpy()
    return (z, -k, +k, f"z(SMA{period},σ)", None,
            sma.to_numpy(), (sma + k*sd).to_numpy(), (sma - k*sd).to_numpy())


def draw_candles(ax, O, H, L, C, x=None):
    n = len(C); x = x if x is not None else list(range(n))
    col = ["#2ca02c" if C[k] >= O[k] else "#d62728" for k in range(n)]
    ax.vlines(x, L, H, colors=col, lw=0.6, zorder=2)
    bottoms = [min(O[k], C[k]) for k in range(n)]
    heights = [max(abs(C[k]-O[k]), (H[k]-L[k])*0.001) for k in range(n)]
    ax.bar(x, heights, bottom=bottoms, width=0.7, color=col, edgecolor=col, linewidth=0.2, zorder=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--indicator", choices=["bollinger", "rsi"], default="bollinger")
    ap.add_argument("--period-d", type=int, default=100, help="일봉 지표 기간")
    ap.add_argument("--period-m", type=int, default=100, help="1분 지표 기간")
    ap.add_argument("--kd", type=float, default=1.5, help="일봉 볼린저 σ배수(작을수록 자주)")
    ap.add_argument("--km", type=float, default=2.5, help="1분 볼린저 σ배수")
    ap.add_argument("--lo", type=float, default=30.0, help="RSI 과매도")
    ap.add_argument("--hi", type=float, default=70.0, help="RSI 과매수")
    ap.add_argument("--max-days", type=int, default=16)
    ap.add_argument("--cooldown-min", type=int, default=240, help="진입 후 재진입 금지(분)")
    args = ap.parse_args()

    daily = fetch_klines_bybit(args.symbol, "D", days=1095)
    dO=np.array([x['open'] for x in daily]); dC=np.array([x['close'] for x in daily])
    dH=np.array([x['high'] for x in daily]); dL=np.array([x['low'] for x in daily]); dts=[x['start'] for x in daily]
    dInd, dlo, dhi, dlabel, dylim, dcen, dup, ddn = indicator(dC, args.indicator, args.period_d, args.kd, args.lo, args.hi)
    nd = len(dC)
    lo_i = max(0, nd - args.window_days); win = list(range(lo_i, nd))

    # ── 이미지 ① ──
    xs = win; K = list(range(len(xs)))
    dates = [datetime.fromtimestamp(dts[i]/1000, tz=timezone.utc) for i in xs]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1], sharex=True)
    draw_candles(ax1, [dO[i] for i in xs], [dH[i] for i in xs], [dL[i] for i in xs], [dC[i] for i in xs], K)
    if dcen is not None:
        ax1.plot(K, [dcen[i] for i in xs], color="orange", lw=1.0, zorder=4, label=f"SMA{args.period_d}")
        ax1.plot(K, [dup[i] for i in xs], color="cyan", ls="--", lw=0.9, zorder=4, label=f"+{args.kd:g}σ")
        ax1.plot(K, [ddn[i] for i in xs], color="magenta", ls="--", lw=0.9, zorder=4, label=f"-{args.kd:g}σ")
        ax1.legend(fontsize=8, loc="upper left")
    trading = []
    for k, i in enumerate(xs):
        v = dInd[i]
        if not np.isfinite(v): continue
        if v <= dlo:
            ax1.scatter([k], [dL[i]], color="magenta", s=70, marker="*", edgecolor="black", linewidth=0.4, zorder=6)
            trading.append((i, "long"))
        elif v >= dhi:
            ax1.scatter([k], [dH[i]], color="cyan", s=70, marker="*", edgecolor="black", linewidth=0.4, zorder=6)
            trading.append((i, "short"))
    ax1.set_title(f"{args.symbol} 일봉 3달 ({dates[0]:%Y-%m-%d}~{dates[-1]:%Y-%m-%d})  ★자홍=과매도(롱일) ★시안=과매수(숏일)  지표 {dlabel} [{dlo:g}/{dhi:g}]")
    ax1.grid(alpha=0.25)
    ax2.plot(K, [dInd[i] for i in xs], color="purple", lw=1.0)
    ax2.axhline(dhi, color="cyan", ls="--", lw=0.8); ax2.axhline(dlo, color="magenta", ls="--", lw=0.8)
    if args.indicator == "bollinger":
        ax2.axhline(0, color="gray", lw=0.5)
    ax2.fill_between(K, dlo, dhi, color="gray", alpha=0.08)
    if dylim: ax2.set_ylim(*dylim)
    ax2.set_ylabel(dlabel); ax2.grid(alpha=0.25)
    ticks = [k for k in K if dates[k].day == 1 or k == 0]
    ax2.set_xticks(ticks); ax2.set_xticklabels([f"{dates[k]:%m/%d}" for k in ticks])
    plt.tight_layout(); plt.savefig(fig_path("mtf_daily.png"), dpi=120); plt.close()
    print(f"거래일 {len(trading)}개 (롱일 {sum(1 for _,s in trading if s=='long')}, 숏일 {sum(1 for _,s in trading if s=='short')})")
    print("이미지① → figures/mtf_daily.png")

    # ── 이미지 ② ──
    if not trading:
        print("거래일 없음 — 이미지② 생략"); return
    show = trading[:args.max_days]
    if len(trading) > args.max_days:
        print(f"(거래일 {len(trading)}개 중 처음 {args.max_days}개만 표시)")

    m1 = fetch_klines_bybit(args.symbol, "1", days=1095)
    mts = np.array([x['start'] for x in m1])
    mO=np.array([x['open'] for x in m1]); mC=np.array([x['close'] for x in m1])
    mH=np.array([x['high'] for x in m1]); mL=np.array([x['low'] for x in m1])
    mInd, mlo, mhi, mlabel, _, mcen, mup, mdn = indicator(mC, args.indicator, args.period_m, args.km, args.lo, args.hi)

    nd2 = len(show); cols = 4; rows = math.ceil(nd2/cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols*5.2, rows*3.2))
    axes = np.array(axes).flatten() if nd2 > 1 else [axes]
    for qi, (di, sidedir) in enumerate(show):
        d_start = dts[di]; d_end = d_start + DAY_MS
        sel = np.where((mts >= d_start) & (mts < d_end))[0]
        ax = axes[qi]
        if len(sel) == 0:
            ax.set_title("(1분 데이터 없음)", fontsize=9); ax.axis("off"); continue
        K2 = list(range(len(sel)))
        draw_candles(ax, mO[sel], mH[sel], mL[sel], mC[sel], K2)
        if mcen is not None:
            ax.plot(K2, [mcen[gi] for gi in sel], color="orange", lw=0.8, zorder=4)
            ax.plot(K2, [mup[gi] for gi in sel], color="cyan", ls="--", lw=0.7, zorder=4)
            ax.plot(K2, [mdn[gi] for gi in sel], color="magenta", ls="--", lw=0.7, zorder=4)
        # debounce: 평균(z=0) 복귀해야 재무장 + 쿨다운(분)
        nent = 0; armed = True; last_k = -10**9; mid_v = 0.0 if args.indicator == "bollinger" else 50.0
        for k, gi in enumerate(sel):
            v = mInd[gi]
            if not np.isfinite(v): continue
            if sidedir == "long":
                if armed and v <= mlo and (k - last_k) >= args.cooldown_min:
                    ax.scatter([k], [mL[gi]], color="magenta", s=55, marker="^", edgecolor="black", linewidth=0.5, zorder=6); nent += 1; armed = False; last_k = k
                elif v >= mid_v:
                    armed = True
            else:
                if armed and v >= mhi and (k - last_k) >= args.cooldown_min:
                    ax.scatter([k], [mH[gi]], color="cyan", s=55, marker="v", edgecolor="black", linewidth=0.5, zorder=6); nent += 1; armed = False; last_k = k
                elif v <= mid_v:
                    armed = True
        d0 = datetime.fromtimestamp(d_start/1000, tz=timezone.utc)
        tag = "롱일(과매도)" if sidedir == "long" else "숏일(과매수)"
        ax.set_title(f"{d0:%Y-%m-%d} {tag} | 진입 {nent}", fontsize=9)
        ax.tick_params(labelsize=6); ax.grid(alpha=0.2)
        hh = [k for k in K2 if k % 240 == 0]
        ax.set_xticks(hh); ax.set_xticklabels([f"{(k//60):02d}h" for k in hh], fontsize=6)
    for j in range(nd2, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{args.symbol} 거래일별 1분봉 + 방향제한 진입 (롱일=과매도매수▲ / 숏일=과매수매도▼)  1분지표 {mlabel}", fontsize=12)
    plt.tight_layout(rect=[0,0,1,0.98]); plt.savefig(fig_path("mtf_intraday.png"), dpi=120); plt.close()
    print("이미지② → figures/mtf_intraday.png")


if __name__ == "__main__":
    main()
