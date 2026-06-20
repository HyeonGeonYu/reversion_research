"""
1일봉만 — (이탈 T x 브래킷 X) 승률 그리드 (오프라인 read-only).

진입: 일봉 종가가 일봉MA100에서 T 이상 이탈 (아래=LONG/반등, 위=SHORT).
승패: ±X% 대칭 브래킷. +X 먼저 = 승, -X 먼저 = 패, maxH일 내 미달성 = 실제 종가손익.
순기대: 실현손익 평균 - 수수료(env FEE 기본 0.11%). (다일 보유 펀딩은 미반영 — 주의)
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE = float(os.environ.get("FEE", "0.0011"))
MA_P = 100
MAX_H = int(os.environ.get("MAXH", "60"))   # 최대 보유 일수

T_ROWS = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]   # 일봉 이탈
X_COLS = [0.03, 0.05, 0.08, 0.10, 0.15]         # 브래킷


def grid_cell(C, Hi, Lo, ma, T, X):
    n = len(C); pnls = []; nres = 0
    i = MA_P; armed = True
    while i < n:
        m = ma[i]
        if m is None:
            i += 1; continue
        d = (C[i] - m) / m
        if armed and abs(d) >= T:
            side = 1 if d <= -T else -1
            P0 = C[i]
            if side == 1: tp = P0*(1+X); sl = P0*(1-X)
            else:         tp = P0*(1-X); sl = P0*(1+X)
            end = min(i + MAX_H, n - 1)
            pnl = None; xi = None
            for k in range(i+1, end+1):
                if side == 1: ht = Hi[k] >= tp; hs = Lo[k] <= sl
                else:         ht = Lo[k] <= tp; hs = Hi[k] >= sl
                if ht and hs: pnl = -X; xi = k; nres += 1; break
                if ht: pnl = X; xi = k; nres += 1; break
                if hs: pnl = -X; xi = k; nres += 1; break
            if pnl is None:
                pnl = side*(C[end]-P0)/P0; xi = end
            pnls.append(pnl); armed = False; i = xi; continue
        if abs(d) < T: armed = True
        i += 1
    if not pnls:
        return None
    cnt = len(pnls)
    return {"n": cnt, "wr": sum(1 for p in pnls if p>0)/cnt,
            "net": sum(pnls)/cnt - FEE, "res": nres/cnt}


def main():
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        daily = fetch_klines_bybit(sym, "D", days=1095)   # 3년
        C=[x['close'] for x in daily]; Hi=[x['high'] for x in daily]; Lo=[x['low'] for x in daily]
        ma=_ma_hlc3(daily, MA_P)
        usable = sum(1 for v in ma if v is not None)
        print(f"\n========== {sym}  (일봉 {len(daily)}개, MA100 가능 {usable}개, 최대보유 {MAX_H}일) ==========")

        print("[승률% (n)]  행:일봉이탈 T, 열:브래킷 X")
        print(" T\\X  " + "".join(f"{x*100:>11.0f}%" for x in X_COLS))
        for T in T_ROWS:
            cells = []
            for X in X_COLS:
                r = grid_cell(C, Hi, Lo, ma, T, X)
                cells.append(f"{r['wr']*100:>4.0f}({r['n']})" if r and r['n'] >= 8 else "  -  ")
            print(f"{T*100:>4.0f}% " + "".join(f"{c:>12}" for c in cells))

        print("[순기대%(수수료후)]  행:T, 열:X")
        print(" T\\X  " + "".join(f"{x*100:>11.0f}%" for x in X_COLS))
        for T in T_ROWS:
            cells = []
            for X in X_COLS:
                r = grid_cell(C, Hi, Lo, ma, T, X)
                cells.append(f"{r['net']*100:>+6.2f}" if r and r['n'] >= 8 else "  -  ")
            print(f"{T*100:>4.0f}% " + "".join(f"{c:>12}" for c in cells))


if __name__ == "__main__":
    main()
