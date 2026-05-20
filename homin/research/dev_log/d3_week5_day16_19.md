# D3 Week 5 — Day 16–19 진행 기록

## Status
- **Stage**: Draft
- **Created**: 2026-04-19
- **Last updated**: 2026-04-19
- **Related code**: `src/holdem/estimate/stat_updater.py`, `src/holdem/state/profile_store.py`, `src/holdem/estimate/opponent_lookup.py`
- **Related configs**: `configs/priors.yaml`, `configs/class_priors.yaml`
- **Related BOT_GUIDE sections**: §5.3 (action_request), §5.4 (action_performed), §5.6 (hand_result)

## 1. Objective
"데이터가 누적되는 배관" 을 완성한다. 이벤트 스트림 → PlayerProfile metric → 상대별 shrunk
posterior rate 접근까지의 경로가 정상 작동하고, 이후 D4+ 에서 이 결과를 decision 에 주입하는
토대를 마련한다.

## 2. BOT_GUIDE Compliance
- [§5.4] `action_performed.action_history` 가 단독 이벤트가 아니라 `action_performed` 가 누적
  소스임을 구현에 반영 (GameState 가 매 이벤트마다 state.action_history 에 append).
- [§5.6] `hand_result` 를 영속 프로필 업데이트 트리거로 사용.
- [§3] 카드 표기(`Ah`) 는 metric 계산과 무관하므로 변경 없음.
- [§4] 포지션은 `PositionMap` 으로 이미 분류. 이번 단계에서는 metric → position 세분화는
  보류 (Day 20+ 과제).

위배 위험:
- `action_history` 에 blind post 가 포함되지 않으므로 VPIP 기회를 **모든 참가자** 에게 부여
  해도 안전 (자동 투입은 counted 안 됨). 다만 SB/BB 가 fold 한 경우에도 VPIP=False 로
  기록됨 — 동일한 관측 체계이므로 일관성 있음.

## 3. Method
### 3.1 모듈 배치
- `estimate/stat_updater.py` — `update_from_hand(profiles, history, participants)`.
- `state/profile_store.py` — `ProfileStore.on_hand_result(ev, game_state)` 훅.
- `estimate/opponent_lookup.py` — `posterior_rate(profile, metric, n_players)` / `opponent_rate(store, name, metric)`.
- `cli.py` — handler 에서 `isinstance(event, p.HandResult)` 조건 분기로 store 갱신.
- `decide/policy.py` — `DecideDeps.profile_store: Optional[ProfileStore]` 추가 (활용은 D5).

### 3.2 집계하는 metric (현 구현)
VPIP / PFR / THREE_BET / FOLD_TO_THREE_BET / CBET / FOLD_TO_CBET / BARREL_TURN /
BARREL_RIVER / CHECK_RAISE / aggression factor (postflop bet+raise vs call).

### 3.3 산출 정책
- 핸드 기회 판정:
  - VPIP/PFR — 참여자 전원.
  - THREE_BET — preflop 에서 VPIP(voluntary action) 한 자.
  - CBET — preflop 최종 aggressor 가 flop 에 도달했을 때.
  - FOLD_TO_CBET — flop 에서 cbet 을 마주한 자.
  - CHECK_RAISE — 동일 스트릿에서 check 이력이 있는 자.

## 4. Results
### 4.1 테스트
- `tests/test_stat_updater.py` — 8 케이스 (VPIP/PFR/3bet/CBET/CHECK_RAISE/aggression/empty/multi).
- `tests/test_profile_store.py` — 3 케이스 (update-on-result, 누적, missing room).
- `tests/test_opponent_lookup.py` — 5 케이스 (None profile, large personal, store lookup, missing store, data-rich flag).
- 전체 회귀: **169 passed, 2 warnings, 3.1s**.

### 4.2 샘플 수치
`posterior_rate(None, "CBET", 9)` → ~0.70 (priors only).
`posterior_rate(profile_with_20_hits_0_misses, "CBET", 9)` → ~0.80 (shrinkage blend, τ_class+τ_pop=48 내에서 personal 20 비중).

## 5. Interpretation
### 5.1 핵심 발견
- 프로필 → shrunk rate 까지의 경로가 "파라미터 이름 기반" 으로 단일 API 에 수렴.
- class_typer 는 min_hands=20 이하에서 균등 반환 → shrinkage 는 언제나 population + uniform class 를 baseline 으로 유지. 콜드 스타트에서도 broken 이 아님.

### 5.2 우리 서버로의 전이 가능성
`n_players` 파라미터로 서버 4/6/9-max 분기. 라이브 decision 경로가 `req.players` 의 길이로
호출하면 config/priors.yaml 이 제공한 block 에 매핑됨.

### 5.3 전이 불가능 영역
- 쇼다운 bluff 라벨은 미구현. hand_result.showdown 의 공개 카드가 필요하며, 베팅 시점
  equity 재계산이 필요 → 배치 처리 큐 (별도 Day).
- BARREL_TURN/RIVER 는 "이전 스트릿에서 본인이 cbet 했는가" 에 의존 → 현 구현은
  in-memory per-hand state. 여러 핸드에 걸친 행동 공간은 포괄하지 않음.

## 6. Parameter Output
이 단계에서 새로 추가된 yaml 값 없음. 기존 `priors.yaml` / `class_priors.yaml` 을 읽어들이는
경로가 완성됨. 다음 단계에서 EDA 기반 값으로 swap 예정.

## 7. Limitations & Caveats
- `allin` 을 raise 로 취급하는 단순화 — 올인이 raise 와 의미 차이가 있을 수 있지만
  현 단계에선 단일 증분으로 처리.
- CHECK_RAISE 기회 판정이 "check 한 스트릿 수" 로 coarse — 실제로는 "facing a bet after
  checking" 이 정확한 분모. 추후 D4+ 에서 조정 가능.
- `faced_three_bet` 은 오프너가 이미 raise 한 후에만 설정 — 실제 preflop 에서 오픈 전
  3bet (squeeze) 상황에서는 취급이 단순화.

## 8. Next Steps
- Day 20: SQLite persist 계층 (`persist/db.py`) — 세션 재시작 시 profile 복원.
- Day 21+: policy 에서 opponent_rate 를 활용한 RFI 소형 조정 (tight 상대에겐 3bet 축소 등).
- D4 (Week 7-8): ConservatismProfile 에 `n_effective` 계산 소스로 profile 사용.

## 9. References
- `research/parameters/population_prior_rationale.md`
- `research/parameters/class_prior_rationale.md`
- `research/bot_guide_extracts.md` §5

## Changelog
- 2026-04-19 (v0.1): D3 Day 16–19 완료. stat_updater + ProfileStore + opponent_lookup + CLI 배선.
