"""
목표 복귀확률을 만족하는 최대 T를 심볼별로 탐색 (horizon 고정, 오프라인 read-only).

예: "MA100, 30분내 복귀확률 ≥ 0.5 가 되는 최대 T는?"
"""
from __future__ import annotations
import argparse
from reversion_calibrator import fetch_klines_bybit, calibrate

# 작은 이탈까지 보는 미세 그리드 (50% 교차는 보통 작은 T 영역)
FINE = [0.0010, 0.0015, 0.0020, 0.0025, 0.0030, 0.0040,
        0.0050, 0.0060, 0.0075, 0.0100, 0.0150, 0.0200]


def find_max_T(rows, target: float, min_n: int):
    """prob >= target 이고 n >= min_n 인 것 중 가장 큰 T."""
    cands = [r for r in rows if r.get("n", 0) >= min_n and r.get("p_revert", 0) >= target]
    return max(cands, key=lambda r: r["T"]) if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--target", type=float, default=0.5)
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--ma", type=int, default=100)
    args = ap.parse_args()

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT"]

    print(f"조건: MA{args.ma}, horizon={args.horizon}봉, 복귀확률 ≥ {args.target}, "
          f"기간 {args.days}일, 최소표본 {args.min_n}\n")

    summary = []
    for sym in symbols:
        try:
            candles = fetch_klines_bybit(sym, "1", days=args.days)
            res = calibrate(candles, ma_period=args.ma, horizon_bars=args.horizon, thresholds=FINE)
            rows = res["rows"]

            print(f"=== {sym} ({len(candles)}봉) ===")
            print(f"{'T':>7} {'건수':>5} {'복귀확률':>7} {'평균복귀':>7} {'손익비':>6} {'기대값':>8}")
            for r in rows:
                if r.get("n", 0) == 0:
                    continue
                from reversion_calibrator import _fmt_dur_min
                print(f"{r['T']*100:>6.2f}% {r['n']:>5} {r['p_revert']*100:>6.1f}% "
                      f"{_fmt_dur_min(r['avg_bars']):>7} {r['rr']:>6.2f} {r['expectancy']*100:>7.2f}%")

            best = find_max_T(rows, args.target, args.min_n)
            if best:
                print(f"  ▶ 복귀확률 ≥ {args.target} 최대 T = {best['T']*100:.2f}% "
                      f"(복귀 {best['p_revert']*100:.1f}%, n={best['n']}, 손익비 {best['rr']:.2f})\n")
                summary.append((sym, best['T'], best['p_revert'], best['n']))
            else:
                print(f"  ▶ {args.target} 이상 도달 T 없음 (가장 작은 T도 미달)\n")
                summary.append((sym, None, None, None))
        except Exception as e:
            print(f"[{sym}] 실패: {e}\n")
            summary.append((sym, None, None, None))

    print("=" * 40)
    print(f"요약 - 복귀확률 >= {args.target} 최대 T")
    for sym, T, p, n in summary:
        if T is None:
            print(f"  {sym:10s} : 없음")
        else:
            print(f"  {sym:10s} : T = {T*100:.2f}%  (복귀 {p*100:.0f}%, n={n})")


if __name__ == "__main__":
    main()
