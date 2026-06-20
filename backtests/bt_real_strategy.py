"""
실제 봇 전략 백테스트 — tradingBot/strategies의 진짜 코드를 그대로 import해서 1년 데이터에 적용.

- 진입: get_long/short_entry_signal (INIT/INIT2,3/BOOST/SCALE_IN)
- 청산: get_exit_signal (TIME_LIMIT/STOP_LOSS/BOOST*/TAKE_PROFIT/RISK_CONTROL/NORMAL/SCALE_OUT/INIT_OUT/NEAR_TOUCH)
- 임계값: 적응형(7일 5크로스, 봇과 동일), momentum_threshold = thr/2, prev3 = 3봉전.
- 시간: 시뮬레이션 시간 주입(모듈 time 교체). price=종가(분봉). 수수료=테이커 왕복 0.11%/lot.

오케스트레이션은 signal_processor 규약: 매 봉 EXIT(양사이드) 먼저, 없으면 ENTRY(SHORT→LONG).
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tradingBot"))

from reversion_calibrator import fetch_klines_bybit, _ma_hlc3
from strategies.basic_entry import get_long_entry_signal, get_short_entry_signal
from strategies.basic_exit import get_exit_signal
import strategies.basic_entry as BE
import strategies.basic_exit as BX

# ── 적응형 임계값 (bt_adaptive와 동일) ──
WIN = 10080; TARGET = 5; MIN_THR, MAX_THR = 0.005, 0.07; MIN_INT = 60; RECALC = 1440
MA_P = 100
FEE = 0.0011                       # 테이커 왕복 / lot
TIME_LIMIT = 7*24*3600
NEAR_TOUCH = 1800

# 시뮬레이션 시계 주입
class Clock:
    now_ms = 0
    def time(self): return self.now_ms / 1000.0
clock = Clock()
BE.time = clock
BX.time = clock


def count_cross(C, Hi, Lo, ma, lo, hi, thr):
    cnt = 0; state = None; lastU = lastD = -10**9
    for i in range(lo, hi):
        m = ma[i]
        if m is None: continue
        up = m*(1+thr); dn = m*(1-thr)
        if state in ("below","in") and Hi[i] > up and (i-lastU) > MIN_INT: cnt += 1; lastU = i
        if state in ("above","in") and Lo[i] < dn and (i-lastD) > MIN_INT: cnt += 1; lastD = i
        cl = C[i]; state = "above" if cl > up else ("below" if cl < dn else "in")
    return cnt


def adaptive_thr(C, Hi, Lo, ma, lo, hi):
    left, right = MIN_THR, MAX_THR; opt = right
    for _ in range(18):
        mid = (left+right)/2
        if count_cross(C, Hi, Lo, ma, lo, hi, mid) > TARGET: left = mid
        else: opt = mid; right = mid
    return max(opt, MIN_THR)


def precompute_thr(C, Hi, Lo, ma):
    n = len(C); out = [None]*n; cur = None; nxt = WIN
    for i in range(n):
        if i >= WIN and i >= nxt:
            cur = adaptive_thr(C, Hi, Lo, ma, i-WIN, i); nxt = i + RECALC
        out[i] = cur
    return out


def run(O, C, Hi, Lo, ma, ts, thr_at, lo, hi):
    sid = 0
    lots = {"LONG": [], "SHORT": []}   # 각 항목 [sid, ts, entry_price, tag]
    last_scaleout = {"LONG": None, "SHORT": None}
    boost_attempts = {"LONG": {}, "SHORT": {}}
    realized = []   # (pnl_pct_net, side, tag, exit_mode)

    def items_of(side):
        return [(str(s), int(t), float(ep), str(tg)) for s, t, ep, tg in lots[side]]

    def close_lots(side, target_ids, price, mode):
        keep = []
        for lot in lots[side]:
            if str(lot[0]) in target_ids:
                ep = lot[2]
                pnl = (price-ep)/ep if side == "LONG" else (ep-price)/ep
                realized.append((pnl - FEE, side, lot[3], mode))
            else:
                keep.append(lot)
        lots[side] = keep

    for i in range(max(WIN, lo), hi):
        m = ma[i]; thr = thr_at[i]
        if m is None or thr is None or i < 3:
            continue
        clock.now_ms = ts[i]
        price = C[i]
        mom_thr = thr/2.0
        prev3 = {"open": O[i-3], "high": Hi[i-3], "low": Lo[i-3], "close": C[i-3]}

        # ── EXIT 먼저 (양 사이드) ──
        did_exit = False
        for side in ("LONG", "SHORT"):
            its = items_of(side)
            if not its:
                continue
            sig = get_exit_signal(
                side=side, price=price, ma100=m, prev3_candle=prev3, open_items=its,
                ma_threshold=thr, time_limit_sec=TIME_LIMIT, near_touch_window_sec=NEAR_TOUCH,
                momentum_threshold=mom_thr, last_scaleout_ts_ms=last_scaleout[side])
            if sig and sig.get("targets"):
                tids = set(str(x) for x in sig["targets"])
                close_lots(side, tids, price, sig.get("mode", "?"))
                if sig.get("mode") == "SCALE_OUT":
                    last_scaleout[side] = ts[i]
                did_exit = True
        if did_exit:
            continue

        # ── ENTRY (SHORT → LONG) ──
        for side, fn in (("SHORT", get_short_entry_signal), ("LONG", get_long_entry_signal)):
            its = items_of(side)
            has_init = any(tg == "INIT" for (_s, _t, _e, tg) in its)
            if its and not has_init:
                continue
            sig = fn(price=price, ma100=m, prev3_candle=prev3, open_items=its,
                     boost_attempts_by_anchor=boost_attempts[side],
                     ma_threshold=thr, momentum_threshold=mom_thr)
            if sig:
                # tag 추론
                reasons = sig.get("reasons") or []
                tag = "INIT"
                for r in reasons:
                    if r in ("INIT", "SCALE_IN", "INIT2", "INIT3") or "BOOST" in str(r):
                        tag = "BOOST" if "BOOST" in str(r) else r
                        break
                extra = sig.get("extra") or {}
                if extra.get("is_boost"):
                    tag = extra.get("boost_tag", "BOOST")
                    anchor = str(extra.get("anchor_signal_id"))
                    boost_attempts[side][anchor] = boost_attempts[side].get(anchor, 0) + 1
                elif extra.get("is_scale_in"):
                    tag = "SCALE_IN"
                elif extra.get("is_init_follow"):
                    tag = "INIT"   # INIT2/3는 INIT 계열로 묶음(INIT 태그 유지로 추가진입 허용)
                sid += 1
                lots[side].append([sid, ts[i], price, tag])
                break   # 한 봉 한 진입

    return realized, lots


def report(realized, lots, label):
    n = len(realized)
    if n == 0:
        print(f"[{label}] 거래 없음"); return
    pnls = [r[0] for r in realized]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    wr = len(wins)/n
    aw = sum(wins)/len(wins) if wins else 0
    al = sum(losses)/len(losses) if losses else 0
    openn = len(lots["LONG"]) + len(lots["SHORT"])
    print(f"[{label}] 청산 {n}건 | 승률 {wr*100:.1f}% | 총손익(lot합) {total*100:+.1f}% | "
          f"평균 {total/n*100:+.3f}%/lot | 평균익 {aw*100:+.3f} 평균손 {al*100:+.3f} | 미청산 {openn}")
    # 청산 모드별
    from collections import defaultdict
    bymode = defaultdict(lambda: [0, 0.0])
    for pnl, side, tag, mode in realized:
        bymode[mode][0] += 1; bymode[mode][1] += pnl
    print("   모드별:", ", ".join(f"{mo}:{c}건/{p*100:+.1f}%" for mo, (c, p) in sorted(bymode.items(), key=lambda x: -x[1][1])))


def main():
    sym = "BTCUSDT"
    c1 = fetch_klines_bybit(sym, "1", days=365)
    O=[x['open'] for x in c1]; C=[x['close'] for x in c1]; Hi=[x['high'] for x in c1]; Lo=[x['low'] for x in c1]
    ts=[x['start'] for x in c1]; ma=_ma_hlc3(c1, MA_P)
    n = len(C); mid = n//2
    print(f"{sym} {n:,}분봉, 적응형 임계값 산출 중...")
    thr_at = precompute_thr(C, Hi, Lo, ma)
    print(f"수수료 {FEE*100:.2f}%/lot (테이커 왕복), 1 lot = 동일 노션 가정\n")

    rz, lt = run(O, C, Hi, Lo, ma, ts, thr_at, WIN, n)
    report(rz, lt, "전체 1년")
    rzi, lti = run(O, C, Hi, Lo, ma, ts, thr_at, WIN, mid)
    report(rzi, lti, "IS(상반기)")
    rzo, lto = run(O, C, Hi, Lo, ma, ts, thr_at, mid, n)
    report(rzo, lto, "OOS(하반기)")


if __name__ == "__main__":
    main()
