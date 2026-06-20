"""
데이터 적재/갱신 — Bybit 공개 kline을 받아 data/ 에 로컬 캐시(pickle).

한 번 받으면 이후 실험은 API 없이 로컬 캐시로 돌아간다 (rate-limit 회피).
일봉은 심볼당 1~2요청이라 다중 심볼도 안전. 1분봉은 심볼당 ~526요청이라 무겁다.

사용:
  python fetch_data.py --daily BTCUSDT,ETHUSDT,SOLUSDT --days 1095   # 3년 일봉
  python fetch_data.py --daily-universe                              # 기본 유니버스 일봉
  python fetch_data.py --m1 BTCUSDT --days 365                       # 1년 1분봉(무거움)
  python fetch_data.py --list                                        # 현재 캐시 현황
"""
from __future__ import annotations
import argparse
import os
import time
from datetime import datetime, timezone
from reversion_calibrator import fetch_klines_bybit, CACHE_DIR, _load_cache

# 풀링 실험용 기본 유니버스 (거래대금/유동성 상위 위주, 필요시 수정)
DEFAULT_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "MATICUSDT",
    "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "NEARUSDT", "FILUSDT", "INJUSDT", "SUIUSDT", "TIAUSDT",
    "SEIUSDT", "RUNEUSDT", "AAVEUSDT", "ETCUSDT", "XLMUSDT", "ALGOUSDT",
]


def fetch_many(symbols, interval, days, inter_sleep):
    ok, fail = [], []
    for i, sym in enumerate(symbols):
        try:
            c = fetch_klines_bybit(sym, interval, days=days, sleep_sec=0.25)
            if c:
                a = datetime.fromtimestamp(c[0]["start"] / 1000, tz=timezone.utc)
                b = datetime.fromtimestamp(c[-1]["start"] / 1000, tz=timezone.utc)
                print(f"  [{i+1}/{len(symbols)}] {sym}: {len(c):,}봉  {a:%Y-%m-%d}~{b:%Y-%m-%d}")
                ok.append(sym)
            else:
                print(f"  [{i+1}/{len(symbols)}] {sym}: 빈 결과")
                fail.append(sym)
        except Exception as e:
            print(f"  [{i+1}/{len(symbols)}] {sym}: 실패 {e}")
            fail.append(sym)
        if i < len(symbols) - 1:
            time.sleep(inter_sleep)   # 심볼 간 여유 (rate-limit 보호)
    print(f"\n완료: 성공 {len(ok)}, 실패 {len(fail)}")
    if fail:
        print("실패:", ", ".join(fail))


def list_cache():
    if not os.path.isdir(CACHE_DIR):
        print("(캐시 없음)")
        return
    print(f"캐시 디렉토리: {CACHE_DIR}")
    for f in sorted(os.listdir(CACHE_DIR)):
        if f.endswith(".pkl"):
            p = os.path.join(CACHE_DIR, f)
            mb = os.path.getsize(p) / 1e6
            try:
                n = len(_load_cache(f.replace(".pkl", "").rsplit("_", 1)[0],
                                    f.replace(".pkl", "").rsplit("_", 1)[1].rstrip("m")))
            except Exception:
                n = "?"
            print(f"  {f:<22} {mb:>7.1f}MB  ({n}봉)" if isinstance(n, int) else f"  {f:<22} {mb:>7.1f}MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", help="콤마구분 심볼들 일봉")
    ap.add_argument("--daily-universe", action="store_true", help="기본 유니버스 일봉")
    ap.add_argument("--m1", help="콤마구분 심볼들 1분봉(무거움)")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--inter-sleep", type=float, default=3.0, help="심볼 간 대기초")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        list_cache(); return
    if args.daily_universe:
        print(f"유니버스 {len(DEFAULT_UNIVERSE)}개 일봉 {args.days}일 적재...")
        fetch_many(DEFAULT_UNIVERSE, "D", args.days, args.inter_sleep)
    elif args.daily:
        syms = [s.strip().upper() for s in args.daily.split(",") if s.strip()]
        fetch_many(syms, "D", args.days, args.inter_sleep)
    elif args.m1:
        syms = [s.strip().upper() for s in args.m1.split(",") if s.strip()]
        fetch_many(syms, "1", args.days, args.inter_sleep)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
