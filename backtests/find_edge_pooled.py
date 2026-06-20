"""
풀링 엣지 탐색 — (b,c)를 σ_dev 정규화하고 BTC/ETH/SOL을 합쳐,
승률이 50%에서 유의하게(그리고 심볼 간 일관되게) 벗어나는 조합을 찾는다.

승률 > 50% → 평균회귀 방향 / < 50% → 반대(추세) 방향 으로 둘 다 엣지가 될 수 있다.
단, |z| 충분 + 심볼 일관 + OOS 유지여야 진짜.

게임: 1분봉이 b 이상 이격 진입 → ±c 청산(timeout 없음). (일봉조건 a는 앞서 무익 → 제외)
b = kb*σ_dev, c = kc*σ_dev.  σ_dev = 이격 (price-MA100)/MA100 의 표준편차.
"""
from __future__ import annotations
import sys, os, statistics, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

MA_P = 100
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
KB = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]   # 진입 이격 (σ_dev배)
KC = [1.0, 2.0, 3.0, 4.0]             # 브래킷 (σ_dev배)


def sigma_dev(C, ma):
    devs = [(C[i]-ma[i])/ma[i] for i in range(len(C)) if ma[i] is not None]
    return statistics.pstdev(devs)


def sim(C, Hi, Lo, ma, b, c, lo, hi):
    """no-timeout ±c. 반환 (wins, losses)."""
    n = len(C); w = l = 0; i = max(MA_P, lo); armed = True
    while i < hi:
        m = ma[i]
        if m is None:
            i += 1; continue
        d = (C[i]-m)/m
        if armed and abs(d) >= b:
            side = 1 if d <= -b else -1; P0 = C[i]
            tp = P0*(1+c) if side == 1 else P0*(1-c)
            sl = P0*(1-c) if side == 1 else P0*(1+c)
            res = None; xi = None; k = i+1
            while k < n:
                ht = (Hi[k] >= tp) if side == 1 else (Lo[k] <= tp)
                hs = (Lo[k] <= sl) if side == 1 else (Hi[k] >= sl)
                if ht and hs: res = -1; xi = k; break
                if ht: res = 1; xi = k; break
                if hs: res = -1; xi = k; break
                k += 1
            if res is None:
                break
            w += res > 0; l += res < 0; armed = False; i = xi; continue
        if abs(d) < b:
            armed = True
        i += 1
    return w, l


def main():
    data = {}
    for s in SYMS:
        c1 = fetch_klines_bybit(s, "1", days=365)
        C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
        ma=_ma_hlc3(c1, MA_P); sd = sigma_dev(C, ma)
        data[s] = (C, Hi, Lo, ma, sd)
        print(f"{s}: σ_dev={sd*100:.3f}% (이격 표준편차)")
    print()

    print("kb / kc (σ_dev배) | 풀승률  n     z(vs50)  일관 | BTC%  ETH%  SOL%")
    rows = []
    for kb in KB:
        for kc in KC:
            tw = tl = 0; per = {}
            for s in SYMS:
                C, Hi, Lo, ma, sd = data[s]
                w, l = sim(C, Hi, Lo, ma, kb*sd, kc*sd, MA_P, len(C))
                per[s] = (w/(w+l)) if (w+l) else 0.5
                tw += w; tl += l
            n = tw+tl
            if n < 50:
                continue
            wr = tw/n
            z = (wr-0.5)/math.sqrt(0.25/n)
            sides = [1 if per[s] > 0.5 else (-1 if per[s] < 0.5 else 0) for s in SYMS]
            consistent = (all(x >= 0 for x in sides) or all(x <= 0 for x in sides)) and any(sides)
            rows.append((abs(z), kb, kc, wr, n, z, consistent, per))
    # |z| 큰 순
    for az, kb, kc, wr, n, z, cons, per in sorted(rows, reverse=True):
        flag = "✓" if (abs(z) >= 2 and cons) else " "
        print(f"  {kb:>3.1f} / {kc:>3.1f}        | {wr*100:5.1f}% {n:>5} {z:>+6.2f}  {('일관' if cons else '불일치'):>4} {flag}| "
              f"{per['BTCUSDT']*100:4.0f}% {per['ETHUSDT']*100:4.0f}% {per['SOLUSDT']*100:4.0f}%")
    print("\n✓ = |z|>=2 AND 심볼 일관 (= 뒤집어서라도 진짜 엣지 후보). OOS 재검증 필요.")


if __name__ == "__main__":
    main()
