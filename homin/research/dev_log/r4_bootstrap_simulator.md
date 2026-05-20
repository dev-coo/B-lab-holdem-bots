# R4 Bootstrap Self-Play Simulator

## Status
- **Stage**: Draft
- **Created**: 2026-04-21
- **Related code**: `src/holdem/simulate/strategies.py`, `src/holdem/simulate/engine.py`, `scripts/bootstrap_sim.py`
- **Related tests**: `tests/test_simulate.py`

## 1. Objective
서버 없이 6종 baseline 전략 간 HU NLHE 자기대전을 돌려 VPIP/PFR/AF 등 metric 의 실증 범위를 확보. R3 의 yaml 초안 수치를 검증/교정할 기반.

## 2. Method
### 2.1 전략
6종 (`all_strategies()`): random / callstation / nitrock / tag / lag / nashjam. 각 전략은 `BaselineStrategy.act(state, rng) -> Decision` 단일 인터페이스.

### 2.2 엔진
- `run_hand(sb, bb, sb_stack, bb_stack, bb=2, sb_amount=1, rng)` → HandResult.
- 2-player HU, 표준 preflop/flop/turn/river 베팅 라운드.
- raise cap = 3 per street.
- Showdown: treys `Evaluator`.

### 2.3 Bootstrap runner
- `scripts/bootstrap_sim.py --hands N` — 모든 전략쌍 round-robin.
- 각 매치업 별 승패 / showdown rate / VPIP / PFR / AF 집계.

## 3. Results (500 hands × 15 pairs)

```
== 전략별 평균 ==
  random        VPIP= 41.8%  PFR= 24.0%  AF=3.63
  callstation   VPIP= 63.0%  PFR=  0.0%  AF=0.00
  nitrock       VPIP=  5.2%  PFR=  5.1%  AF=48.23
  tag           VPIP= 12.8%  PFR= 12.5%  AF=64.24
  lag           VPIP= 25.7%  PFR= 25.4%  AF=208.24
  nashjam       VPIP= 13.7%  PFR= 13.4%  AF=62.11
```

7500 hands in 0.2s (aarch64, Python 3.11).

### 특징 확인
- callstation VPIP 63% + PFR 0% = 순수 수동 (정의 부합).
- nitrock VPIP 5% ≪ tag 13% ≪ lag 26% (계층 분리).
- AF 수치는 passive (call) 표본 희소로 상대적 지표 용도로만 활용.
- nitrock vs 나머지 showdown=0 → nitrock 이 preflop 에서 대부분 fold 해 postflop 도달 드뭄. bootstrap 데이터 활용 시 showdown 한정 metric (BLUFF_AT_SHOWDOWN) 은 nitrock 매치에서 수집 부족 예상.

## 4. Interpretation
이 결과는 **behavior 검증** 용. 실 서버 상대와 직접 비교 불가 (상대 풀이 다름). 용도:
1. `configs/priors.yaml` 의 VPIP/PFR 범위가 합리적 (5-65%) 임을 간접 확인.
2. bootstrap 데이터를 warm-start DB 로 주입하는 후속 작업에 쓸 원료.
3. 전략 자체의 회귀 테스트 — 코드 변경 후 VPIP 분포가 10% 이상 변동하면 버그 알림.

## 5. Limitations
- HU only — 4/6/9-max 확장은 후속.
- Fixed blind (1/2) — 블라인드 상승 시뮬레이션 없음. 토너먼트 특성 재현 안됨.
- No side pot — all-in 다중 시 정확도 떨어짐.
- AF 가 비정상적으로 큼 (passive 표본 부족). metric 정의 재검토 필요.

## 6. Next Steps
- bootstrap 결과를 `data/bootstrap_profiles.db` 로 덤프 (상대명 `__baseline_{strategy}` 로 저장).
- `configs/priors.yaml` 의 값과 자기대전 관측값 비교 → 편차 크면 재조정.
- 다중 인원 (3-9 player) HU 엔진으로 확장 — 블라인드 레벨별 시뮬 지원.

## 7. Changelog
- 2026-04-21 (v0.1): strategies + engine + runner + 7 tests + 7500 hands 실행 검증.
