"""Self-play simulator — 2-player HU NLHE 간이 엔진.

목적: R4 Bootstrap — 6종 baseline 전략 간 N 핸드 자기대전으로 population prior /
class prior 실증값 산출. 실서버 배포 전에 "warm-start" 용 DB 생성.

범위 (MVP):
  - 2-player heads-up.
  - NLHE 표준 룰 (preflop 3bet/4bet, postflop bet/raise/call/fold).
  - No-limit sizing 은 pot-ratio grid 에서 선택.
  - Showdown 평가는 `treys`.

범위 외 (후속):
  - 3+ way multiway.
  - Side pot.
  - Blind schedule 변화 (현재는 고정 1/2).
"""
