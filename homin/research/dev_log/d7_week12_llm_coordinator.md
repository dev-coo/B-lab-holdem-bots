# D7 Week 12 — LLM Coordinator

## Status
- **Stage**: Draft
- **Created**: 2026-04-20
- **Last updated**: 2026-04-20
- **Related code**: `meta/llm_coordinator.py`, `meta/llm_client.py`
- **Related configs**: `configs/llm.yaml`
- **Related BOT_GUIDE sections**: §5.3 (action_request 30s timeout)

## 1. Objective
EV candidate list 와 상황 context 를 받아, 필요한 경우에만 LLM 에게 선택권을 위임하는
coordinator 구현. 모든 실패 경로는 통계 argmax 로 수렴 (P6 원칙).

## 2. BOT_GUIDE Compliance
- [§5.3] LLM 호출 timeout 은 모델별 2–3초로 설정. 30s 하드 제한 내 3회 연속 실패도
  수용 가능.
- [§6.1] LLM 이 반환할 수 있는 action 은 fold/check/call/raise/allin 집합으로 스키마
  검증. 밖의 값은 fallback.

## 3. Method
### 3.1 Escalation gate
- `pick_tier(ranked, triggers, gate)` → 'none' | 'default' | 'standard' | 'critical'.
- flag 계산:
  - `top1_top2_ev_within_5pct`: top1 vs top2 의 `log_util` 상대 차이 ≤ 5%.
  - `variance_high`: top1.variance > 100 (chip 단위 임시 threshold).
  - `multiway_3plus_borderline` / `fold_equity_uncertain`: 외부에서 판단 후 주입.
  - `M_lt_6` / `near_bubble` / `stack_gt_100bb_pot_gt_50bb`: 전략 분기점.
- 가장 높은 tier 부터 평가 — critical 이 우선.

### 3.2 Prompt 조립
- system 은 `build_prompt` 가 직접 생성 (LLMClient 의 `system` 파라미터 사용 가능).
- 응답 형식: `'<action>'` 또는 `'raise@<N>'` 만 요구 — 설명 금지.

### 3.3 응답 파싱 (`parse_llm_action`)
- regex `\b(fold|check|call|allin)\b|raise(?:\s*@?\s*(\d+))?`.
- 대소문자 무관.
- raise 인데 amount 미매치 → 가장 가까운 amount 의 raise candidate 선택.
- 매치 실패 → None → fallback.

### 3.4 Coordinator.decide()
- 순위 정렬 (log_util 기본) → pick_tier → LLM 호출 → 파싱 → 결과 구성.
- `used_llm=False` 이고 `reason=statistical` 인 경우 LLM 호출 자체를 생략.
- 모든 실패는 top1 반환 (`used_llm=False, reason=fallback:...`).

## 4. Results
- `tests/test_llm_coordinator.py` — 14 cases:
  - pick_tier: no-escalation, close-EV → default, bubble → critical.
  - parse: fold/call/raise exact/nearest/case-insensitive/empty/gibberish.
  - build_prompt: candidates·context 포함.
  - Coordinator integration: statistical 경로, close-EV→LLM, timeout→fallback, schema_violation→fallback.
- 전체 회귀: **253 passed, 2 warnings, 3.0s** (+14 from D6).

## 5. Interpretation
### 5.1 policy.decide() 와의 관계
- 이번 단계에서는 coordinator 를 standalone 으로 완성. 실제 policy 경로에 배선하려면:
  1. `policy.decide()` 에서 후보 EV list 를 생성 (현재는 single branch 만 반환).
  2. Coordinator.decide 를 asyncio.run 으로 호출 (또는 CLI handler 에서 await).
  3. Coordinator 결과의 `candidate.action/amount` 를 `p.Action` 으로 변환.
- 이 배선은 Phase 2 로 유보 — 현 policy 의 preflop 차트 경로가 이미 안전하므로
  EV tree 가 preflop 에 적용될 때 함께 이관.

### 5.2 비용 관리
- default → sonnet 4.5, critical → opus 4.6. 모든 호출은 llm.yaml budget 로 캡.
- temperature=0.0 + snapshot test 로 회귀 감지.

## 6. Parameter Output
`configs/llm.yaml` 은 기존 값 유지. gate/triggers 는 아직 tuning 전 — 자기대전 이후
튜닝 예정.

## 7. Limitations & Caveats
- `_variance_high` threshold 100 은 chip 단위 임시값 — stack·pot 에 따라 적응 필요.
- Prompt 에 opponent profile (VPIP/PFR/상대 class) 는 아직 미포함. 추가 시 컨텍스트
  길이·캐싱 영향 평가.
- snapshot test (`tests/snapshots/llm_decisions.jsonl`) 는 yaml 에 경로만 지정, 아직
  생성 안 함. 첫 실서버 호출 후 생성 예정.

## 8. Next Steps
- E2E integration: cli handler 에서 coordinator 호출. 조건: EV tree 가 policy 에 연결된
  후 (Phase 2).
- Prompt 확장: opponent class weights + board_texture + SPR 같은 high-level 정보 주입.
- Snapshot test 도입 — 동일 입력 → 동일 action 재현.

## 9. References
- Section M (LLM 통합 표준), plan P5/P6.

## Changelog
- 2026-04-20 (v0.1): LLM Coordinator + escalation gate + parse + tests.
