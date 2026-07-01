"""상대 뻥카 확률 실시간 조회 + Strategy 통합 헬퍼.

런타임 플로우
-------------
1. `_postflop` 진입 시 `estimate_opp_bluff_prob(req, store)` 호출
2. 내부에서 `req.action_history` 를 훑어 **마지막 공격적 상대 액션** 찾음
   (internet heads-up 경우) or **가장 최근 aggressive action 의 주인** (multiway).
3. `sizing_bucket + street + action_type` 키로 `BluffPriorStore.lookup`
4. 반환: `OppBluffEstimate(prob, confidence, key, player)` — meta 에 기록

"마지막 공격적 액션" 정의:
- 현재 phase 에서 player ≠ 나 인 raise/allin 중 가장 최근 것.
- phase 에 없으면 직전 phase 의 마지막 aggressive.

posterior 업데이트 경로
----------------------
`on_hand_result` 에서:
1. showdown 공개된 player 들 → 각자의 aggressive action 각각에 대해
   (그 시점의 hand equity vs random board runout) 로 hard label.
2. 쇼다운 없이 winners 에 있는 player 가 이 핸드에서 aggressive action 을
   최소 1개 했다면 → 그 **마지막 aggressive action** 에 soft_fold_win.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from holdem_core.equity import equity_mc
from holdem_core.models.events import ActionHistoryItem, ActionRequest, HandResult

from holdem_main_bot.bluff_prior import (
    ActionType,
    BluffPriorStore,
    SizingBucket,
    Street,
    action_type,
    sizing_bucket,
)


@dataclass(frozen=True)
class OppBluffEstimate:
    player: str | None
    action: ActionType | None
    sizing: SizingBucket | None
    street: Street | None
    prob: float  # 0..1 — 이 공격적 액션이 뻥카일 posterior 확률
    confidence: float  # 0..1 — 샘플 신뢰도
    reason: str  # 디버그: no_aggression / found / global_prior 등


# ─── 조회 경로 ────────────────────────────────────────────────────────────────


def _latest_opp_aggressive(
    history: list[ActionHistoryItem], my_name: str | None, current_phase: str, current_pot: int
) -> tuple[ActionHistoryItem, int, int] | None:
    """상대의 가장 최근 aggressive action + 그 라운드의 (raise_cnt_before, pot_before) 반환.

    pot_before 는 정확 계산이 아니라 근사: current_pot 에서 히스토리 역산.
    불가능하면 current_pot 자체를 사용 (sizing_bucket 은 ratio 기반이라 보수적으로 과대 추정).
    """
    # phase-per-round raise counter. history 는 시간 순서.
    per_phase_raise_count: dict[str, int] = {}
    target: ActionHistoryItem | None = None
    raise_cnt_before_target = 0
    for item in history:
        d = item if isinstance(item, dict) else item.model_dump()
        ph = d.get("phase")
        act = d.get("action")
        player = d.get("player")
        if not ph or not act:
            continue
        is_agg = act in ("raise", "allin")
        cur_cnt = per_phase_raise_count.get(ph, 0)
        if is_agg and player != my_name:
            target = item
            raise_cnt_before_target = cur_cnt
        if is_agg:
            per_phase_raise_count[ph] = cur_cnt + 1
    if target is None:
        return None
    # pot_before_target 은 정확히 모르니 current_pot 사용 — ratio 비율 측정에는 무리 없음.
    return (target, raise_cnt_before_target, current_pot)


def _my_player_name(req: ActionRequest) -> str | None:
    for p in req.players:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if d.get("position") == req.seat:
            name = d.get("name")
            return name if isinstance(name, str) else None
    return None


def estimate_opp_bluff_prob(
    req: ActionRequest,
    store: BluffPriorStore,
) -> OppBluffEstimate:
    my_name = _my_player_name(req)
    history = list(req.action_history)
    found = _latest_opp_aggressive(history, my_name, req.phase, req.pot)
    if found is None:
        # 공격적 액션 없는 상태 (내가 첫 공격자 or 모두 check/call) — 뻥카 판정 불가.
        return OppBluffEstimate(
            player=None,
            action=None,
            sizing=None,
            street=None,
            prob=0.25,  # 중립
            confidence=0.0,
            reason="no_aggression",
        )
    item, raise_cnt_before, pot_ref = found
    d = item if isinstance(item, dict) else item.model_dump()
    player = d.get("player")
    if not isinstance(player, str):
        return OppBluffEstimate(None, None, None, None, 0.25, 0.0, "unknown_player")
    phase = d.get("phase") or req.phase
    is_pre = phase == "preflop"
    atype = action_type(d.get("action") or "", raise_cnt_before, is_pre)
    if atype is None:
        return OppBluffEstimate(None, None, None, None, 0.25, 0.0, "not_aggressive")
    amount = int(d.get("amount") or 0)
    sizing = sizing_bucket(amount, pot_ref, to_call=0)
    prob, conf = store.lookup(player, phase, sizing, atype)
    return OppBluffEstimate(
        player=player,
        action=atype,
        sizing=sizing,
        street=phase,
        prob=prob,
        confidence=conf,
        reason="found" if conf > 0 else "global_prior",
    )


# ─── 업데이트 경로 (on_hand_result) ──────────────────────────────────────────


def _iter_aggressive_in_hand(
    history: list[dict[str, Any]], my_name: str | None
) -> list[tuple[str, Street, SizingBucket, ActionType, int]]:
    """이 핸드의 모든 상대 aggressive action → (player, street, sizing, atype, amount)."""
    out: list[tuple[str, Street, SizingBucket, ActionType, int]] = []
    per_phase_raise_count: dict[str, int] = {}
    running_pot = 0
    for item in history:
        ph = item.get("phase")
        act = item.get("action")
        player = item.get("player")
        amount = int(item.get("amount") or 0)
        if not ph or not act:
            continue
        is_agg = act in ("raise", "allin")
        cur_cnt = per_phase_raise_count.get(ph, 0)
        if is_agg and player and player != my_name:
            pot_ref = max(running_pot, 1)
            sz = sizing_bucket(amount, pot_ref, to_call=0)
            at = action_type(act, cur_cnt, ph == "preflop")
            if at is not None:
                out.append((player, ph, sz, at, amount))  # type: ignore[arg-type]
        if is_agg:
            per_phase_raise_count[ph] = cur_cnt + 1
        # running_pot 근사: call/raise/allin amount 누적. 정확하진 않지만 비율용.
        if act in ("call", "raise", "allin", "bet"):
            running_pot += amount
    return out


def _equity_vs_random(cards: list[str], board_snapshot: list[str], samples: int = 300) -> float:
    """쇼다운 핸드의 "그 시점" equity 근사. board_snapshot 은 aggressive 시점의 보드."""
    try:
        if len(cards) < 2:
            return 0.5
        return equity_mc(cards, board_snapshot, samples=samples, opp_combos=None)
    except Exception:
        return 0.5


def _board_at_street(community_cards: list[str], street: str) -> list[str]:
    """final community_cards 에서 해당 street 시점 보드 슬라이스."""
    if street == "preflop":
        return []
    if street == "flop":
        return community_cards[:3]
    if street == "turn":
        return community_cards[:4]
    return community_cards[:5]


def observe_hand_result(
    result: HandResult,
    history: list[Any],
    store: BluffPriorStore,
    my_name: str | None,
    equity_samples: int = 300,
) -> int:
    """한 핸드 결과를 store 에 반영. 업데이트된 버킷 수 반환."""
    history_raw = [
        h if isinstance(h, dict) else (h.model_dump() if hasattr(h, "model_dump") else dict(h))
        for h in history
    ]
    showdown = list(result.showdown or [])
    community = list(result.community_cards or [])
    winners = {
        w.get("name") for w in (result.winners or []) if isinstance(w, dict) and w.get("name")
    }

    # 1) 쇼다운 카드 공개된 상대 → 각 aggressive action 에 hard label
    revealed: dict[str, list[str]] = {}
    for s in showdown:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        cards = s.get("cards") or []
        if isinstance(name, str) and name and name != my_name and len(cards) >= 2:
            revealed[name] = list(cards)

    aggressive = _iter_aggressive_in_hand(history_raw, my_name)
    updated = 0
    seen_hard_for_player: set[str] = set()
    for player, street, sizing, atype, _amt in aggressive:
        if player in revealed:
            # 그 플레이어의 이 핸드 모든 aggressive action 에 대해 hard label
            board_snap = _board_at_street(community, street)
            eq = _equity_vs_random(revealed[player], board_snap, samples=equity_samples)
            store.update_hard(player, street, sizing, atype, eq)
            seen_hard_for_player.add(player)
            updated += 1

    # 2) 쇼다운 없이 이긴 aggressive 플레이어 → 마지막 aggressive 에 soft_fold_win
    last_agg_by_player: dict[str, tuple[Street, SizingBucket, ActionType]] = {}
    for player, street, sizing, atype, _amt in aggressive:
        if player in seen_hard_for_player:
            continue  # hard label 받은 애는 skip
        if player in winners:
            last_agg_by_player[player] = (street, sizing, atype)

    for player, (street, sizing, atype) in last_agg_by_player.items():
        store.update_soft_fold_win(player, street, sizing, atype)
        updated += 1

    return updated
