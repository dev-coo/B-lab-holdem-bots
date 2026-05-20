# Phase 2 통합 #2 — Coordinator 를 CLI 에 배선

## Status
- **Stage**: Draft
- **Created**: 2026-04-20
- **Related code**: `decide/policy.py`, `cli.py`
- **Related tests**: `tests/test_policy_async.py`

## 1. Objective
D7 LLM Coordinator 를 실제 봇 런타임에 연결. postflop EV candidates → coordinator →
Action 경로가 CLI 플래그로 opt-in 가능.

## 2. Method
### 2.1 policy 쪽 추가
- `postflop_candidates(req, deps) -> list[EVCandidate]` — coordinator 입력용 후보 목록.
- `candidate_to_action(cand, req, my_bet)` — EVCandidate → 서버 전송용 Action (min_raise/
  stack 경계 보정 공통 로직).
- `decide_async(req, bot_name, deps, coordinator)` — async 엔트리. preflop 또는 EV-tree
  비활성 시 sync `decide()` 로 폴백. postflop + coordinator 제공 시 candidates 생성 →
  coordinator.decide → Action 변환.

### 2.2 CLI 쪽 변경
- `--use-ev-tree` : `DecideDeps.use_ev_tree_postflop = True`.
- `--use-coordinator` : LLMClient 생성 후 Coordinator 래핑. `--use-ev-tree` 미설정 시
  경고 후 무시.
- handler 가 `await decide_async(...)` 로 전환.

## 3. Results
- `tests/test_policy_async.py` — 7 cases:
  - candidates 에 fold/check/raise 포함, equity 실패 시 빈 리스트.
  - `candidate_to_action` min_raise/stack 캡 검증.
  - coordinator=None 이면 sync 동일, preflop 이면 coordinator 무시.
  - LLM result 가 유효한 action 으로 변환되거나 fallback.
- 전체 회귀: **264 passed** (Phase 2 #1 완료시 257 → +7).

## 4. Interpretation
### 4.1 동작 경로
```
ActionRequest
  ↓
decide_async(req, bot, deps, coordinator)
  ├─ preflop OR not use_ev_tree → decide() (sync chart 경로)
  └─ postflop + ev-tree + coordinator
       ├─ postflop_candidates(req, deps) → list[EVCandidate]
       ├─ empty? → decide() fallback
       ├─ coordinator.decide(candidates, triggers, context)
       │    ├─ pick_tier → none/default/critical
       │    ├─ none → top1 (statistical)
       │    └─ LLM 호출 → parse_llm_action
       │         ├─ ok → LLM choice
       │         └─ fail → top1 (fallback)
       └─ candidate_to_action → Action
```

### 4.2 실서버 사용법
```
uv run python -m holdem.cli --use-ev-tree --use-coordinator \
    --profile-db data/profiles.db
```

`--use-coordinator` 만 단독 사용 불가 — ev-tree 가 candidates 를 생성해야 함.

## 5. Limitations
- `EscalationTriggers` 는 현재 CLI 에서 생성되지 않음 (기본값만). M<6, 버블 등의 상황
  플래그 계산을 `decide_async` 직전에 추가해야 opus escalation 이 트리거됨.
- `postflop_candidates` 는 매번 equity MC 를 실행 — coordinator 가 gate 에서 탈락해도
  MC 비용이 발생. 최적화: coordinator 가 none 반환하면 enumerate 스킵하도록 lazy 화.
- Coordinator 호출 시 per-hand budget (llm.yaml) 는 아직 적용되지 않음 — counter
  hook 이 D7 TODO 로 남아있음.

## 6. Next Steps
- Triggers 계산기: `build_triggers(req, deps)` — M, stack, pot 비율로 플래그 세팅.
- Budget tracker: Hook 기반 per-hand / per-game 카운터.
- Snapshot test 도입 — 동일 EV candidates 입력 시 동일 coordinator decision 재현.

## 7. Changelog
- 2026-04-20 (v0.1): decide_async + CLI --use-coordinator 배선 + 7 tests.
