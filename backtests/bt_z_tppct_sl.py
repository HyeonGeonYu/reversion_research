"""
BTCUSDT 역추세 — TP는 'Bσ 복귀'의 진입시점 가격%로, SL은 그 %를 대칭 적용.

진입(AND, 양방향):
  - 일봉 30일 z >= +(daily_k) / <= -(daily_k)   (전일 완성봉)
  - 1분봉 10080봉 z >= +3.48 / <= -3.48
청산: 진입 시점에 'z가 Bσ로 복귀하면 얻는 가격%(tp_pct)'를 계산 →
  - TP: 가격이 +tp_pct 도달 (롱 기준; 그 지점이 곧 Bσ 밴드선)
  - SL: 가격이 -tp_pct 도달 (대칭, 고정 가격%)
  봉 내 둘 다 닿으면 손절 우선. tp_pct는 트레이드마다 변동성/진입깊이로 달라짐.
비용: 편도 fee.

사용:
  python backtests/bt_z_tppct_sl.py --symbol BTCUSDT --daily-k 1 --band 1.5
"""
from __future__ import annotations
import sys, os, argparse
from datetime import datetime, timezone
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import _load_cache


def rolling_mean_std(x, w):
    n = len(x)
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
    mean = np.full(n, np.nan); std = np.full(n, np.nan)
    s = cs[w:] - cs[:-w]; s2 = cs2[w:] - cs2[:-w]
    mm = s / w; var = np.maximum(s2 / w - mm * mm, 0.0)
    mean[w - 1:] = mm; std[w - 1:] = np.sqrt(var)
    return mean, std


def prep(symbol, args):
    m1 = _load_cache(symbol, "1"); daily = _load_cache(symbol, "D")
    C = np.array([c["close"] for c in m1], dtype=float)
    H = np.array([c["high"] for c in m1], dtype=float)
    L = np.array([c["low"] for c in m1], dtype=float)
    ts = np.array([c["start"] for c in m1], dtype=np.int64)
    m, sd = rolling_mean_std(C, args.m1_win)
    z1 = np.where(sd > 0, (C - m) / sd, np.nan)
    Cd = np.array([c["close"] for c in daily], dtype=float)
    md, sdd = rolling_mean_std(Cd, args.daily_ma)
    zd = np.where(sdd > 0, (Cd - md) / sdd, np.nan)
    day2idx = {int(d): i for i, d in
               enumerate(np.array([c["start"] for c in daily]) // 86_400_000)}
    prev_idx = np.array([day2idx.get(int(d) - 1, -1) for d in (ts // 86_400_000)])
    zd_at = np.where(prev_idx >= 0, zd[np.clip(prev_idx, 0, len(zd) - 1)], np.nan)
    return C, H, L, m, sd, z1, zd_at, ts


def run(C, H, L, m, sd, z1, zd_at, ts, args):
    K1, Kd, B = args.m1_k, args.daily_k, args.band
    n = len(C); fee2 = 2 * args.fee
    if args.no_daily:
        dlong = np.ones(n, bool); dshort = np.ones(n, bool)
    else:
        dlong = (zd_at <= -Kd); dshort = (zd_at >= Kd)
    trades = []  # (side, ret, bars, win, tp_pct, entry_ts)
    pos = 0; epx = 0.0; ei = 0; tp_p = 0.0; sl_p = 0.0; pct = 0.0
    for i in range(args.m1_win, n):
        zi = z1[i]
        if not np.isfinite(zi):
            continue
        if pos == 0:
            if zi <= -K1 and dlong[i]:
                _tp = m[i] - B * sd[i]; _pct = _tp / C[i] - 1.0
                if _pct > 0:                       # 가드: 밴드<진입깊이라 TP가 평균쪽
                    pos = 1; epx = C[i]; ei = i; tp_p = _tp; pct = _pct
                    sl_p = epx * (1 - pct)
            elif zi >= K1 and dshort[i] and not args.long_only:
                _tp = m[i] + B * sd[i]; _pct = C[i] / _tp - 1.0
                if _pct > 0:
                    pos = -1; epx = C[i]; ei = i; tp_p = _tp; pct = _pct
                    sl_p = epx * (1 + pct)
        elif pos == 1:
            if L[i] <= sl_p:                        # 손절 우선
                trades.append((1, -pct - fee2, i - ei, False, pct, int(ts[ei]))); pos = 0
            elif H[i] >= tp_p:
                trades.append((1, pct - fee2, i - ei, True, pct, int(ts[ei]))); pos = 0
        elif pos == -1:
            if H[i] >= sl_p:
                trades.append((-1, -pct - fee2, i - ei, False, pct, int(ts[ei]))); pos = 0
            elif L[i] <= tp_p:
                trades.append((-1, pct - fee2, i - ei, True, pct, int(ts[ei]))); pos = 0
    return trades


def report(trades, title):
    if not trades:
        print(f"  {title}: 거래 없음"); return
    rets = np.array([t[1] for t in trades]); sides = np.array([t[0] for t in trades])
    bars = np.array([t[2] for t in trades]); pcts = np.array([t[4] for t in trades])
    def line(mask, name):
        r = rets[mask]
        if len(r) == 0:
            print(f"    {name:<5} 거래    0"); return
        pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
        pf = pf_n / pf_d if pf_d > 0 else np.inf
        print(f"    {name:<5} 거래 {len(r):>4} | 승률 {(r>0).mean()*100:5.1f}% | "
              f"평균 {r.mean()*100:+6.3f}% | 누적 {(np.prod(1+r)-1)*100:+8.1f}% | "
              f"PF {pf:5.2f} | 보유 {bars[mask].mean()/60:5.1f}h | 평균브래킷 {pcts[mask].mean()*100:4.2f}%")
    print(f"  {title}")
    line(np.ones(len(rets), bool), "전체")
    line(sides == 1, "롱")
    line(sides == -1, "숏")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--daily-ma", type=int, default=30)
    ap.add_argument("--daily-k", type=float, default=1.0)
    ap.add_argument("--m1-win", type=int, default=10080)
    ap.add_argument("--m1-k", type=float, default=3.48)
    ap.add_argument("--band", type=float, default=1.5, help="TP 복귀 σ (가격%로 환산해 SL 대칭)")
    ap.add_argument("--fee", type=float, default=0.00055)
    ap.add_argument("--long-only", action="store_true", help="숏 제외(추천)")
    ap.add_argument("--no-daily", action="store_true", help="일봉 게이트 제거(1분봉 3.48σ만)")
    args = ap.parse_args()
    gate = "일봉게이트 없음" if args.no_daily else f"일봉 SMA{args.daily_ma}±{args.daily_k}σ"
    print(f"{args.symbol} | {gate} | "
          f"1분봉 {args.m1_win}봉±{args.m1_k}σ | TP=Bσ({args.band})환산% / SL=대칭% | "
          f"{'롱온리 | ' if args.long_only else ''}수수료 편도 {args.fee*100:.3f}%\n")
    C, H, L, m, sd, z1, zd_at, ts = prep(args.symbol, args)
    trades = run(C, H, L, m, sd, z1, zd_at, ts, args)
    report(trades, f"=== 전체 3년: TP복귀 {args.band}σ → 가격% 대칭 브래킷 ===")

    # ── 3개월(90일)별 성적
    print("\n=== 3개월(90일)별 ===")
    qms = 90 * 86_400_000
    base = int(ts[0])
    buckets = {}
    for t in trades:
        q = (t[5] - base) // qms
        buckets.setdefault(q, []).append(t)
    for q in sorted(buckets):
        d0 = datetime.fromtimestamp((base + q*qms)/1000, tz=timezone.utc)
        d1 = datetime.fromtimestamp((base + (q+1)*qms)/1000, tz=timezone.utc)
        r = np.array([x[1] for x in buckets[q]])
        pf_n = r[r > 0].sum(); pf_d = -r[r < 0].sum()
        pf = pf_n / pf_d if pf_d > 0 else np.inf
        print(f"  {d0:%Y-%m-%d} ~ {d1:%m-%d}  거래 {len(r):>3} | 승률 {(r>0).mean()*100:5.1f}% | "
              f"누적 {(np.prod(1+r)-1)*100:+7.1f}% | PF {pf:5.2f}")


if __name__ == "__main__":
    main()
