# reversion_research

MA100 평균회귀 전략의 엣지를 데이터로 검증하는 연구 프로젝트.
(실거래 봇 `tradingBot`과 분리 — 여긴 순수 오프라인 백테스트/탐색.)

## 가설

> 가격이 MA100(이동평균)에서 임계값 T 이상 벗어나면 평균으로 회귀한다.
> 손절=익절을 같은 %(X)로 두면 대칭 게임이므로, 승률 > 50%면 무한반복 시 기대값 양수.

## 데이터

- Bybit 공개 kline(`/v5/market/kline`, 인증 불필요)을 받아 `data/*.pkl`에 로컬 캐시.
- 한 번 받으면 이후 실험은 **API 없이 로컬 캐시로** 돌아감 (rate-limit 회피).
- 현재 캐시: BTCUSDT/ETHUSDT/SOLUSDT 1분봉 1년(각 ~52만봉) + 일봉 3년.
- ⚠️ 1년 1분봉 = 심볼당 ~526 요청. 3심볼 연속이면 `retCode=10006` rate-limit 발생.
  `fetch_data.py`에 재시도/백오프 + 심볼간 대기 내장.

```bash
# 환경: anaconda executor-a2 (requests 포함). 출력 인코딩 강제 권장:
#   PYTHONIOENCODING=utf-8 python <script>.py
python fetch_data.py --list                       # 캐시 현황
python fetch_data.py --daily-universe              # 풀링용 유니버스 일봉(3년)
python fetch_data.py --m1 BTCUSDT --days 365       # 1분봉(무거움)
```

## 핵심 결론 (2026-06 현재)

1분/일봉/멀티TF/브래킷/보유기간을 OOS(상반기→하반기)로 엄격 검증한 결과:

- **단순 MA100 이탈만으로는 수수료를 이기는 견고한 엣지가 안 나옴.**
- 짧은 horizon 대칭 브래킷: OOS 승률 ~50%(동전던지기). IS에서 좋아 보여도 OOS 붕괴(과적합).
- **함정**: 시간초과(시장가 청산) 케이스를 ±X 만점으로 치면 환상이 생김 → 반드시 **실현손익**으로 계산.
- 1일봉 단독: 표본이 셀당 n=10~50뿐 → 50% vs 60% 통계적 구별 불가(노이즈 ±20%p).
- 변동성(σ) 정규화해도 심볼 간 패턴 정렬 안 됨, IS/OOS 대부분 붕괴.

**다음 관문(진행 예정): 다중 심볼 풀링**
- σ 정규화 후 20~30개 심볼의 (kσ 이탈, kσ 브래킷) 이벤트를 합쳐 표본을 수백~수천으로.
- 그래야 일봉 평균회귀의 엣지 유무를 통계적으로 검정 가능.

## 파일

| 파일 | 역할 |
|------|------|
| `reversion_calibrator.py` | 공용 코어: fetch+캐시, MA, calibrate, 출력 |
| `fetch_data.py` | 데이터 적재/갱신 (로컬 캐시) |
| `find_t_for_prob.py` | 목표 복귀확률 달성 최대 T 탐색 |
| `validate_oos.py` | 대칭 브래킷 OOS 검증 (IS→OOS) |
| `mtf_daily.py` / `mtf_grid.py` | 1일봉 필터/멀티TF (일봉×1분 조합) |
| `daily_grid.py` | 1일봉 단독 (T×X) 승률 그리드 |
| `daily_grid_vol.py` | 1일봉 σ정규화 (kσ×kσ) 그리드 + IS/OOS |
| `reversion_plot.py` | 복귀확률 시각화(matplotlib, base 아나콘다 필요) |

## 측정 규약 (중요)

- **이탈** = (price − MA100) / MA100. MA는 hlc3 기준.
- **복귀** = 움직이는 MA100 터치 (진입시점 고정값 아님).
- **승패** = TP(+X) 달성 승 / SL(−X) 달성 패 / 시간초과는 **실제 종가손익**.
- **수수료** = env `FEE`(기본 테이커 왕복 0.0011). 메이커는 0.0004. (펀딩 미반영)
- **OOS** = 상반기에서 고른 설정을 하반기에 그대로 적용. 무너지면 과적합.
