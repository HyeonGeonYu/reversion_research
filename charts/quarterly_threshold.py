"""
분기별(3개월 윈도우) "1터치 임계값 T" — 1분봉 기준.

각 90일 윈도우에서, 가격이 MA100 ±T 밴드를 '딱 1번'만 터치(크로스)하는 T를 이분탐색으로 구하고,
분기별로 T값을 표/그래프로 보여준다. (윈도우/타깃 변경 가능)

사용:
  python quarterly_threshold.py                 # 캐시된 1분봉 전체를 90일 단위로
  python quarterly_threshold.py --target 1 --win-days 90 --ma 100
"""
from __future__ import annotations
import sys, os, argparse
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

MIN_INT = 60  # 터치 최소간격(분) = 1시간


def count_cross(C, Hi, Lo, ma, lo, hi, thr):
    cnt = 0; state = None; lastU = lastD = -10**9
    for i in range(lo, hi):
        m = ma[i]
        if m is None:
            continue
        up = m*(1+thr); dn = m*(1-thr)
        if state in ("below", "in") and Hi[i] > up and (i-lastU) > MIN_INT:
            cnt += 1; lastU = i
        if state in ("above", "in") and Lo[i] < dn and (i-lastD) > MIN_INT:
            cnt += 1; lastD = i
        cl = C[i]; state = "above" if cl > up else ("below" if cl < dn else "in")
    return cnt


def find_T(C, Hi, Lo, ma, lo, hi, target, maxthr=0.6):
    """크로스 수가 target 이하가 되는 최소 T (이분탐색)."""
    left, right = 0.0, maxthr; opt = right
    for _ in range(34):
        mid = (left+right)/2
        if count_cross(C, Hi, Lo, ma, lo, hi, mid) > target:
            left = mid
        else:
            opt = mid; right = mid
    return opt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=1095)   # 캐시에 있는 만큼만 사용됨
    ap.add_argument("--win-days", type=int, default=90)
    ap.add_argument("--target", type=int, default=1)
    ap.add_argument("--ma", type=int, default=100)
    ap.add_argument("--out", default="quarterly_threshold.png")
    args = ap.parse_args()

    c1 = fetch_klines_bybit(args.symbol, "1", days=args.days)
    C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
    ts=[x['start'] for x in c1]; ma=_ma_hlc3(c1, args.ma)
    n = len(C)
    qwin = args.win_days * 1440
    nq = n // qwin
    print(f"{args.symbol}: {n:,}분봉 = {nq}개 {args.win_days}일 윈도우 "
          f"({datetime.fromtimestamp(ts[0]/1000,tz=timezone.utc):%Y-%m-%d}~"
          f"{datetime.fromtimestamp(ts[-1]/1000,tz=timezone.utc):%Y-%m-%d})\n")

    labels = []; Ts = []
    print(f"{'윈도우':>14} {'T(1터치)':>9} {'검증크로스':>8}")
    for q in range(nq):
        lo = q*qwin; hi = (q+1)*qwin
        lo = max(lo, args.ma)  # MA 워밍업
        T = find_T(C, Hi, Lo, ma, lo, hi, args.target)
        cc = count_cross(C, Hi, Lo, ma, lo, hi, T)
        d0 = datetime.fromtimestamp(ts[q*qwin]/1000, tz=timezone.utc)
        lab = f"{d0:%y-%m}"
        labels.append(lab); Ts.append(T*100)
        print(f"{d0:%Y-%m-%d}  {T*100:>7.2f}%  {cc:>6}회")

    # 그래프
    fig, ax = plt.subplots(figsize=(max(8, nq*1.1), 5))
    bars = ax.bar(labels, Ts, color="steelblue")
    for b, t in zip(bars, Ts):
        ax.text(b.get_x()+b.get_width()/2, t+0.1, f"{t:.1f}%", ha="center", fontsize=9)
    ax.set_title(f"{args.symbol} 분기별({args.win_days}일) '1터치' 임계값 T  (MA{args.ma}, 1분봉)")
    ax.set_ylabel("T (MA 대비 이격 %)")
    ax.set_xlabel("윈도우 시작(년-월)")
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(fig_path(args.out), dpi=120)
    print(f"\n저장 → {args.out}")


if __name__ == "__main__":
    main()
