"""
1일봉, 변동성(σ) 정규화 (T x X) 승률 그리드 (오프라인 read-only).

각 심볼의 일간 수익률 표준편차 σ로 T,X를 정규화:
  T = kT * σ (이탈), X = kX * σ (브래킷).
→ 심볼 변동성 차이를 보정해 같은 'σ 단위'에서 패턴이 정렬되는지 비교.
또한 IS/OOS 분할로 안정성 확인.
"""
from __future__ import annotations
import sys, os, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE = float(os.environ.get("FEE", "0.0011"))
MA_P = 100
MAX_H = int(os.environ.get("MAXH", "60"))

KT = [1, 2, 3, 4, 5]      # 이탈 = kT*σ
KX = [1, 2, 3, 4]         # 브래킷 = kX*σ


def daily_sigma(C):
    rets = [(C[i] - C[i-1]) / C[i-1] for i in range(1, len(C)) if C[i-1] > 0]
    return statistics.pstdev(rets)


def cell(C, Hi, Lo, ma, T, X, lo, hi):
    n = len(C); pnls = []
    i = max(MA_P, lo); armed = True
    while i < hi:
        m = ma[i]
        if m is None:
            i += 1; continue
        d = (C[i] - m) / m
        if armed and abs(d) >= T:
            side = 1 if d <= -T else -1; P0 = C[i]
            if side == 1: tp = P0*(1+X); sl = P0*(1-X)
            else:         tp = P0*(1-X); sl = P0*(1+X)
            end = min(i + MAX_H, n - 1); pnl = None; xi = None
            for k in range(i+1, end+1):
                if side == 1: ht = Hi[k] >= tp; hs = Lo[k] <= sl
                else:         ht = Lo[k] <= tp; hs = Hi[k] >= sl
                if ht and hs: pnl = -X; xi = k; break
                if ht: pnl = X; xi = k; break
                if hs: pnl = -X; xi = k; break
            if pnl is None:
                pnl = side*(C[end]-P0)/P0; xi = end
            pnls.append(pnl); armed = False; i = xi; continue
        if abs(d) < T: armed = True
        i += 1
    if not pnls:
        return None
    cnt = len(pnls)
    return {"n": cnt, "wr": sum(1 for p in pnls if p>0)/cnt, "net": sum(pnls)/cnt - FEE}


def main():
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        daily = fetch_klines_bybit(sym, "D", days=1095)
        C=[x['close'] for x in daily]; Hi=[x['high'] for x in daily]; Lo=[x['low'] for x in daily]
        ma=_ma_hlc3(daily, MA_P); n=len(C)
        sig = daily_sigma(C)
        print(f"\n===== {sym}  (일봉 {n}개, 일변동성 σ={sig*100:.2f}%/일) =====")
        print("[전체기간 승률% (n)]  행:이탈 kσ, 열:브래킷 kσ   (절대%는 σ배)")
        print(" 이탈\\브래킷 " + "".join(f"{kx}σ".rjust(11) for kx in KX))
        for kt in KT:
            T = kt * sig
            cells = []
            for kx in KX:
                X = kx * sig
                r = cell(C, Hi, Lo, ma, T, X, MA_P, n)
                cells.append(f"{r['wr']*100:>3.0f}({r['n']})" if r and r['n'] >= 8 else "  -  ")
            print(f"  {kt}σ ({T*100:>4.1f}%) " + "".join(f"{c:>11}" for c in cells))

        # IS/OOS 안정성 (전체 최고 셀 기준)
        mid = n // 2
        best = None
        for kt in KT:
            for kx in KX:
                r = cell(C, Hi, Lo, ma, kt*sig, kx*sig, MA_P, mid)  # IS=전반
                if r and r['n'] >= 10 and (best is None or r['wr'] > best['wr']):
                    best = {**r, 'kt': kt, 'kx': kx}
        if best:
            oos = cell(C, Hi, Lo, ma, best['kt']*sig, best['kx']*sig, mid, n)
            print(f"  IS최고: 이탈{best['kt']}σ/브래킷{best['kx']}σ → IS승률 {best['wr']*100:.0f}%(n={best['n']}) | "
                  f"OOS승률 {oos['wr']*100:.0f}%(n={oos['n']}) {'유지' if oos['wr']>0.5 else '붕괴'}" if oos else "")


if __name__ == "__main__":
    main()
