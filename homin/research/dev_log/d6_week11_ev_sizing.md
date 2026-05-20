# D6 Week 11 — EV Tree + Sizing Optimizer

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Related code**: `decide/ev.py`, `decide/sizing.py`
- **Related BOT_GUIDE sections**: §6.2 (raise total amount 정의)

## 1. Objective
후보 액션 (fold/check/call/raise@S/allin) 각각의 chip-EV 와 log-utility 를 동일한 시그니처
로 계산하는 공통 블록을 제공. Sizing grid 가 허용한 raise 사이즈만 enumerate 해 objective
기반으로 best pick.

## 2. BOT_GUIDE Compliance
- [§6.2] raise amount = 이번 라운드 총 베팅액. `EVInputs.my_bet` (이미 투입) 과 `delta =
  amount − my_bet` 을 분리해 수식이 올바르게 chip 증분을 계산.
- forced jam (stack ≤ to_call) 은 all-in 후보를 항상 포함.

## 3. Method
### 3.1 EV 수식 (부록 C)
```
EV_fold   = 0
EV_call   = eq · (pot + to_call) − to_call
EV_raise@S = p_fold · pot
           + p_call · (eq · (pot + 2·ΔS) − ΔS)
           + p_reraise · (−ΔS)           # 1-ply 보수 근사
```
- `p_fold/p_call/p_raise` 는 `DirichletResponse.sample()` 한 회 — Thompson 1-sample 일관.
- `p_reraise` 경로는 "우리가 fold" 로 보수 근사 (D6 1-ply 한계).

### 3.2 log-utility (평가 C1)
```
U(s) = log(s + ε)
EV_util = eq · U(win_stack) + (1−eq) · U(lose_stack)
         (raise 는 fold/call/reraise 세 경로 가중합)
```
- ε = BB (콜드 구간의 stack floor 역할). 실서버 튜닝 대상.
- 올인 + 저equity 는 log 가 발산하여 자연 기각 (unit test 로 검증).

### 3.3 Sizing enumeration
- `ConservatismProfile.sizing_grid.value_bet` (또는 `bluff_bet`) 에서 ratio 추출.
- `amount = my_bet + round(ratio · pot_before)`.
- `allow_allin=False` 이고 forced_jam 아니면 all-in 후보 제외.
- 이미 grid 에서 all-in 에 도달하면 중복 추가 방지.

## 4. Results
- `tests/test_ev.py` — 11 cases (fold/check/call break-even, raise fold/sticky, log_util 안전장치).
- `tests/test_sizing.py` — 7 cases (cold→no allin, heavy→has allin, forced jam, optimize picks).
- 전체 회귀: **239 passed, 2 warnings, 3.1s** (+18 from D5).

## 5. Interpretation
### 5.1 EV 와 policy.decide() 의 관계
- 현재 `decide/policy.py` 는 chart + pot_odds 기반으로 단순 call/fold/raise. D6 모듈은
  standalone building block 이며, D7 LLM coordinator 또는 후속 리팩토링이 policy 를
  EV-tree 기반으로 재배선할 예정.
- 교체 포인트 (후속):
  - `_decide_midlow_and_deep` postflop: `optimize(cons, response, inputs)` 로 교체 가능.
  - 단, `response` 의 per-situation 테이블(response_store) 이 필요 — D7 연계.

### 5.2 왜 1-ply 로 멈추는가
- 2-ply 이상은 run-time 예산(30s 제약)과 상대 range inference 정확도가 동시 필요.
- 1-ply + IG bonus + conservatism veto 의 조합이 실전 대부분의 결정을 커버한다고 판단
  (평가 C3 의 realization factor 매직넘버 제거도 1-ply 유지의 이유).

### 5.3 한계
- `p_reraise` 경로 보수 근사 — 실제로 3bet 후 우리가 call 하는 시나리오가 일부 존재.
  튜닝 대상.
- `bluff_factor` 는 아직 미반영. bluff 후보를 생성할 때 EV 에 스케일링을 가하는 식으로
  D7 에서 통합.

## 6. Parameter Output
새로운 yaml 없음. ε (log-utility floor) 는 코드 내 상수(=BB). 튜닝 여부는 자기대전 이후.

## 7. Limitations & Caveats
- 멀티웨이 정확도 — `DirichletResponse` 는 단일 상대 가정. 3+way 에서는 sample 을 한
  상대에 대해 적용 후 다른 상대는 "독립 action" 으로 근사 (평가 G7 한계 재확인).
- `variance` 필드는 현재 값 선택에 사용되지 않음 — I.3 의 λ · Var 페널티가 log-utility 로
  흡수됨 (C1 단일화).

## 8. Next Steps
- D7 Week 12: LLM Coordinator — borderline EV 분기 (top1/top2 차이 < X) 에서 LLM 에게
  최종 선택권. EV 모듈의 `pick_best` 결과에 태그를 달아 escalation 조건 확인.
- Response store: per-situation DirichletResponse 저장소 (SQLite or in-memory).
- policy.decide postflop 리팩토링 후 EV 기반으로 교체.

## 9. References
- plan 부록 C (EV 수식), 4-1 (sizing), C1 (log-utility).

## Changelog
- 2026-04-19 (v0.1): EV tree + sizing optimizer 모듈 + 18 tests.
