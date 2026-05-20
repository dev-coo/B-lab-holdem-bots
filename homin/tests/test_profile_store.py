from __future__ import annotations

from holdem.state.game_state import GameState
from holdem.state.profile_store import ProfileStore
from holdem.transport.protocol import (
    ActionPerformed,
    HandResult,
    HandStart,
    PhaseChange,
    PlayerState,
    Winner,
)


def _playerstate(name: str, stack: int = 100, position: str = "utg"):
    return PlayerState(name=name, stack=stack, position=position, status="active", bet=0)


def _feed_hand(gs: GameState):
    """simplified hand: A raises PF, B calls, A cbets flop, B folds"""
    gs.handle(HandStart(
        type="hand_start",
        room_id=1,
        hand_number=1,
        your_cards=["Ah", "Kh"],
        your_stack=100,
        your_seat="btn",
        blind=[1, 2],
        players=[_playerstate("A", 100, "sb"), _playerstate("B", 100, "bb")],
    ))
    for name, act, amt in [
        ("A", "raise", 6),
        ("B", "call", 6),
    ]:
        gs.handle(ActionPerformed(
            type="action_performed", room_id=1, player=name, action=act,
            amount=amt, pot=0, players=[],
        ))
    gs.handle(PhaseChange(type="phase_change", room_id=1, phase="flop", community_cards=["2h", "7c", "Qd"]))
    for name, act, amt in [
        ("A", "raise", 8),
        ("B", "fold", 0),
    ]:
        gs.handle(ActionPerformed(
            type="action_performed", room_id=1, player=name, action=act,
            amount=amt, pot=0, players=[],
        ))


def test_profile_store_updates_on_hand_result():
    gs = GameState(bot_name="A")
    store = ProfileStore()

    _feed_hand(gs)
    store.on_hand_result(
        HandResult(type="hand_result", room_id=1, hand_number=1, winners=[Winner(name="A", amount=14)]),
        gs,
    )

    assert store.has("A")
    assert store.has("B")
    assert store.get("A").vpip() == 1.0
    assert store.get("A").pfr() == 1.0
    assert store.get("A").get("CBET").rate(default=0) == 1.0
    assert store.get("B").get("FOLD_TO_CBET").rate(default=0) == 1.0


def test_profile_store_accumulates_over_multiple_hands():
    gs = GameState(bot_name="A")
    store = ProfileStore()

    _feed_hand(gs)
    store.on_hand_result(HandResult(type="hand_result", room_id=1, hand_number=1, winners=[]), gs)

    # second hand — same participants, A folds preflop
    gs.handle(HandStart(
        type="hand_start", room_id=1, hand_number=2,
        your_cards=["2h", "7c"], your_stack=94, your_seat="btn",
        blind=[1, 2],
        players=[_playerstate("A", 94, "sb"), _playerstate("B", 106, "bb")],
    ))
    gs.handle(ActionPerformed(type="action_performed", room_id=1, player="A",
                              action="fold", amount=0, pot=0, players=[]))
    store.on_hand_result(HandResult(type="hand_result", room_id=1, hand_number=2, winners=[]), gs)

    assert store.get("A").hands_seen == 2
    assert store.get("A").vpip() == 0.5   # 1/2 VPIP
    assert store.get("A").pfr() == 0.5


def test_profile_store_ignores_missing_room():
    gs = GameState(bot_name="A")
    store = ProfileStore()
    # no hand_start — should not raise
    store.on_hand_result(HandResult(type="hand_result", room_id=99, hand_number=1, winners=[]), gs)
    assert len(store.names()) == 0


# --- P-Decay: posterior 자동 감쇠 ---

def test_decay_all_shrinks_metric_alphas():
    """decay_all 호출 시 모든 metric 의 alpha/beta 가 factor 만큼 줄어든다."""
    store = ProfileStore()
    prof = store.get("villain")
    cnt = prof.get("VPIP")
    cnt.alpha = 100.0
    cnt.beta = 50.0
    store.decay_all(0.9)
    assert abs(cnt.alpha - 90.0) < 1e-6
    assert abs(cnt.beta - 45.0) < 1e-6
    # rate 는 보존 (100/150 = 0.6667 → 90/135 = 0.6667).
    assert abs(cnt.rate() - 100/150) < 1e-6


def test_decay_all_shrinks_dirichlet_response():
    """decay_all 은 ResponseStore 의 Dirichlet alpha 도 함께 감쇠."""
    from holdem.estimate.bayes import DirichletResponse
    store = ProfileStore()
    store.responses.table[("opp", "flop")] = DirichletResponse(
        alpha_fold=10.0, alpha_call=5.0, alpha_raise=5.0,
    )
    store.decay_all(0.5)
    r = store.responses.table[("opp", "flop")]
    assert abs(r.alpha_fold - 5.0) < 1e-6
    assert abs(r.alpha_call - 2.5) < 1e-6
    assert abs(r.alpha_raise - 2.5) < 1e-6


def test_on_hand_result_triggers_decay_after_interval(monkeypatch):
    """N hands 마다 자동 decay 호출 — hands_since_decay 카운터 검증."""
    import holdem.state.profile_store as ps_module
    monkeypatch.setattr(ps_module, "_DECAY_INTERVAL_HANDS", 3)
    monkeypatch.setattr(ps_module, "_DECAY_FACTOR", 0.5)

    gs = GameState(bot_name="me")
    store = ProfileStore()

    # 첫 2 hand 는 카운터만 증가, decay 미발동.
    for hn in (1, 2):
        gs.handle(HandStart(
            type="hand_start", room_id=1, hand_number=hn,
            your_cards=[], your_stack=0, your_seat="",
            blind=[1, 2],
            players=[
                PlayerState(name="me", position="btn", stack=100, bet=0, status="active"),
            ],
        ))
        store.on_hand_result(
            HandResult(type="hand_result", room_id=1, hand_number=hn, winners=[]), gs,
        )
    assert store._hands_since_decay == 2

    # 3번째에서 reset 되어야 (decay 발동 후 0).
    gs.handle(HandStart(
        type="hand_start", room_id=1, hand_number=3,
        your_cards=[], your_stack=0, your_seat="",
        blind=[1, 2],
        players=[
            PlayerState(name="me", position="btn", stack=100, bet=0, status="active"),
        ],
    ))
    store.on_hand_result(
        HandResult(type="hand_result", room_id=1, hand_number=3, winners=[]), gs,
    )
    assert store._hands_since_decay == 0
