# Phase 2 통합 #1 — EV Tree 를 Policy Postflop 경로에 배선

## Status
- **Stage**: Draft
- **Created**: 2026-04-20
- **Related code**: `src/holdem/decide/policy.py`
- **Related tests**: `tests/test_policy_ev_tree.py`

## 1. Objective
D6 의 `decide.ev.optimize()` 를 `policy.decide` 의 postflop 분기에 **opt-in** 플래그로
배선한다. 기본값은 기존 pot_odds 경로 유지 — 회귀 없음.

## 2. Method
- `DecideDeps.use_ev_tree_postflop: bool = False` 추가. `True` 설정 시 postflop 결정이
  `_decide_postflop_ev(req, deps)` 로 라우팅.
- `_decide_postflop_ev`:
  1. `equity_from_cards(...)` 로 현재 핸드·보드 기반 equity 계산.
  2. `_table_conservatism(req, "", deps)` 로 ConservatismProfile 획득.
  3. `EVInputs` 구성 (pot/to_call/my_stack/my_bet/equity/bb).
  4. 기본 `DirichletResponse(1,1,1)` + `ev_optimize(...)` → best EVCandidate.
  5. 서버 min_raise·my_stack 경계 보정 후 `p.Action` 변환.
- `ev_seed` 도 추가 — 테스트 결정성을 위한 `random.Random(seed)` 주입.

## 3. Results
- `tests/test_policy_ev_tree.py` — 4 cases:
  - AA 강한 equity → fold 아님.
  - 72o vs 팟의 10배 to_call → call 아님 (fold 또는 bluff-raise).
  - no to_call → check 가능.
  - preflop 은 영향 없음.
- 전체 회귀: **257 passed** (+4 from D7 완료 시점).

## 4. Limitations
- `DirichletResponse(1,1,1)` 은 상황별 학습된 반응이 아님 → 33/33/33 가정이 "blindly
  bluff-friendly" 한 결과를 만들 수 있음. per-situation response store 는 후속.
- my_bet 추출: `req.players` 에서 `seat`/`position` 매칭. 정확한 필드 매칭은 서버
  스키마에 따라 튜닝 필요.
- LLM Coordinator 와의 결합은 아직 미구현 — `decide` 가 단일 Action 을 반환하기 때문에
  coordinator 가 top1/top2 차이를 볼 수 없음. 다음 통합 (Phase 2 #2) 과제.

## 5. Next Steps
- Phase 2 #2: `decide_candidates(req, deps) -> list[EVCandidate]` 엔트리 추가 후
  CLI handler 에서 coordinator 호출 여부 분기.
- Per-situation `DirichletResponse` store — in-memory dict by `(phase, pos_class, ctx)`.
  ProfileStore 와 유사하게 hand_result 시점에 observe.

## 6. Changelog
- 2026-04-20 (v0.1): EV tree opt-in postflop 배선 + 4 tests.
