# Phase 2 통합 #4 — Per-Opponent × Phase Response Store

## Status
- **Stage**: Draft
- **Created**: 2026-04-21
- **Related code**: `state/response_store.py`, `state/profile_store.py`, `decide/policy.py`
- **Related tests**: `tests/test_response_store.py`

## 1. Objective
EV tree 의 `ev_raise` 경로가 고정 Dirichlet(1,1,1) 을 사용해 상대 반응을 균등 가정하던
문제를 해소. 상대별 × phase 별 관측 기반 사후분포로 교체 → bluff 과적합 방지.

실서버 첫 smoke (2026-04-21 10:49 KST, room 359) 에서 hand 2 river allin 으로 조기
탈락 → 원인: coordinator / EV tree 경로가 33/33/33 fold 가정으로 bluff raise 가 +EV 로 산출.

## 2. Method
### 2.1 `state/response_store.py`
- `ResponseStore.table: dict[(opp_name, phase), DirichletResponse]`.
- `lookup(name, phase)` — 없으면 신규 DirichletResponse(1,1,1) 생성.
- `aggregate(names, phase)` — 관측 있는 상대들의 alpha 합산. 빈 시작점에서 시작해
  baseline 중복 방지.
- `observe_from_hand(history)` — action_history 순회하며 `DirichletResponse.observe(action)`.

### 2.2 `ProfileStore` 통합
- `ProfileStore.responses: ResponseStore = field(default_factory=ResponseStore)`.
- `on_hand_result` 에서 `update_from_hand` 호출 직후 `responses.observe_from_hand(history)`
  동시 업데이트.

### 2.3 Policy 사용
- `postflop_candidates` 와 `_decide_postflop_ev` 가 하드코딩 `DirichletResponse()` 대신
  `_aggregate_response(req, deps)` 호출.
- store 없거나 관측 없는 상대면 기본 (1,1,1) 반환 → 기존 동작과 호환.

## 3. Results
- `tests/test_response_store.py` — 6 케이스 (lookup default / observe per-phase /
  aggregate / unknown → default / n_opponents / allin → raise).
- 전체 회귀: **293 passed** (+6 from 287).

## 4. 실서버 효과 예상
- 수집된 관측이 쌓일수록 EV tree 의 p_fold / p_call / p_raise 가 상대별로 조정됨.
- "calling station" 상대 (p_call 높음) 에 대해 bluff raise 의 EV 가 자연스럽게 −EV 로
  산출 → river jam 억제.
- 단, 대부분의 실전 결정은 현재 push_fold 또는 chart 경로 (postflop `--use-ev-tree`
  미활성) 이므로 즉각적 효과는 EV tree opt-in 시만 나타남.

## 5. Limitations
- `phase` 만 키 — position / SPR / pot 크기 context 는 분리 안 됨. MVP 수준.
- blind 자동 투입 제외 (BOT_GUIDE §5.4) — VPIP 와 같은 기준으로 "voluntary response" 만 집계.
- 데이터 영속 미구현. 세션 종료 시 소실 (ProfileStore 는 SQLite 저장되지만 ResponseStore 는
  미포함). 다음 이터레이션에서 JSON 직렬화 추가.

## 6. Next Steps
- ResponseStore SQLite 영속 (profile_db 에 별도 테이블).
- Context 키 확장: `(opp_name, phase, last_bet_size_bucket, pot_spr_bucket)`.
- Snapshot test — (history, store state) → (coordinator decision) 재현성.

## 7. Changelog
- 2026-04-21 (v0.1): ResponseStore + wire-up + 6 tests + policy 통합.
