from __future__ import annotations

import pytest

from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.tight_aggressive import TightAggressive
from holdem_agent.strategy.genome import StrategyGenome


def _make_context(to_call: int = 0, phase: str = "preflop", **overrides) -> DecisionContext:
    defaults = dict(
        hand_number=1,
        hole_cards=["Ah", "Kh"],
        community_cards=["Ad", "7c", "2h"] if phase != "preflop" else [],
        phase=phase,
        pot=20,
        my_stack=300,
        my_seat="btn",
        to_call=to_call,
        min_raise=4,
        blind=(1, 2),
        players=[],
        action_history=[],
        blind_structure=[],
        starting_stack=300,
        room_id=1,
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


def test_tag_name() -> None:
    strategy = TightAggressive()

    assert strategy.name == "tight-aggressive"


def test_tag_genome_tight_thresholds() -> None:
    strategy = TightAggressive()

    assert strategy.genome.preflop_raise_threshold == {
        "btn": 0.30,
        "co": 0.35,
        "hj": 0.40,
        "mp": 0.45,
        "utg": 0.50,
        "sb": 0.40,
        "bb": 0.45,
    }
    assert strategy.genome.preflop_call_threshold == {
        "btn": 0.55,
        "co": 0.55,
        "hj": 0.50,
        "mp": 0.50,
        "utg": 0.45,
        "sb": 0.50,
        "bb": 0.50,
    }


def test_tag_from_genome() -> None:
    custom = StrategyGenome(
        preflop_raise_threshold={"btn": 0.5, "co": 0.5, "hj": 0.5, "mp": 0.5, "utg": 0.5, "sb": 0.5, "bb": 0.5},
        preflop_call_threshold={"btn": 0.6, "co": 0.6, "hj": 0.6, "mp": 0.6, "utg": 0.6, "sb": 0.6, "bb": 0.6},
        cbet_size_pot_fraction=0.65,
        raise_size_pot_fraction=1.1,
        bluff_frequency=0.2,
    )
    strategy = TightAggressive.from_genome(custom)

    assert isinstance(strategy, TightAggressive)
    assert strategy.genome == custom


def test_tag_fold_weak_hand_utg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.tight_aggressive.estimated_equity", lambda *_args, **_kwargs: 0.10
    )
    strategy = TightAggressive.from_genome(
        StrategyGenome(
            preflop_raise_threshold={
                "btn": 0.0,
                "co": 0.0,
                "hj": 0.0,
                "mp": 0.0,
                "utg": 0.0,
                "sb": 0.0,
                "bb": 0.0,
            }
        )
    )
    context = _make_context(
        phase="preflop",
        to_call=20,
        hole_cards=["7d", "2c"],
        my_seat="utg",
        community_cards=[],
    )

    assert strategy.decide(context) == Action(action="fold", reasoning="TAG: out of range")


def test_tag_raise_strong_hand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.tight_aggressive.estimated_equity", lambda *_args, **_kwargs: 0.95
    )
    strategy = TightAggressive()
    context = _make_context(
        phase="preflop",
        to_call=0,
        pot=10,
        hole_cards=["As", "Ks"],
        my_seat="btn",
    )

    assert strategy.decide(context) == Action(action="raise", amount=7, reasoning="TAG: raise in range equity=0.95")


def test_tag_value_raise_postflop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.tight_aggressive.estimated_equity", lambda *_args, **_kwargs: 0.80
    )
    strategy = TightAggressive()
    context = _make_context(
        phase="flop",
        pot=20,
        to_call=10,
        hole_cards=["As", "Ks"],
        community_cards=["Ad", "7c", "2h"],
        my_seat="btn",
    )

    assert strategy.decide(context) == Action(
        action="raise",
        amount=15,
        reasoning="TAG: value raise equity=0.80",
    )


def test_tag_fold_to_raise_weak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.tight_aggressive.estimated_equity", lambda *_args, **_kwargs: 0.15
    )
    strategy = TightAggressive()
    context = _make_context(
        phase="flop",
        to_call=20,
        hole_cards=["7d", "2c"],
        community_cards=["Qh", "Jd", "4s"],
        my_seat="btn",
    )

    assert strategy.decide(context) == Action(action="fold", reasoning="TAG: fold equity=0.15")


def test_tag_call_decent_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.tight_aggressive.estimated_equity", lambda *_args, **_kwargs: 0.40
    )
    strategy = TightAggressive()
    context = _make_context(
        phase="preflop",
        to_call=20,
        hole_cards=["As", "As"],
        my_seat="btn",
        pot=100,
        min_raise=40,
    )

    assert strategy.decide(context) == Action(action="call", reasoning="TAG: call equity=0.40")
