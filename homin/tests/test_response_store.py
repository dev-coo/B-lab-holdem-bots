from __future__ import annotations

from holdem.state.response_store import ResponseStore
from holdem.transport.protocol import HistoryEntry


def _h(phase, player, action, amount=0):
    return HistoryEntry(phase=phase, player=player, action=action, amount=amount)


def test_lookup_returns_default_if_missing():
    store = ResponseStore()
    r = store.lookup("nobody", "flop")
    assert r.mean()["fold"] == r.mean()["call"] == r.mean()["raise"]


def test_observe_from_hand_updates_per_player_phase():
    store = ResponseStore()
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
        _h("flop", "A", "raise", 10),
        _h("flop", "B", "fold"),
    ]
    store.observe_from_hand(history)

    a_pre = store.lookup("A", "preflop")
    assert a_pre.alpha_raise == 2.0   # 1 baseline + 1 obs
    assert a_pre.alpha_fold == 1.0
    assert a_pre.alpha_call == 1.0

    b_pre = store.lookup("B", "preflop")
    assert b_pre.alpha_call == 2.0

    b_flop = store.lookup("B", "flop")
    assert b_flop.alpha_fold == 2.0


def test_aggregate_sums_alphas():
    store = ResponseStore()
    history = [
        _h("flop", "A", "fold"),
        _h("flop", "A", "fold"),
        _h("flop", "B", "call"),
    ]
    store.observe_from_hand(history)

    agg = store.aggregate(["A", "B"], "flop")
    # A: fold 3, call 1, raise 1. B: fold 1, call 2, raise 1. 합 fold=4, call=3, raise=2.
    assert agg.alpha_fold == 4.0
    assert agg.alpha_call == 3.0
    assert agg.alpha_raise == 2.0


def test_aggregate_unknown_opponents_returns_default():
    store = ResponseStore()
    agg = store.aggregate(["X", "Y"], "turn")
    m = agg.mean()
    # 모두 같은 prior 1/3
    assert abs(m["fold"] - m["call"]) < 1e-9


def test_n_opponents_unique():
    store = ResponseStore()
    store.observe_from_hand([
        _h("preflop", "A", "raise", 4),
        _h("preflop", "B", "call", 4),
        _h("flop", "A", "fold"),
    ])
    assert store.n_opponents() == 2


def test_allin_folded_into_raise():
    store = ResponseStore()
    store.observe_from_hand([_h("flop", "A", "allin", 50)])
    r = store.lookup("A", "flop")
    # allin 은 raise bucket 으로 집계
    assert r.alpha_raise == 2.0
