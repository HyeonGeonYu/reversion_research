"""
최종 추천 역추세 전략 — 3년 종합 분석.

세팅: 롱온리 · 일봉게이트 없음 · 1분봉 10080봉 3.48σ 과매도 진입
      · TP=Bσ(1.5)환산% / SL=대칭% · 청산후 쿨다운
출력: 전체/연도별 성적, 최대낙폭(MDD), 쿨다운 비교, 에쿼티 커브.

사용:
  python backtests/bt_final_report.py --symbol BTCUSDT --cooldown 1440
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


def backtest(C, H, L, m, sd, z1, args, cooldown):
    K1, B = args.m1_k, args.band; n = len(C); fee2 = 2 * args.fee
    ts = args._ts
    trades = []  # (entry_ts, exit_ts, ret, win, bars)
    pos = 0; epx = 0; ei = 0; tpp = 0; slp = 0; pct = 0; last = -10**18
    for i in range(args.m1_win, n):
        zi = z1[i]
        if not np.isfinite(zi):
            continue
        if pos == 0:
            if zi <= -K1 and (ts[i] - last) >= cooldown * 60000:
                _tp = m[i] - B * sd[i]; _pct = _tp / C[i] - 1
                if _pct > 0:                       # 가드: TP가 진입가보다 위(평균쪽)일 때만
                    pos = 1; epx = C[i]; ei = i; tpp = _tp; pct = _pct; slp = epx * (1 - pct)
        elif pos == 1:
            if L[i] <= slp:
                trades.append((int(ts[ei]), int(ts[i]), -pct - fee2, False, i - ei)); pos = 0; last = ts[i]
            elif H[i] >= tpp:
                trades.append((int(ts[ei]), int(ts[i]), pct - fee2, True, i - ei)); pos = 0; last = ts[i]
    return trades


def mdd(rets):
    eq = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(eq)
    return ((eq - peak) / peak).min() * 100


def stats(trades):
    if not trades:
        return None
    r = np.array([t[2] for t in trades])
    pf = r[r > 0].sum() / (-r[r < 0].sum()) if (r < 0).any() else np.inf
    bars = np.array([t[4] for t in trades])
    return dict(n=len(r), win=(r > 0).mean()*100, avg=r.mean()*100,
               cum=(np.prod(1+r)-1)*100, pf=pf, mdd=mdd(r), hold=bars.mean()/60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--m1-win", type=int, default=10080)
    ap.add_argument("--m1-k", type=float, default=3.48)
    ap.add_argument("--band", type=float, default=1.5)
    ap.add_argument("--fee", type=float, default=0.00055)
    ap.add_argument("--cooldown", type=int, default=1440, help="청산후 쿨다운(분)")
    ap.add_argument("--out", default="final_equity.png")
    args = ap.parse_args()

    m1 = _load_cache(args.symbol, "1")
    C = np.array([c["close"] for c in m1], dtype=float)
    H = np.array([c["high"] for c in m1], dtype=float)
    L = np.array([c["low"] for c in m1], dtype=float)
    ts = np.array([c["start"] for c in m1], dtype=np.int64)
    args._ts = ts
    m, sd = rolling_mean_std(C, args.m1_win)
    z1 = np.where(sd > 0, (C - m) / sd, np.nan)

    print(f"{args.symbol} 최종 역추세 (롱온리·10080 {args.m1_k}σ·TP/SL={args.band}σ환산%·쿨다운 {args.cooldown}분)\n")

    # 쿨다운 비교
    print("=== 쿨다운 비교 (3년 전체) ===")
    print(f"{'쿨다운':>8} {'거래':>5} {'승률':>6} {'누적%':>9} {'PF':>5} {'MDD%':>7} {'평균보유':>8}")
    for cd in [0, 1440, 4320]:
        s = stats(backtest(C, H, L, m, sd, z1, args, cd))
        lab = {0: "없음", 1440: "1일", 4320: "3일"}[cd]
        print(f"{lab:>8} {s['n']:>5} {s['win']:>5.1f}% {s['cum']:>+8.1f}% {s['pf']:>5.2f} "
              f"{s['mdd']:>6.1f}% {s['hold']:>6.1f}h")

    # 선택 쿨다운 상세
    trades = backtest(C, H, L, m, sd, z1, args, args.cooldown)
    s = stats(trades)
    print(f"\n=== 채택: 쿨다운 {args.cooldown}분 ===")
    print(f"  거래 {s['n']} | 승률 {s['win']:.1f}% | 거래당평균 {s['avg']:+.3f}% | "
          f"누적 {s['cum']:+.1f}% | PF {s['pf']:.2f} | MDD {s['mdd']:.1f}% | 평균보유 {s['hold']:.1f}h")

    # 연도별
    print("\n=== 연도별 ===")
    print(f"{'연도':>6} {'거래':>5} {'승률':>6} {'누적%':>9} {'PF':>5}")
    by = {}
    for t in trades:
        y = datetime.fromtimestamp(t[0]/1000, tz=timezone.utc).year
        by.setdefault(y, []).append(t)
    for y in sorted(by):
        s2 = stats(by[y])
        print(f"{y:>6} {s2['n']:>5} {s2['win']:>5.1f}% {s2['cum']:>+8.1f}% {s2['pf']:>5.2f}")

    # 에쿼티 커브
    trades.sort(key=lambda t: t[1])
    r = np.array([t[2] for t in trades])
    eq = (np.cumprod(1 + r) - 1) * 100
    dts = [datetime.fromtimestamp(t[1]/1000, tz=timezone.utc) for t in trades]
    peak = np.maximum.accumulate(np.cumprod(1+r))
    dd = (np.cumprod(1+r) - peak) / peak * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(dts, eq, color="#1f77b4", lw=1.6)
    ax1.axhline(0, color="gray", ls=":", lw=0.8)
    ax1.set_title(f"{args.symbol} 최종 역추세 누적수익  롱온리·10080 {args.m1_k}σ·TP/SL {args.band}σ%·쿨다운{args.cooldown//60}h  "
                  f"거래 {s['n']} 승률 {s['win']:.0f}% 누적 {s['cum']:+.0f}% PF {s['pf']:.2f} MDD {s['mdd']:.0f}%", fontsize=11)
    ax1.set_ylabel("누적수익 %"); ax1.grid(alpha=0.25)
    ax2.fill_between(dts, dd, 0, color="#d62728", alpha=0.4)
    ax2.set_ylabel("낙폭 %"); ax2.grid(alpha=0.25)
    plt.tight_layout()
    out = fig_path(args.out)
    plt.savefig(out, dpi=120)
    print(f"\n에쿼티 커브 저장: {out}")


if __name__ == "__main__":
    main()
