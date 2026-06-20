"""
(1일봉 이탈% x 1분봉 이탈%) 조합별 승률 2D 그리드 (오프라인 read-only, IS/OOS).

진입: 1분봉이 MA100에서 T 이상 이탈 AND 1일봉도 같은 방향으로 Td 이상 이탈(하루전 확정봉, 무룩어헤드).
승패: 진입 후 H봉 보유 후 청산. 유리방향이면 승.
순기대: 실제 실현손익(시장가 청산) - 수수료(env FEE, 기본 테이커 0.11%).
"""
from __future__ import annotations
import sys, os, bisect
sys.path.insert(0, os.path.dirname(__file__))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE = float(os.environ.get("FEE", "0.0011"))
DAY_MS = 86_400_000
MA_P = 100
H = int(os.environ.get("HOLD", "1440"))   # 보유봉수 (기본 1일)

T_COLS = [0.005, 0.01, 0.015, 0.02]                 # 1분봉 이탈
TD_ROWS = [None, 0.0, 0.02, 0.04, 0.06, 0.08]       # 1일봉 이탈 (None=조건없음)


def run(C, Hi, Lo, ma, ts, daily, ma_d, T, Td, lo, hi):
    starts = [d["start"] for d in daily]
    def dev_at(ts_ms):
        j = bisect.bisect_right(starts, ts_ms - DAY_MS) - 1
        if j < 0 or ma_d[j] is None:
            return None
        return (daily[j]["close"] - ma_d[j]) / ma_d[j]

    n = len(C); pnls = []
    i = max(MA_P, lo); armed = True
    while i < hi:
        m = ma[i]
        if m is None:
            i += 1; continue
        d = (C[i] - m) / m
        if armed and abs(d) >= T:
            side = 1 if d <= -T else -1
            ok = True
            if Td is not None:
                dd = dev_at(ts[i])
                ok = (dd is not None) and ((dd <= -Td) if side == 1 else (dd >= Td))
            if not ok:
                i += 1; continue   # 진입 안함, 사건경계는 baseline과 동일하게 유지
            P0 = C[i]; end = min(i + H, n - 1)
            pnl = side * (C[end] - P0) / P0
            pnls.append(pnl)
            armed = False; i = end; continue
        if abs(d) < T:
            armed = True
        i += 1
    if not pnls:
        return None
    cnt = len(pnls)
    wr = sum(1 for p in pnls if p > 0) / cnt
    return {"n": cnt, "wr": wr, "net": sum(pnls)/cnt - FEE}


def main():
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        c = fetch_klines_bybit(sym, "1", days=365)
        daily = fetch_klines_bybit(sym, "D", days=600)
        C=[x['close'] for x in c]; Hi=[x['high'] for x in c]; Lo=[x['low'] for x in c]
        ts=[x['start'] for x in c]; ma=_ma_hlc3(c,MA_P); ma_d=_ma_hlc3(daily,MA_P)
        n=len(C); mid=n//2

        print(f"\n========== {sym}  (보유 {H//1440 or H}{'일' if H>=1440 else '봉'}) ==========")
        for tag, lo, hi in [("OOS(하반기)", mid, n)]:   # OOS만 (IS는 과적합 참고용)
            print(f"[{tag}] 셀 = 승률% (n)   — 행:1일봉이탈, 열:1분봉이탈")
            hdr = "일봉\\1분 " + "".join(f"{t*100:>11.1f}%" for t in T_COLS)
            print(hdr)
            for Td in TD_ROWS:
                rl = "  없음 " if Td is None else f"{Td*100:>5.0f}% "
                cells = []
                for T in T_COLS:
                    r = run(C,Hi,Lo,ma,ts,daily,ma_d,T,Td,lo,hi)
                    cells.append(f"{r['wr']*100:>5.1f}({r['n']})" if r and r['n']>=20 else "   -   ")
                print(rl + "".join(f"{c:>12}" for c in cells))
        # 순기대(OOS) 별도
        print(f"[OOS] 셀 = 순기대%(수수료후)")
        print("일봉\\1분 " + "".join(f"{t*100:>11.1f}%" for t in T_COLS))
        for Td in TD_ROWS:
            rl = "  없음 " if Td is None else f"{Td*100:>5.0f}% "
            cells=[]
            for T in T_COLS:
                r=run(C,Hi,Lo,ma,ts,daily,ma_d,T,Td,mid,n)
                cells.append(f"{r['net']*100:>+7.3f}" if r and r['n']>=20 else "   -   ")
            print(rl + "".join(f"{c:>12}" for c in cells))


if __name__ == "__main__":
    main()
