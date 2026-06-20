"""
회귀확률 캘리브레이터 (1분봉 우선 / 오프라인 분석, read-only)

목적:
  과거 1m 캔들에서 "MA100 대비 이탈 → horizon 내 MA 복귀" 사건을 백테스트하여
  임계값 T별로 [복귀확률 / 평균복귀시간 / 평균수익 / 평균손실 / 손익비 / 기대값]을 산출.

핵심:
  - calibrate(): 라이브에서도 재사용할 순수 계산 함수 (I/O 없음)
  - fetch_klines_bybit(): Bybit 공개 API로 1m 캔들 적재(인증 불필요)
  - 라이브 트레이딩과 분리됨. 숫자 검증 후 ma_threshold 연동 예정.

사용:
  python tools/reversion_calibrator.py                      # 기본 심볼/파라미터
  python tools/reversion_calibrator.py --symbol BTCUSDT --days 30 --horizon 1440
"""
from __future__ import annotations

import argparse
import os
import pickle
import time
from statistics import mean
from typing import Optional

try:
    import requests
except ImportError:
    requests = None

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 적재 (Bybit 공개 kline, 인증 불필요) — 재시도/백오프/진행률/디스크캐시
# ─────────────────────────────────────────────────────────────────────────────
def _cache_path(symbol: str, interval: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_{interval}m.pkl")


def _load_cache(symbol: str, interval: str) -> list[dict]:
    p = _cache_path(symbol, interval)
    if os.path.exists(p):
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            return []
    return []


def _save_cache(symbol: str, interval: str, candles: list[dict]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(symbol, interval), "wb") as f:
        pickle.dump(candles, f)


def _get_page(url, params, max_retries=6, log=print):
    """한 페이지 요청 + rate-limit/네트워크 백오프 재시도."""
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code in (403, 429) or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code} (rate-limit/서버)")
            r.raise_for_status()
            data = r.json()
            rc = data.get("retCode", 0)
            if rc != 0:
                # 10006/10018 등 rate-limit 계열
                raise RuntimeError(f"retCode={rc} {data.get('retMsg')}")
            return data
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            log(f"    [retry {attempt+1}/{max_retries}] {e} - wait {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
    raise RuntimeError("unreachable")


def fetch_klines_bybit(symbol: str, interval: str = "1", days: int = 30,
                       base: str = "https://api.bybit.com",
                       use_cache: bool = True, sleep_sec: float = 0.25,
                       log=print) -> list[dict]:
    if requests is None:
        raise RuntimeError("requests 미설치")

    per_min = {"1": 1, "5": 5, "60": 60, "D": 1440}.get(str(interval), 1)
    target = int(days * 1440 / per_min)

    # 1) 캐시가 충분하면 그대로 사용
    if use_cache:
        cached = _load_cache(symbol, interval)
        if len(cached) >= target:
            log(f"  [cache] {symbol} {len(cached)}봉 보유 → {target}봉 사용 (API 호출 없음)")
            return cached[-target:]

    url = f"{base}/v5/market/kline"
    out: list[dict] = []
    end = None
    pages = 0
    total_pages = (target + 999) // 1000
    while len(out) < target:
        limit = min(1000, target - len(out))
        params = {"category": "linear", "symbol": symbol,
                  "interval": interval, "limit": limit}
        if end is not None:
            params["end"] = end

        data = _get_page(url, params, log=log)
        lst = (data.get("result") or {}).get("list") or []
        if not lst:
            break
        lst = lst[::-1]  # newest-first → oldest-first
        chunk = [{
            "start": int(c[0]),
            "open": float(c[1]), "high": float(c[2]),
            "low": float(c[3]), "close": float(c[4]),
        } for c in lst if len(c) >= 5]
        out = chunk + out
        end = int(lst[0][0]) - 1
        pages += 1
        if pages % 25 == 0 or len(out) >= target:
            log(f"    {symbol}: {len(out):,}/{target:,}봉 ({pages}/{total_pages}p)")
        if len(lst) < limit:
            break
        time.sleep(sleep_sec)

    out = out[-target:] if target > 0 else out
    if use_cache and out:
        _save_cache(symbol, interval, out)
        log(f"  [cache] {symbol} {len(out):,}봉 저장")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 순수 계산: 회귀확률 캘리브레이션
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_THRESHOLDS = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08]


def _ma_hlc3(candles: list[dict], period: int) -> list[Optional[float]]:
    n = len(candles)
    hlc3 = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles]
    ma: list[Optional[float]] = [None] * n
    s = 0.0
    for i in range(n):
        s += hlc3[i]
        if i >= period:
            s -= hlc3[i - period]
        if i >= period - 1:
            ma[i] = s / period
    return ma


def calibrate(
    candles: list[dict],
    *,
    ma_period: int = 100,
    horizon_bars: int = 1440,
    thresholds: Optional[list[float]] = None,
    revert: str = "ma_touch",          # "복귀" 정의: MA 터치
    fail_loss: str = "horizon_end",    # 실패 손실 기준: horizon 종료 시점 가격
    min_events: int = 15,              # 통계 유효 최소 이벤트 수
) -> dict:
    """
    각 임계값 T별로 이탈→복귀 사건을 백테스트한 통계표 반환.
    이벤트: |deviation| >= T 로 진입(가격이 밴드 밖으로 이탈). 해소(|d|<T) 후 재무장 → 중복 방지.
    side: 가격이 MA 아래면 LONG(반등 베팅), 위면 SHORT.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    n = len(candles)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    ma = _ma_hlc3(candles, ma_period)

    rows = []
    for T in thresholds:
        events = []
        i = ma_period
        armed = True
        while i < n:
            m = ma[i]
            if m is None:
                i += 1
                continue
            d = (closes[i] - m) / m

            if armed and abs(d) >= T:
                side = "LONG" if d <= -T else "SHORT"
                P0 = closes[i]
                end = i + horizon_bars
                if end >= n:
                    break  # 남은 전진 데이터 부족 → 이후 이벤트도 부족하므로 종료

                reverted = False
                bars = 0
                profit = 0.0
                pnl_fail = 0.0
                if side == "LONG":
                    worst = P0
                    for k in range(i + 1, end + 1):
                        if lows[k] < worst:
                            worst = lows[k]
                        if ma[k] is not None and highs[k] >= ma[k]:  # MA 터치(아래→위)
                            reverted = True
                            bars = k - i
                            profit = (ma[k] - P0) / P0
                            break
                    mae = (P0 - worst) / P0
                    if not reverted:
                        pnl_fail = (closes[end] - P0) / P0
                else:  # SHORT
                    worst = P0
                    for k in range(i + 1, end + 1):
                        if highs[k] > worst:
                            worst = highs[k]
                        if ma[k] is not None and lows[k] <= ma[k]:
                            reverted = True
                            bars = k - i
                            profit = (P0 - ma[k]) / P0
                            break
                    mae = (worst - P0) / P0
                    if not reverted:
                        pnl_fail = (P0 - closes[end]) / P0

                events.append({
                    "reverted": reverted, "bars": bars,
                    "profit": profit if reverted else None,
                    "pnl_fail": None if reverted else pnl_fail,
                    "mae": mae,
                })
                armed = False
                i = (i + bars) if reverted else end  # 해소 지점으로 점프(중복 방지)
                continue

            if abs(d) < T:
                armed = True
            i += 1

        # ── 집계 ──
        n_ev = len(events)
        if n_ev == 0:
            rows.append({"T": T, "n": 0})
            continue
        rev = [e for e in events if e["reverted"]]
        fail = [e for e in events if not e["reverted"]]
        p = len(rev) / n_ev
        avg_bars = mean([e["bars"] for e in rev]) if rev else 0.0
        avg_win = mean([e["profit"] for e in rev]) if rev else 0.0
        avg_fail_pnl = mean([e["pnl_fail"] for e in fail]) if fail else 0.0
        avg_loss = -avg_fail_pnl            # 양수 = 손실 크기
        avg_mae = mean([e["mae"] for e in events])
        rr = (avg_win / avg_loss) if avg_loss > 1e-12 else float("inf")
        rr_mae = (avg_win / avg_mae) if avg_mae > 1e-12 else float("inf")
        expectancy = p * avg_win - (1 - p) * avg_loss

        rows.append({
            "T": T, "n": n_ev, "p_revert": p,
            "avg_bars": avg_bars, "avg_win": avg_win,
            "avg_loss": avg_loss, "rr": rr, "avg_mae": avg_mae,
            "rr_mae": rr_mae, "expectancy": expectancy,
        })

    # 기대값 최대 T (유효 이벤트 수 충족)
    valid = [r for r in rows if r.get("n", 0) >= min_events and "expectancy" in r]
    best = max(valid, key=lambda r: r["expectancy"]) if valid else None

    return {"rows": rows, "best": best, "min_events": min_events}


# ─────────────────────────────────────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_dur_min(bars: float) -> str:
    m = int(round(bars))
    if m < 60:
        return f"{m}m"
    if m < 1440:
        return f"{m/60:.1f}h"
    return f"{m/1440:.1f}d"


def print_table(symbol: str, result: dict, horizon_bars: int):
    print(f"\n=== {symbol} (1m, horizon={_fmt_dur_min(horizon_bars)}) ===")
    print(f"{'T이탈':>7} {'건수':>5} {'복귀확률':>7} {'평균복귀':>8} "
          f"{'평균수익':>8} {'평균손실':>8} {'손익비':>6} {'MAE':>7} {'rr/MAE':>7} {'기대값':>8}")
    for r in result["rows"]:
        if r.get("n", 0) == 0:
            print(f"{r['T']*100:>6.2f}% {0:>5}   (이벤트 없음)")
            continue
        print(f"{r['T']*100:>6.2f}% {r['n']:>5} {r['p_revert']*100:>6.1f}% "
              f"{_fmt_dur_min(r['avg_bars']):>8} {r['avg_win']*100:>7.2f}% "
              f"{r['avg_loss']*100:>7.2f}% {r['rr']:>6.2f} {r['avg_mae']*100:>6.2f}% "
              f"{r['rr_mae']:>7.2f} {r['expectancy']*100:>7.2f}%")
    b = result["best"]
    if b:
        print(f"  ▶ 최적 T = {b['T']*100:.2f}%  (기대값 {b['expectancy']*100:+.2f}%, "
              f"복귀 {b['p_revert']*100:.0f}%, 손익비 {b['rr']:.2f}, n={b['n']})")
    else:
        print(f"  ▶ 유효 이벤트(≥{result['min_events']}) 없음 — 기간/임계값 조정 필요")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="단일 심볼 (없으면 기본 세트 전부)")
    ap.add_argument("--days", type=int, default=30, help="적재할 1m 데이터 일수")
    ap.add_argument("--horizon", type=int, default=1440, help="복귀 horizon (봉=분)")
    ap.add_argument("--ma", type=int, default=100, help="MA 기간")
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT"]

    for sym in symbols:
        try:
            candles = fetch_klines_bybit(sym, "1", days=args.days)
            print(f"[{sym}] 적재 {len(candles)}봉")
            res = calibrate(candles, ma_period=args.ma, horizon_bars=args.horizon)
            print_table(sym, res, args.horizon)
        except Exception as e:
            print(f"[{sym}] 실패: {e}")


if __name__ == "__main__":
    main()
