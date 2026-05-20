"""멀티룸 동시 게임 처리 검증 (BOT_GUIDE §7).

서버가 여러 방에 동시 배정 시 각 이벤트의 `room_id` 로 상태를 분리하는지.
기존 설계는 이미 room_id 키 분리 — 본 테스트는 regression 방지.
"""
from __future__ import annotations

import pytest

from holdem.meta.budget import BudgetLimits, BudgetTracker
from holdem.state.game_state import GameState
from holdem.state.profile_store import ProfileStore
from holdem.transport import protocol as p


def _hand_start(room_id: int, hand_no: int, cards: list[str]) -> p.HandStart:
    return p.HandStart(
        type="hand_start", room_id=room_id, hand_number=hand_no,
        your_cards=cards, your_stack=300, your_seat="sb",
        blind=[1, 2],
        players=[
            p.PlayerState(name="my-bot", stack=300, position="sb"),
            p.PlayerState(name="opp", stack=300, position="bb"),
        ],
    )


def _phase_change(room_id: int, phase: str, community: list[str]) -> p.PhaseChange:
    return p.PhaseChange(type="phase_change", room_id=room_id, phase=phase,
                         community_cards=community)


def _action_performed(room_id: int, player: str, action: str, amount: int = 0) -> p.ActionPerformed:
    return p.ActionPerformed(
        type="action_performed", room_id=room_id, player=player,
        action=action, amount=amount, pot=amount * 2,
        players=[
            p.PlayerState(name="my-bot", stack=300, position="sb"),
            p.PlayerState(name="opp", stack=300, position="bb"),
        ],
    )


def test_game_state_isolates_rooms():
    gs = GameState("my-bot")
    gs.handle(_hand_start(room_id=1, hand_no=1, cards=["Ah", "Kh"]))
    gs.handle(_hand_start(room_id=2, hand_no=1, cards=["2c", "7d"]))

    room1 = gs.get(1)
    room2 = gs.get(2)
    assert room1 is not None and room2 is not None
    assert room1.my_cards == ["Ah", "Kh"]
    assert room2.my_cards == ["2c", "7d"]
    # 서로 영향 없음
    assert room1.room_id == 1
    assert room2.room_id == 2


def test_phase_change_only_affects_target_room():
    gs = GameState("my-bot")
    gs.handle(_hand_start(1, 1, ["Ah", "Kh"]))
    gs.handle(_hand_start(2, 1, ["2c", "7d"]))
    gs.handle(_phase_change(1, "flop", ["Qs", "Jh", "5c"]))
    assert gs.get(1).phase == "flop"
    assert gs.get(1).community_cards == ["Qs", "Jh", "5c"]
    # room 2 는 여전히 preflop.
    assert gs.get(2).phase == "preflop"
    assert gs.get(2).community_cards == []


def test_action_performed_isolated_per_room():
    gs = GameState("my-bot")
    gs.handle(_hand_start(1, 1, ["Ah", "Kh"]))
    gs.handle(_hand_start(2, 1, ["2c", "7d"]))
    gs.handle(_action_performed(1, "opp", "call", 2))
    gs.handle(_action_performed(2, "opp", "raise", 10))

    room1_history = gs.get(1).action_history
    room2_history = gs.get(2).action_history
    assert len(room1_history) == 1
    assert len(room2_history) == 1
    assert room1_history[0].action == "call"
    assert room2_history[0].action == "raise"


def test_hand_result_pops_only_one_room():
    gs = GameState("my-bot")
    gs.handle(_hand_start(1, 1, ["Ah", "Kh"]))
    gs.handle(_hand_start(2, 1, ["2c", "7d"]))

    # game_end 는 해당 room 만 삭제, hand_result 는 state 유지.
    gs.handle(p.GameEnd(type="game_end", room_id=1, winner="my-bot"))
    assert gs.get(1) is None
    assert gs.get(2) is not None


def test_budget_tracker_per_room_independent():
    tracker = BudgetTracker(limits=BudgetLimits(per_hand=2, per_game=5, per_day=100))
    # Room 1 핸드 1: 2회 호출.
    assert tracker.allow_call(room_id=1, hand_number=1)[0]
    tracker.record_call(room_id=1, hand_number=1)
    tracker.record_call(room_id=1, hand_number=1)
    # 3번째는 per_hand 한도 초과.
    allowed, reason = tracker.allow_call(room_id=1, hand_number=1)
    assert not allowed

    # Room 2 핸드 1 은 별개 카운터 — 여전히 허용.
    allowed2, _ = tracker.allow_call(room_id=2, hand_number=1)
    assert allowed2


def test_budget_per_game_resets_on_game_end():
    tracker = BudgetTracker(limits=BudgetLimits(per_hand=10, per_game=3, per_day=100))
    for _ in range(3):
        tracker.record_call(room_id=1, hand_number=1)
    # per_game 한도 도달.
    assert not tracker.allow_call(room_id=1, hand_number=2)[0]
    # 동일 방 game_end → per_game counter 리셋.
    tracker.on_game_end(room_id=1)
    assert tracker.allow_call(room_id=1, hand_number=2)[0]


def test_profile_store_shared_across_rooms():
    """같은 상대 이름은 방과 무관하게 동일 profile — plan P4 전역 키."""
    from holdem.transport.protocol import HandResult, Winner
    gs = GameState("my-bot")
    store = ProfileStore()

    # 같은 opp 이름으로 두 방에서 핸드 진행.
    for room in (1, 2):
        gs.handle(_hand_start(room, 1, ["Ah", "Kh"]))
        gs.handle(_action_performed(room, "opp", "raise", 6))
        result = HandResult(
            type="hand_result", room_id=room, hand_number=1,
            winners=[Winner(name="opp", amount=10, hand_type=None)],
            showdown=[], community_cards=[], pot=10, eliminated=[],
        )
        store.on_hand_result(result, gs)

    # 같은 이름 → 단일 profile (두 방의 관측이 하나의 프로필로 누적).
    profiles = store.names()
    assert "opp" in profiles
    opp = store.get("opp")
    # hands_seen 은 두 번 증분 (두 방의 hand_result 모두).
    assert opp.hands_seen >= 2
    # VPIP 는 두 번의 preflop raise 관측 반영.
    assert opp.get("VPIP").alpha >= 2


def test_action_response_carries_room_id():
    """Action 에는 항상 해당 ActionRequest 의 room_id 가 실림."""
    # Action pydantic 모델이 room_id 필수인지 확인.
    action = p.Action(room_id=42, action="fold")
    assert action.room_id == 42
    dumped = action.model_dump_json()
    assert '"room_id":42' in dumped
