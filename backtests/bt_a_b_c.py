"""
(a, b, c) 시뮬레이션 — BTCUSDT 1년, 1일봉+1분봉 동시이격 진입, ±c 청산(timeout 없음).

게임:
  진입: 1일봉이 일봉MA100에서 a% 이상 이격 AND 1분봉이 1분MA100에서 b% 이상 이격 (같은 방향).
  청산: 진입가 ±c% 도달 시 (보유시간 제한 없음 → 모두 +c/-c로 결판, 데이터끝 미해결만 제외).
  승=+c 먼저, 패=-c 먼저. 같은봉 동시도달=보수적 손절(패).
제약:
  빈도가 하루 너무 많으면 안 됨 → b는 0.5% 이상에서 탐색, 결과에 '하루 거래수' 표시.
순기대 = (2*승률-1)*c - 수수료(env FEE, 기본 테이커 0.11%). timeout 없으니 환상 없음.
"""
from __future__ import annotations
import sys, os, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE = float(os.environ.get("FEE", "0.0011"))
DAY_MS = 86_400_000
MA_P = 100

A_GRID = [0.0, 0.02, 0.05, 0.10]                 # 일봉 이격
B_GRID = [0.005, 0.0075, 0.01, 0.015, 0.02]      # 1분봉 이격 (>=0.5%)
C_GRID = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03]  # 브래킷


def simulate(C, Hi, Lo, ma1, ts, daily, mad, a, b, c):
    n = len(C)
    starts = [d["start"] for d in daily]

    def ddev(ts_ms):
        j = bisect.bisect_right(starts, ts_ms - DAY_MS) - 1
        if j < 0 or mad[j] is None:
            return None
        return (daily[j]["close"] - mad[j]) / mad[j]

    wins = losses = unresolved = 0
    i = MA_P; armed = True
    while i < n:
        m = ma1[i]
        if m is None:
            i += 1; continue
        d = (C[i] - m) / m
        if armed and abs(d) >= b:
            side = 1 if d <= -b else -1
            dd = ddev(ts[i])
            ok = (dd is not None) and ((dd <= -a) if side == 1 else (dd >= a))
            if not ok:
                i += 1; continue
            P0 = C[i]
            if side == 1: tp = P0*(1+c); sl = P0*(1-c)
            else:         tp = P0*(1-c); sl = P0*(1+c)
            res = None; xi = None
            k = i + 1
            while k < n:
                if side == 1: ht = Hi[k] >= tp; hs = Lo[k] <= sl
                else:         ht = Lo[k] <= tp; hs = Hi[k] >= sl
                if ht and hs: res = -1; xi = k; break
                if ht: res = 1; xi = k; break
                if hs: res = -1; xi = k; break
                k += 1
            if res is None:        # 데이터 끝까지 미해결
                unresolved += 1
                break
            if res > 0: wins += 1
            else: losses += 1
            armed = False; i = xi; continue
        if abs(d) < b:
            armed = True
        i += 1

    tot = wins + losses
    if tot == 0:
        return None
    wr = wins / tot
    return {"n": tot, "wr": wr, "net": (2*wr-1)*c - FEE, "unresolved": unresolved}


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=365)
    daily = fetch_klines_bybit(sym, "D", days=1095)
    C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
    ts=[x['start'] for x in c1]; ma1=_ma_hlc3(c1, MA_P); mad=_ma_hlc3(daily, MA_P)
    days_span = (ts[-1]-ts[0]) / DAY_MS

    print(f"{sym} {len(C):,}분봉 (~{days_span:.0f}일), 수수료 {FEE*100:.2f}%")
    print(f"게임: 일봉 a%이격 AND 1분 b%이격 진입 → ±c 청산(timeout 없음)\n")

    rows = []
    for a in A_GRID:
        for b in B_GRID:
            for c in C_GRID:
                r = simulate(C, Hi, Lo, ma1, ts, daily, mad, a, b, c)
                if r:
                    r.update({"a": a, "b": b, "c": c, "per_day": r["n"]/days_span})
                    rows.append(r)

    # 전체 중 승률>50% 인 것 (빈도/표본 표시)
    print("=== 승률 50% 초과 조합 (빈도 오름차순) ===")
    print(f"{'a%':>5}{'b%':>6}{'c%':>6}{'승률':>7}{'건수':>6}{'하루':>7}{'순기대':>8}")
    over = [r for r in rows if r["wr"] > 0.5 and r["n"] >= 30]
    for r in sorted(over, key=lambda z: z["per_day"]):
        print(f"{r['a']*100:>4.0f}%{r['b']*100:>5.2f}%{r['c']*100:>5.2f}%"
              f"{r['wr']*100:>6.1f}%{r['n']:>6}{r['per_day']:>6.2f}/일{r['net']*100:>+7.3f}%")
    if not over:
        print("  (승률>50% & n>=30 조합 없음)")

    print("\n=== 순기대 상위 10 (n>=30, 하루 거래 <=3) ===")
    print(f"{'a%':>5}{'b%':>6}{'c%':>6}{'승률':>7}{'건수':>6}{'하루':>7}{'순기대':>8}")
    cand = [r for r in rows if r["n"] >= 30 and r["per_day"] <= 3.0]
    for r in sorted(cand, key=lambda z: -z["net"])[:10]:
        print(f"{r['a']*100:>4.0f}%{r['b']*100:>5.2f}%{r['c']*100:>5.2f}%"
              f"{r['wr']*100:>6.1f}%{r['n']:>6}{r['per_day']:>6.2f}/일{r['net']*100:>+7.3f}%")


if __name__ == "__main__":
    main()
