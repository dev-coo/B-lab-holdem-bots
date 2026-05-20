from __future__ import annotations

from holdem.decide.policy import build_default_deps, decide
from holdem.state.profile_store import ProfileStore
from holdem.transport.protocol import ActionRequest, PlayerState


def _req(*, my_cards, seat, my_stack, sb, bb, to_call=0, min_raise=0,
         pot=0, phase="preflop", action_history=None, players=None):
    return ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=my_cards,
        community_cards=[],
        phase=phase,
        pot=pot if pot else sb + bb,
        my_stack=my_stack,
        to_call=to_call,
        min_raise=min_raise,
        blind=[sb, bb],
        seat=seat,
        players=players or [
            PlayerState(name="my-bot", stack=my_stack, position=seat, status="active"),
            PlayerState(name="opp-A", stack=my_stack, position="bb", status="active"),
            PlayerState(name="opp-B", stack=my_stack, position="sb", status="active"),
        ],
        action_history=list(action_history or []),
    )


def test_rfi_size_cold_start_uses_cold_profile():
    # Store 없음 → hard_conservative. BTN 에서 AA 오픈.
    # conservative_grid raise_open_bb = [2.2, 2.5]. BTN(LP)→ sizes[1]=2.5 → round(2.5·2)=5.
    action = decide(_req(
        my_cards=["As", "Ac"], seat="btn", my_stack=200, sb=1, bb=2,
        min_raise=4,
    ), "my-bot")
    assert action.action == "raise"
    assert action.amount == 5


def test_rfi_size_with_profile_store_respects_grid_levels():
    # profile_store 있고, 상대가 충분한 데이터 → balanced grid.
    deps = build_default_deps()
    store = ProfileStore()
    for name in ("opp-A", "opp-B"):
        p = store.get(name)
        p.hands_seen = 200
        p.get("VPIP").alpha = 50
        p.get("VPIP").beta = 150
        p.aggression.aggressive = 25
        p.aggression.passive = 25
    deps.profile_store = store

    action = decide(_req(
        my_cards=["As", "Ac"], seat="btn", my_stack=200, sb=1, bb=2,
        min_raise=4,
    ), "my-bot", deps)
    assert action.action == "raise"
    # balanced grid raise_open_bb = [2.2, 2.5, 3.0]. BTN(LP) → sizes[1]=2.5 → target 5.
    # exploit_grid = [2.2, 2.5, 3.0, 3.5] → sizes[2]=3.0 → target 6. hands_seen=200 은 balanced 구간.
    assert action.amount in (5, 6)


def test_rfi_size_with_mixed_opponents_uses_min_n_effective():
    # 하나는 heavy (balanced), 하나는 unknown (hard_conservative).
    # 최종 profile = hard_conservative.
    deps = build_default_deps()
    store = ProfileStore()
    heavy = store.get("opp-A")
    heavy.hands_seen = 500
    heavy.get("VPIP").alpha = 125
    heavy.get("VPIP").beta = 375
    heavy.aggression.aggressive = 60
    heavy.aggression.passive = 40
    # opp-B 는 store 에 없음
    deps.profile_store = store

    action = decide(_req(
        my_cards=["As", "Ac"], seat="btn", my_stack=200, sb=1, bb=2,
        min_raise=4,
    ), "my-bot", deps)
    assert action.action == "raise"
    # hard_conservative → conservative_grid sizes[1]=2.5 → target 5.
    assert action.amount == 5
