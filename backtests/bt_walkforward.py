"""
S1 워크포워드(적응형) — 과거 윈도우에서 최적 (K1, W) 선택 → 다음 블록에 적용.

- 학습창: 직전 train-days일 (롤링)
- 재최적화: 매 test-days일마다
- 그리드: K1 ∈ {2.0,2.5,3.0} × W(브래킷폭=K1−B) ∈ {0.3,0.5,0.75}
  학습창 누적수익 최대인 조합 채택(최소거래 미달 시 기본값).
- OOS: 첫 train-days 이후(최근 ~2년)만 집계. 고정 베이스라인과 비교.

사용:
  python backtests/bt_walkforward.py --symbol BTCUSDT
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


def run_block(C, H, L, m, sd, z1, ts, s, e, K1, W, CD, fee2, warm):
    """[s,e) 구간 백테스트 → 거래수익 리스트. (flat에서 시작)"""
    B = K1 - W
    tr = []; pos = 0; epx = 0.0; tpp = 0.0; slp = 0.0; pct = 0.0; last = -10**18
    i0 = max(s, warm)
    for i in range(i0, e):
        zi = z1[i]
        if not np.isfinite(zi):
            continue
        if pos == 0:
            if zi <= -K1 and (ts[i] - last) >= CD * 60000:
                _tp = m[i] - B * sd[i]; _p = _tp / C[i] - 1
                if _p > 0:
                    pos = 1; epx = C[i]; tpp = _tp; pct = _p; slp = epx * (1 - pct)
        elif pos == 1:
            if L[i] <= slp:
                tr.append(-pct - fee2); pos = 0; last = ts[i]
            elif H[i] >= tpp:
                tr.append(pct - fee2); pos = 0; last = ts[i]
    return tr


def cum(r):
    return float(np.prod([1 + x for x in r]) - 1) if r else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--train-days", type=int, default=365)
    ap.add_argument("--test-days", type=int, default=90)
    ap.add_argument("--cd", type=int, default=720)
    ap.add_argument("--fee", type=float, default=0.00055)
    ap.add_argument("--min-trades", type=int, default=10)
    args = ap.parse_args()
    warm = 10080; CD = args.cd; fee2 = 2 * args.fee
    K1s = [2.0, 2.5, 3.0]; Ws = [0.3, 0.5, 0.75]
    DEF = (2.5, 0.5)

    m1 = _load_cache(args.symbol, "1")
    C = np.array([c["close"] for c in m1]); H = np.array([c["high"] for c in m1])
    L = np.array([c["low"] for c in m1]); ts = np.array([c["start"] for c in m1], dtype=np.int64)
    n = len(C)
    m, sd = rolling_mean_std(C, 10080); z1 = np.where(sd > 0, (C - m) / sd, np.nan)

    tr_w = args.train_days * 1440; te_w = args.test_days * 1440
    start = warm + tr_w                      # 첫 OOS 시작
    oos = []; oos_fixed = []; picks = []
    bs = start
    while bs < n:
        be = min(bs + te_w, n)
        # 학습창에서 최적 (K1,W)
        ts0 = bs - tr_w
        best = (-1e9, DEF)
        for K1 in K1s:
            for W in Ws:
                rtr = run_block(C, H, L, m, sd, z1, ts, ts0, bs, K1, W, CD, fee2, warm)
                if len(rtr) >= args.min_trades:
                    sc = cum(rtr)
                    if sc > best[0]:
                        best = (sc, (K1, W))
        K1b, Wb = best[1]
        # OOS 적용
        otr = run_block(C, H, L, m, sd, z1, ts, bs, be, K1b, Wb, CD, fee2, warm)
        ftr = run_block(C, H, L, m, sd, z1, ts, bs, be, DEF[0], DEF[1], CD, fee2, warm)
        oos += otr; oos_fixed += ftr
        d0 = datetime.fromtimestamp(ts[bs] / 1000, tz=timezone.utc)
        picks.append((d0, K1b, Wb, len(otr), cum(otr) * 100, cum(ftr) * 100))
        bs = be

    print(f"{args.symbol} 워크포워드 | 학습 {args.train_days}일 롤링 / 재최적 {args.test_days}일 / 쿨다운{CD}분")
    print(f"그리드 K1{K1s} × W{Ws}, 학습창 누적수익 최대 채택 (최소 {args.min_trades}거래)\n")
    print(f"{'블록시작':>12} {'K1':>4} {'W':>5} {'B':>5} {'거래':>4} {'적응누적%':>9} {'고정누적%':>9}")
    for (d0, K1b, Wb, nt, oc, fc) in picks:
        print(f"{d0:%Y-%m-%d} {K1b:>4.1f} {Wb:>5.2f} {K1b-Wb:>5.2f} {nt:>4} {oc:>+8.1f}% {fc:>+8.1f}%")

    def summ(r, name):
        if not r:
            print(f"  {name}: 거래없음"); return
        r = np.array(r); pf = r[r > 0].sum() / (-r[r < 0].sum()) if (r < 0).any() else 99
        eq = np.cumprod(1 + r); dd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100
        print(f"  {name:>14}: 거래{len(r):>4} 승률{(r>0).mean()*100:>4.0f}% 거래당{r.mean()*100:>+6.3f}% "
              f"누적{(np.prod(1+r)-1)*100:>+7.1f}% PF{pf:>4.2f} MDD{dd:>5.0f}%")
    print(f"\n=== OOS 종합 (최근 ~{(n-start)/1440/365:.1f}년) ===")
    summ(oos, "적응형(walk-fwd)")
    summ(oos_fixed, "고정(2.5/0.5)")


if __name__ == "__main__":
    main()
