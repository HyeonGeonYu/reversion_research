"""
멀티 TF 검증 — 1분봉 평균회귀 진입에 "1일봉 동시 이탈" 필터를 걸면
승률이 50%를 넘는지 검증 (오프라인 read-only, OOS 포함).

비교: 같은 1분 진입 신호에 대해
  - baseline: 필터 없음
  - filtered: 진입 시점의 1일봉도 일봉MA100에서 같은 방향으로 Td 이상 이탈해 있을 때만
손익은 실현치(TP=+X, SL=-X, 시간초과=실제 종가). 수수료 env FEE(기본 테이커 0.11%).
"""
from __future__ import annotations
import sys, os, bisect
sys.path.insert(0, os.path.dirname(__file__))
from reversion_calibrator import fetch_klines_bybit, _ma_hlc3

FEE = float(os.environ.get("FEE", "0.0011"))
DAY_MS = 86_400_000

# 고정 베이스 (재최적화 안 함 — 필터 효과만 본다)
T_BASE = 0.01       # 1분봉 MA100 이탈 1%
X_BASE = 0.03       # 대칭 브래킷 ±3%
H_BASE = 1440       # 보유 1일
MA_P = 100


def daily_dev_lookup(daily, ma_d):
    """무룩어헤드: 1m ts에서 '하루 전 이미 마감된' 일봉의 (이탈률) 반환 함수."""
    starts = [d["start"] for d in daily]

    def dev_at(ts_ms):
        # ts 기준 최소 1일 전 시작한 마지막 일봉 (확정봉)
        j = bisect.bisect_right(starts, ts_ms - DAY_MS) - 1
        if j < 0 or ma_d[j] is None:
            return None
        return (daily[j]["close"] - ma_d[j]) / ma_d[j]
    return dev_at


def backtest(C, Hi, Lo, ma, ts, dev_at, T, X, H, lo, hi, Td=None):
    """Td=None이면 baseline. 아니면 일봉 동시이탈(같은 방향, |dd|>=Td) 필터."""
    n = len(C)
    pnls = []
    i = max(MA_P, lo)
    armed = True
    while i < hi:
        m = ma[i]
        if m is None:
            i += 1; continue
        d = (C[i] - m) / m
        if armed and abs(d) >= T:
            side = 1 if d <= -T else -1
            passed = True
            if Td is not None:
                dd = dev_at(ts[i])
                if dd is None:
                    passed = False
                else:
                    # 같은 방향 동시 이탈: LONG이면 일봉도 아래(dd<=-Td), SHORT이면 위(dd>=+Td)
                    passed = (dd <= -Td) if side == 1 else (dd >= Td)
            if not passed:
                armed = False  # 신호는 소비(다음 이탈 해소까지 대기) → baseline과 진입후보 동일하게
                # baseline 비교 공정성 위해 진입후보 위치는 같게 두되, 필터통과만 다르게.
                # 여기선 미진입이지만 armed=False로 두면 baseline과 사건경계가 어긋남 → 대신 통과로직만 분기
                # => armed 복구: 필터 미통과는 '진입 안함'이되 사건경계는 baseline과 같게 하려고 jump 안함
                armed = True
                i += 1
                continue
            P0 = C[i]
            if side == 1:
                tp = P0 * (1 + X); sl = P0 * (1 - X)
            else:
                tp = P0 * (1 - X); sl = P0 * (1 + X)
            end = min(i + H, n - 1)
            pnl = None; xi = None
            for k in range(i + 1, end + 1):
                if side == 1:
                    ht = Hi[k] >= tp; hs = Lo[k] <= sl
                else:
                    ht = Lo[k] <= tp; hs = Hi[k] >= sl
                if ht and hs:
                    pnl = -X; xi = k; break
                if ht:
                    pnl = X; xi = k; break
                if hs:
                    pnl = -X; xi = k; break
            if pnl is None:
                pnl = side * (C[end] - P0) / P0; xi = end
            pnls.append(pnl)
            armed = False
            i = xi
            continue
        if abs(d) < T:
            armed = True
        i += 1

    if not pnls:
        return None
    cnt = len(pnls)
    wr = sum(1 for p in pnls if p > 0) / cnt
    ev = sum(pnls) / cnt
    return {"n": cnt, "wr": wr, "net": ev - FEE}


def main():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    print(f"베이스 고정: 1m MA100 이탈 T={T_BASE*100:.1f}%, 브래킷 X={X_BASE*100:.0f}%, "
          f"보유 {H_BASE//1440}일 | 수수료 {FEE*100:.2f}%\n")

    for sym in symbols:
        c = fetch_klines_bybit(sym, "1", days=365)
        daily = fetch_klines_bybit(sym, "D", days=600)
        C = [x["close"] for x in c]; Hi = [x["high"] for x in c]; Lo = [x["low"] for x in c]
        ts = [x["start"] for x in c]; ma = _ma_hlc3(c, MA_P)
        ma_d = _ma_hlc3(daily, MA_P)
        dev_at = daily_dev_lookup(daily, ma_d)
        n = len(C); mid = n // 2

        print(f"=== {sym} ===")
        print(f"{'조건':<22}{'IS승률':>7}{'IS순기대':>9}{'IS건수':>7}  | {'OOS승률':>7}{'OOS순기대':>9}{'OOS건수':>7}")
        for label, Td in [("baseline(필터없음)", None), ("일봉동시이탈 Td=0", 0.0),
                          ("일봉동시이탈 Td=3%", 0.03), ("일봉동시이탈 Td=5%", 0.05)]:
            is_r = backtest(C, Hi, Lo, ma, ts, dev_at, T_BASE, X_BASE, H_BASE, MA_P, mid, Td)
            oos_r = backtest(C, Hi, Lo, ma, ts, dev_at, T_BASE, X_BASE, H_BASE, mid, n, Td)
            if is_r and oos_r:
                print(f"{label:<22}{is_r['wr']*100:>6.1f}%{is_r['net']*100:>+8.3f}%{is_r['n']:>7}  | "
                      f"{oos_r['wr']*100:>6.1f}%{oos_r['net']*100:>+8.3f}%{oos_r['n']:>7}")
            else:
                print(f"{label:<22} (데이터 부족)")
        print()


if __name__ == "__main__":
    main()
