# Phase 2 통합 #3 — Triggers + Budget

## Status
- **Stage**: Draft
- **Created**: 2026-04-20
- **Related code**: `meta/triggers.py`, `meta/budget.py`, `meta/llm_coordinator.py`, `cli.py`

## 1. Objective
- `EscalationTriggers` 를 ActionRequest 기반으로 자동 계산 — M<6, bubble, deep big pot,
  multiway, fold_equity_uncertain 플래그.
- LLM 호출 예산 강제 — configs/llm.yaml 의 per_hand/per_game/per_minute/per_day 를
  BudgetTracker 로 추적. 초과 시 fallback.

## 2. Method
### 2.1 triggers.py
- `build_triggers(req, bot_name, profile_store=None)` → EscalationTriggers.
- `fold_equity_uncertain` — profile_store 있으면 최소 관측 수 기반, 없으면 보수적 True.
- `near_bubble` — remaining ∈ (2, 3] 이면서 m≥1.

### 2.2 budget.py
- `BudgetTracker` — 4종 카운터 (hand/game/minute/day).
- `allow_call(room_id, hand_number)` → (ok, reason).
- `record_call(room_id, hand_number)` — 카운터 증가.
- `on_hand_end` / `on_game_end` — 범위별 카운터 정리.
- minute window 는 60초 롤링 prune.

### 2.3 coordinator 통합
- `Coordinator.__init__(..., budget=BudgetTracker | None)`.
- `decide(..., room_id=, hand_number=)` 에서 tier 비-none 이면 budget 체크. 통과 시
  `record_call`, 실패 시 statistical fallback (reason="fallback:budget_{hand,game,minute,day}").

### 2.4 policy.decide_async 통합
- triggers 인자 None 이면 `build_triggers(req, bot_name, profile_store)` 자동 호출.
- coordinator.decide 에 room_id/hand_number 전달.

### 2.5 cli.py 배선
- `--use-coordinator` 경로에서 `BudgetTracker.from_yaml()` 주입.
- `HandResult` 수신 시 `budget.on_hand_end()` 호출.
- `GameEnd` 수신 시 `budget.on_game_end()` 호출.

## 3. Results
- `tests/test_triggers.py` — 12 cases.
- `tests/test_budget.py` — 9 cases.
- `tests/test_llm_coordinator.py` 에 budget 테스트 2 추가 (gate 차단, record_call 후 재호출 차단).
- 전체 회귀: **287 passed** (264 → +23).

## 4. 실서버 사용 흐름
```
uv run python -m holdem.cli --use-ev-tree --use-coordinator --profile-db data/profiles.db
```
1. ActionRequest 도착.
2. `decide_async` → postflop 이면 candidates 생성.
3. `build_triggers` → `EscalationTriggers` 자동 계산.
4. `coordinator.decide` → tier 판정 → budget 허용 시 LLM 호출.
5. LLM 응답 파싱 → candidate → Action 전송.
6. HandResult → budget/profile/db 갱신.
7. GameEnd → budget game 카운터 리셋.

## 5. Limitations
- minute_window 는 list prune. 호출이 잦으면 O(n). 실서버 부하에서는 deque 로 전환 검토.
- snapshot test 미구현. 동일 (EV, triggers) 입력에서 coordinator decision 일관성은 단위
  테스트로만 검증됨.
- budget reason 은 현재 로그에만 — Prometheus/datadog 같은 관측 연결은 후속.

## 6. Next Steps
- Per-situation DirichletResponse store (hand 종료 시 `coordinator.budget` 같이 update).
- R4 bootstrap self-play 시뮬레이터 — 10k 자기대전으로 priors 재튜닝.
- 실서버 smoke — deploy API 해결 후.

## 7. Changelog
- 2026-04-20 (v0.1): triggers.py + budget.py + coordinator integration + CLI hooks + 23 tests.
