# Multi-way Engine (N=2~9) + Side Pots

## Status
- **Stage**: Draft
- **Created**: 2026-04-22
- **Related code**: `src/holdem/simulate/engine_multi.py`
- **Related tests**: `tests/test_engine_multi.py` (12 — 4 side-pot units + 8 integration)

## 1. Objective
HU 전용 `engine.py` 한계 제거. 3~9인 NLHE 핸드를 정확히 시뮬 + side pot 분배 구현.

## 2. Design
### 2.1 PlayerState / MultiHandResult
- `PlayerState(idx, strategy, stack, hole, bet_this_street, total_bet, folded, allin)`.
- `MultiHandResult(winner_idx_per_pot: list[list[int]], pots: list[SidePot], ...)`.

### 2.2 Action order
- Preflop: `first_to_act = (BB_idx + 1) % n = (SB_idx + 2) % n`. n=2 예외 → SB first.
- Postflop: SB (또는 시계방향 첫 non-folded).

### 2.3 Side pot 분할
`_compute_side_pots`:
```
ceilings = sorted({p.total_bet for p in players if p.total_bet > 0})
for cap in ceilings:
    amount = Σ (min(p.total_bet, cap) - last_cap)
    eligible = non-folded contributors
    if amount > 0 and eligible: pot
    last_cap = cap
```

Folded 플레이어의 투입은 pot 기여하지만 자격 없음 (핵심 포커 규칙).

## 3. Verification
Unit side-pot 케이스:
- 단일 pot (균등 bet): 1 pot.
- 1 allin (10) vs 2 full (30): main=30, side=40.
- 1 fold(10) + 1 allin(20) + 1 full(30): 30 / 20 / 10 (3 tier).
- 3-way all-in 상이한 ceiling: 30 / 30 / 15.

Integration: 3/4/6인 핸드 chip conservation, all-fold 자동 승자, HU 케이스 backward compat.

## 4. Sanity (200 hands 6-way)
```
strategies=[random, callstation, nitrock, tag, lag, nashjam]
avg pots/hand = 2.54   # 멀티 올인으로 자연스럽게 side pot 빈번.
main-pot wins:
  callstation 100  random 45  lag 25  tag 13  nashjam 13  nitrock 4
```
→ nitrock 최하 (멀티웨이 fold 누적 → 블라인드 소멸), callstation 상위 (showdown 도달 많음).

## 5. Limitations
- Rake/antes 없음.
- 포지션 회전(dealer button 이동) 은 호출자가 관리 (tournament 래퍼가 필요).
- Multi-way 전략들은 기존 HU 가정으로 설계된 baseline (TAG/LAG/NitRock) — 3+way 에서 suboptimal.

## 6. Integration Next
- `tournament.py` 를 N-way 확장 (현재 HU only).
- Policy (`decide/policy.py`) 의 멀티웨이 보수 가정 검증 (plan H.8: `P(all_fold)=min(fᵢ)^n`).

## 7. Changelog
- 2026-04-22 (v0.1): engine_multi.py + side pot + 12 tests.
