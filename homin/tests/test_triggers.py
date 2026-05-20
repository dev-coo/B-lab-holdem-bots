from __future__ import annotations

from holdem.meta.triggers import (
    TriggerConfig,
    build_triggers,
    count_active_opponents,
    count_remaining,
)
from holdem.state.player_profile import PlayerProfile
from holdem.state.profile_store import ProfileStore
from holdem.transport.protocol import ActionRequest, PlayerState


def _req(*, my_stack=100, sb=1, bb=2, pot=10, n_active=2, n_eliminated=0):
    players = [
        PlayerState(name="my-bot", stack=my_stack, position="btn", status="active"),
    ]
    for i in range(n_active):
        players.append(PlayerState(name=f"opp{i}", stack=100, position="bb", status="active"))
    for i in range(n_eliminated):
        players.append(PlayerState(name=f"dead{i}", stack=0, position="sb", status="eliminated"))
    return ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=["As", "Kd"],
        community_cards=[],
        phase="preflop",
        pot=pot,
        my_stack=my_stack,
        to_call=0,
        min_raise=4,
        blind=[sb, bb],
        seat="btn",
        players=players,
        action_history=[],
    )


def test_m_lt_6_flag():
    # stack=10, sb+bb=3 → M=3.33 < 6
    t = build_triggers(_req(my_stack=10, sb=1, bb=2), "my-bot")
    assert t.M_lt_6


def test_m_not_lt_6_with_deep_stack():
    t = build_triggers(_req(my_stack=200, sb=1, bb=2), "my-bot")
    assert not t.M_lt_6


def test_near_bubble_three_remaining():
    t = build_triggers(_req(n_active=2, n_eliminated=5), "my-bot")
    assert t.near_bubble


def test_not_bubble_when_headsup():
    t = build_triggers(_req(n_active=1, n_eliminated=5), "my-bot")
    # 2 remaining = headsup, not bubble
    assert not t.near_bubble


def test_stack_gt_100bb_pot_gt_50bb():
    # my_stack=200, bb=2 → 100BB stack; pot=100 → 50BB.
    t = build_triggers(_req(my_stack=200, sb=1, bb=2, pot=100), "my-bot")
    assert t.stack_gt_100bb_pot_gt_50bb


def test_multiway_3plus():
    t = build_triggers(_req(n_active=3), "my-bot")
    assert t.multiway_3plus_borderline


def test_not_multiway_with_2_opponents():
    t = build_triggers(_req(n_active=2), "my-bot")
    assert not t.multiway_3plus_borderline


def test_fold_equity_uncertain_no_profile_store():
    t = build_triggers(_req(n_active=1), "my-bot", profile_store=None)
    assert t.fold_equity_uncertain


def test_fold_equity_certain_with_rich_profiles():
    store = ProfileStore()
    for i in range(2):
        prof = store.get(f"opp{i}")
        prof.hands_seen = 100
        for key in ("VPIP", "PFR", "CBET"):
            prof.get(key).alpha = 25
            prof.get(key).beta = 75
    t = build_triggers(_req(n_active=2), "my-bot", profile_store=store)
    assert not t.fold_equity_uncertain


def test_fold_equity_uncertain_when_one_opponent_unknown():
    store = ProfileStore()
    # opp0 는 풍부, opp1 은 없음
    rich = store.get("opp0")
    rich.hands_seen = 100
    for key in ("VPIP",):
        rich.get(key).alpha = 25
        rich.get(key).beta = 75
    # opp1 미등록
    t = build_triggers(_req(n_active=2), "my-bot", profile_store=store)
    assert t.fold_equity_uncertain


def test_count_active_and_remaining():
    r = _req(n_active=3, n_eliminated=2)
    assert count_active_opponents(r, "my-bot") == 3
    assert count_remaining(r) == 4  # me + 3 active


def test_custom_config():
    cfg = TriggerConfig(m_short_threshold=10.0)
    # M = 200/3 = 66 > 10 → False, 100/3 = 33.3 → False
    t = build_triggers(_req(my_stack=24, sb=1, bb=2), "my-bot", cfg=cfg)
    # M = 24/3 = 8 < 10 → True
    assert t.M_lt_6
