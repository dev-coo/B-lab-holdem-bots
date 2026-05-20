from __future__ import annotations

from holdem.decide.policy import build_default_deps, decide
from holdem.transport.protocol import ActionRequest, PlayerState


def _req(*, phase="flop", my_cards, community, my_stack, sb, bb, to_call, min_raise,
         pot, seat="btn"):
    return ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=my_cards,
        community_cards=community,
        phase=phase,
        pot=pot,
        my_stack=my_stack,
        to_call=to_call,
        min_raise=min_raise,
        blind=[sb, bb],
        seat=seat,
        players=[
            PlayerState(name="my-bot", stack=my_stack, position=seat, status="active"),
            PlayerState(name="opp", stack=my_stack, position="bb", status="active"),
        ],
        action_history=[],
    )


def test_ev_tree_calls_with_strong_equity():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 42
    # AA 플레이어, 보드 2h 7c 2d (페어), to_call=4, pot=10 → eq 압도
    action = decide(_req(
        my_cards=["As", "Ac"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=4, min_raise=8, pot=10,
    ), "my-bot", deps)
    # 최소한 fold 는 아님 — equity 거의 100%
    assert action.action in ("call", "raise", "allin")


def test_ev_tree_avoids_call_with_weak_equity_vs_huge_bet():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 42
    # 72o 온 Jh Qh Kh 보드 — equity 거의 0, to_call 은 팟의 10배.
    # Call 은 명백히 -EV (pot_odds ≈ 91% 필요). fold 또는 bluff-raise.
    action = decide(_req(
        my_cards=["7d", "2c"], community=["Jh", "Qh", "Kh"],
        my_stack=100, sb=1, bb=2, to_call=100, min_raise=200, pot=10,
    ), "my-bot", deps)
    assert action.action != "call"


def test_ev_tree_checks_when_no_to_call():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 1
    action = decide(_req(
        my_cards=["As", "Kd"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=0, min_raise=2, pot=4,
    ), "my-bot", deps)
    assert action.action in ("check", "raise")


def test_ev_tree_does_not_break_preflop():
    # opt-in flag 는 postflop 만 영향. preflop AA BTN 은 여전히 raise.
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    action = decide(_req(
        phase="preflop",
        my_cards=["As", "Ac"], community=[],
        my_stack=200, sb=1, bb=2, to_call=0, min_raise=4, pot=3,
    ), "my-bot", deps)
    assert action.action == "raise"
