# reversion_research

평균회귀(MA/볼린저/RSI) 전략의 엣지를 데이터로 검증하는 연구 프로젝트.
(실거래 봇 `tradingBot`과 분리 — 여긴 순수 오프라인 백테스트/탐색.)

## 폴더 구조

```
reversion_research/
├── reversion_calibrator.py   # 공용 코어: fetch+캐시, MA, calibrate, fig_path()
├── fetch_data.py             # 데이터 적재/갱신 CLI (로컬 캐시)
├── data/                     # 캔들 캐시 *.pkl  (gitignore, 재취득 가능)
├── figures/                  # 모든 그래프 이미지 PNG  (gitignore)
├── charts/                   # 시각화 스크립트
└── backtests/                # 백테스트/탐색 스크립트
```

- **이미지는 전부 `figures/`로.** 차트 스크립트는 `from reversion_calibrator import fig_path`
  하고 `plt.savefig(fig_path("이름.png"))` → 파일명만 줘도 `figures/`에 저장됨. 새 차트도 이 규칙 사용.
- charts/·backtests/ 스크립트는 `sys.path`에 상위(`..`)를 넣어 루트의 `reversion_calibrator`를 임포트.

## 실행 환경

```bash
# anaconda: base(numpy/pandas/matplotlib) 또는 executor-a2(requests). 인코딩 강제:
PYTHONIOENCODING=utf-8 python <스크립트>.py
python fetch_data.py --list                  # 캐시 현황
python fetch_data.py --m1 BTCUSDT --days 1095 # 3년 1분봉(무거움, rate-limit 백오프 내장)
```

## 데이터 (현재 캐시)

- BTC/ETH/SOL/XRP **1분봉 3년**(각 ~157만봉) + **일봉 3년**.
- Bybit 공개 kline을 `data/*.pkl`에 캐시 → 이후 API 없이 로컬로 실험.
- ⚠️ 3년 1분봉 = 심볼당 ~1577요청. 연속이면 `retCode=10006`. `fetch_data.py`에 재시도/백오프+심볼간 대기 내장.

## 핵심 결론 (2026-06 현재)

진입 신호를 전방위로 검증(대칭브래킷/적응형/percentile-gate/MTF(RSI turn·stretch)/일봉기간·k 스윕/멀티심볼):

- **MA·볼린저·RSI 기반 "진입 방향 맞추기"는 크립토 단타에서 ~50/50.** 수수료를 못 이김.
- 일봉 z-게이트(과매도/과매수 구간)는 1분 게임 승률을 **일관되게 +1%p** 보태지만 50%를 못 넘김.
- **함정 교훈**: ①시간초과(시장가청산)를 ±X 만점으로 치면 환상 → 실현손익으로 계산.
  ②소표본(n 수십)의 고승률은 노이즈(±20%p), 반드시 OOS+풀링으로 확인.
  ③다중검정(많은 조합 스윕)하면 우연히 z>2 나옴 → Bonferroni/OOS 필수.
- **유일하게 gross 양수**: 실제 봇의 **비대칭 청산**(MA터치 작은익절 자주 + 물타기). 단 수수료 경계·국면의존.

→ **엣지는 "진입 방향"이 아니라 "청산/관리"에 있다.** (다음: 청산/물타기/사이징 연구)

## 추세매매: 모멘텀 더블극단 (⚠️ 수정중 / WIP)

평균회귀가 다 ~50/50인 와중에 **유일하게 수수료 후 양수 + OOS 안정**인 엣지.
**역추세가 아니라 추세 지속(모멘텀)에 베팅**하는 게 핵심.

**진입 (같은 방향 이중 극단):**
- 일봉 볼린저 z(SMA30) ≤ −2 → 확정 하락추세
- 1분 볼린저 z(SMA10080=7일) ≤ −3.48σ → 투매 가속
- → **SHORT**(지속 베팅). 롱은 거울(z≥+2 & z≥+3.48)이나 숏이 더 강해 **숏온리 채택**.

**청산:** 대칭 ±2% (쿨다운 60분, 중복진입 허용).

**검증 (4심볼 풀링, 3년, 테이커 0.11%):**
- 양방: n=233, 승률 64.8%, **z+4.52**, OOS 60.6%, net **+0.48%/거래**
- 숏온리 strict(−2/−3.48): n=121, 승률 67.8%, +0.60%/거래, 명목 +72.7% (매년·거의 모든 심볼 흑자)
- 숏온리 느슨(−2/**−3.0**): n=176, 승률 **70.5%**, +0.71%/거래 ← 1분 임계만 풀면 빈도·품질 둘 다↑ (현재 최선)
- ⚠️ 일봉은 −2 유지 필수(−1.5로 풀면 붕괴). XRP는 기여 미미(드래그) → 제외 검토.

**왜 되나:** 크립토 **청산 캐스케이드 + 음의 왜도**를, 이중 극단 필터로 "진짜 투매"만 골라 **단기 지속**을 수확. → 레버리지/변동성 구조·레짐에 의존(취약점).

**남은 일(WIP):** 펀딩 반영, 청산데이터 상관, 변동성 레짐 분해, 청산 ±2% 개선, 심볼셋 정리(XRP 제외), 실거래 이식.

**스크립트:** `bt_recommend_pool.py`(확정판) · `bt_recommend_quarters.py`(분기별) · `bt_short_loosen.py`(숏온리 느슨 스윕) · `bt_and_multi.py`(최초 발견).

## 지표 메모

- **볼린저 z-score**(권장): z=(가격−SMA_N)/σ_N. 변동성 정규화 → raw 이격의 비대칭·국면 문제 해결.
  일봉 게이트는 SMA100±2σ 부근. 1분 트리거는 RSI(14) turn(과매도서 위로 꺾임) 등.
- **수수료**: env `FEE`(테이커 왕복 0.0011 / 메이커 0.0004). 펀딩 미반영.
- **OOS**: 상반기 설정 → 하반기 적용. 무너지면 과적합.

## 주요 스크립트

**charts/**
- `quarterly_daily_bollinger.py` — 분기별 일봉 캔들 + 볼린저(z) 과매수/과매도 ★ (현재 표준 차트)
- `quarterly_daily_pct.py` — 분기별 일봉 + 백분위 극단 밴드
- `quarterly_daily_chart.py` / `quarterly_threshold.py` — (초기) N터치 임계 시각화
- `reversion_plot.py` — (초기) 1분 복귀확률 곡선

**backtests/**
- `bt_real_strategy.py` — **실제 봇 로직**(basic_entry/exit) 백테스트 ← 중요
- `bt_mtf.py` / `bt_mtf_sweep.py` — 일봉 z게이트 + 1분 RSI 트리거(turn/stretch), 일봉기간×k 스윕
- `bt_percentile_gate.py` — 일봉 백분위 게이트 + 1분 회귀 ±c
- `bt_adaptive.py` — 적응형 임계값(7일 5크로스, 봇 방식)
- `find_edge_pooled.py` — σ정규화 다중심볼 풀링 엣지 탐색
- (초기) `bt_a_b_c.py` `daily_grid*.py` `mtf_*.py` `validate_oos.py` `find_t_for_prob.py`
