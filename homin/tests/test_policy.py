"""policy.decide — ActionRequest → Action end-to-end."""
from __future__ import annotations

from holdem.decide.policy import decide
from holdem.transport import protocol as p


def _req(
    *,
    my_cards: list[str],
    seat: str,
    my_stack: int,
    sb: int = 1,
    bb: int = 2,
    phase: p.Phase = "preflop",
    to_call: int = 0,
    min_raise: int = 4,
    pot: int = 3,
    n_players: int = 9,
    action_history: list[p.HistoryEntry] | None = None,
) -> p.ActionRequest:
    players = [
        p.PlayerState(name=f"p{i}", stack=100, position=seat if i == 0 else None, bet=0)
        for i in range(n_players)
    ]
    players[0] = p.PlayerState(name="my-bot", stack=my_stack, position=seat, bet=0)
    return p.ActionRequest(
        type="action_request",
        room_id=1,
        hand_number=1,
        your_cards=my_cards,
        community_cards=[] if phase == "preflop" else ["2s", "7d", "Kc"],
        phase=phase,
        pot=pot,
        my_stack=my_stack,
        to_call=to_call,
        min_raise=min_raise,
        blind=[sb, bb],
        seat=seat,
        players=players,
        action_history=action_history or [],
    )


def test_aa_in_push_fold_range_jams():
    # M=5 (stack=10, blinds 1/2 + ... SB=0, BB=0? we use 1/2 here):
    # with stack=10, sb=1, bb=2 → M = 10/3 ≈ 3.3 → push_fold
    action = decide(_req(my_cards=["Ah", "Ad"], seat="btn", my_stack=10), "my-bot")
    assert action.action == "allin"


def test_72o_from_EP_folds_at_short_stack():
    # stack=20, sb=2, bb=4 → M=3.3, push_fold. UTG (EP) 72o → fold
    action = decide(_req(
        my_cards=["7d", "2c"], seat="utg", my_stack=20, sb=2, bb=4,
    ), "my-bot")
    assert action.action == "fold"


def test_any_two_from_btn_at_very_short_m():
    # M < 2 → any two from BTN
    action = decide(_req(
        my_cards=["7d", "2c"], seat="btn", my_stack=5, sb=2, bb=4,
    ), "my-bot")
    assert action.action == "allin"


def test_hybrid_AA_opens_with_min_raise():
    # stack=40, sb=2, bb=4 → M=6.6, push_fold (max=8) — oops still push_fold.
    # Raise blinds to get hybrid: sb=5, bb=10, stack=100 → M=100/15=6.6 (push_fold).
    # Need M > 8 but <= 15: stack=150, sb=5, bb=10 → M=10 → hybrid ✓
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=150, sb=5, bb=10,
        min_raise=20,
    ), "my-bot")
    assert action.action == "raise"
    assert action.amount == 20


def test_hybrid_facing_raise_folds_weak():
    history = [
        p.HistoryEntry(phase="preflop", player="bot-B", action="raise", amount=20),
    ]
    action = decide(_req(
        my_cards=["7d", "2c"], seat="btn", my_stack=150, sb=5, bb=10,
        to_call=20, min_raise=40, action_history=history,
    ), "my-bot")
    assert action.action == "fold"


def test_hybrid_facing_jam_calls_with_premium():
    # M=10 범위의 call_vs_jam = 77+, AQs+, AKo, KQs
    history = [
        p.HistoryEntry(phase="preflop", player="bot-B", action="allin", amount=150),
    ]
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=150, sb=5, bb=10,
        to_call=150, min_raise=300, action_history=history,
    ), "my-bot")
    assert action.action == "call"


def test_mid_AA_BTN_opens_with_rfi_size():
    # stack=200, sb=1, bb=2 → M=100 → deep. BTN RFI chart → AA 포함.
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=200, sb=1, bb=2,
        min_raise=4,
    ), "my-bot")
    assert action.action == "raise"
    # LP RFI = 2.5bb → target = round(2.5 × 2) = 5, 하지만 min_raise=4 보다 큼
    assert action.amount == 5


def test_deep_AA_opens():
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=300, sb=1, bb=2,
        min_raise=4,
    ), "my-bot")
    assert action.action == "raise"


def test_deep_72o_BTN_folds_on_to_call():
    # 72o 는 BTN RFI 에도 없음 → to_call > 0 인 정상 상황에서 fold
    action = decide(_req(
        my_cards=["7d", "2c"], seat="btn", my_stack=300, sb=1, bb=2,
        to_call=2, min_raise=4,
    ), "my-bot")
    assert action.action == "fold"


def test_deep_72o_BB_checks_when_free():
    # to_call=0 이면 포지션 무관 check
    action = decide(_req(
        my_cards=["7d", "2c"], seat="bb", my_stack=300, sb=1, bb=2,
        to_call=0, min_raise=4,
    ), "my-bot")
    assert action.action == "check"


def test_deep_postflop_strong_hand_calls_or_raises():
    # flop: AKs vs K-high → 80%+ equity. P1 EV tree 기본 활성으로 value bet
    # 또는 call 모두 허용 (둘 다 +EV).
    history = [p.HistoryEntry(phase="preflop", player="bot-B", action="raise", amount=6)]
    action = decide(_req(
        my_cards=["As", "Ks"], seat="btn", my_stack=200, sb=1, bb=2,
        phase="flop", pot=20, to_call=10, min_raise=20,
        action_history=history,
    ), "my-bot")
    assert action.action in ("call", "raise", "allin")


def test_deep_postflop_weak_hand_folds_bad_odds():
    # flop: 72o on A-high board, pot-odds nearly 0.4 → equity < 0.3 → fold
    history = [p.HistoryEntry(phase="preflop", player="bot-B", action="raise", amount=6)]
    action = decide(_req(
        my_cards=["7d", "2c"], seat="btn", my_stack=200, sb=1, bb=2,
        phase="flop", pot=20, to_call=14, min_raise=28,
        action_history=history,
    ), "my-bot")
    # community 는 _req 가 기본 2s/7d/Kc 사용 — 이는 72 페어 made, ok equity.
    # 대신 명시적으로 A-high 보드로 덮기
    ar = _req(
        my_cards=["7d", "2c"], seat="btn", my_stack=200, sb=1, bb=2,
        phase="flop", pot=20, to_call=14, min_raise=28,
        action_history=history,
    )
    ar.community_cards = ["As", "Kh", "Qd"]
    action = decide(ar, "my-bot")
    assert action.action == "fold"


def test_deep_postflop_check_on_to_call_zero():
    action = decide(_req(
        my_cards=["7d", "2c"], seat="btn", my_stack=200, sb=1, bb=2,
        phase="flop", pot=10, to_call=0, min_raise=4,
    ), "my-bot")
    assert action.action == "check"


def test_postflop_folds():
    # 9-way 활성 가정에서 AA on 2-7-K vs 8 random ≈ 38% equity.
    # Required pot odds 57% → fold 가 +EV. EV tree 도 동일 결론 (call/raise 가
    # negative chip_ev, fold = 0 이 최적).
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=10, sb=1, bb=2,
        phase="flop", to_call=4,
    ), "my-bot")
    assert action.action == "fold"


def test_invalid_cards_folds_safely():
    action = decide(_req(
        my_cards=["X1"], seat="btn", my_stack=10,
    ), "my-bot")
    assert action.action == "fold"


def test_min_raise_exceeds_stack_folds():
    # hybrid 에서 AA 인데 min_raise > my_stack → fold (자동 올인 방어)
    action = decide(_req(
        my_cards=["Ah", "Ad"], seat="btn", my_stack=150, sb=5, bb=10,
        min_raise=200,   # > my_stack 150
    ), "my-bot")
    assert action.action == "fold"
