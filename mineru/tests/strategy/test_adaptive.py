from __future__ import annotations

import pytest

from holdem_agent.models.state import ActionRecord
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.adaptive import Adaptive
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


def test_adaptive_name() -> None:
    assert Adaptive().name == "adaptive"


def test_adaptive_genome_default() -> None:
    assert Adaptive().genome == StrategyGenome()


def test_adaptive_from_genome() -> None:
    genome = StrategyGenome(bluff_frequency=0.2, raise_size_pot_fraction=1.5)
    strategy = Adaptive.from_genome(genome)

    assert isinstance(strategy, Adaptive)
    assert strategy.genome == genome


def test_adaptive_fold_weak_utg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.10)
    strategy = Adaptive()
    context = _make_context(
        phase="preflop",
        to_call=20,
        hole_cards=["7d", "2c"],
        my_seat="utg",
        community_cards=[],
    )

    assert strategy.decide(context) == Action(action="fold", reasoning="Adaptive: out of range, weak")


def test_adaptive_raise_strong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.95)
    strategy = Adaptive()
    context = _make_context(
        phase="preflop",
        to_call=0,
        pot=10,
        hole_cards=["As", "Ks"],
        my_seat="btn",
    )

    assert strategy.decide(context) == Action(action="raise", amount=10, reasoning="Adaptive: open equity=0.95")


def test_adaptive_call_good_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.40)
    strategy = Adaptive()
    context = _make_context(
        phase="preflop",
        to_call=20,
        pot=100,
        min_raise=40,
        hole_cards=["As", "Ac"],
        my_seat="btn",
    )

    assert strategy.decide(context) == Action(action="call", reasoning="Adaptive: call equity=0.40")


def test_adaptive_traps_vs_aggressive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.70)
    strategy = Adaptive()
    context = _make_context(
        phase="preflop",
        to_call=12,
        hole_cards=["As", "Ks"],
        action_history=[
            ActionRecord(phase="preflop", player="opp1", action="raise", amount=10),
            ActionRecord(phase="flop", player="opp1", action="bet", amount=12),
        ],
    )

    assert strategy.decide(context) == Action(action="call", reasoning="Adaptive: trap vs aggro")


def test_adaptive_exploits_passive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.20)
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.random.random", lambda: 0.0)
    strategy = Adaptive.from_genome(StrategyGenome(bluff_frequency=0.2, exploit_aggression=1.0))
    context = _make_context(
        phase="flop",
        to_call=0,
        pot=20,
        action_history=[
            ActionRecord(phase="preflop", player="opp1", action="call", amount=2),
            ActionRecord(phase="flop", player="opp1", action="call", amount=4),
        ],
        hole_cards=["7d", "2c"],
        community_cards=["Qh", "Jd", "4s"],
    )

    assert strategy.decide(context) == Action(action="raise", amount=11, reasoning="Adaptive: exploit bluff")


def test_adaptive_opponent_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.adaptive.estimated_equity", lambda *_args, **_kwargs: 0.10)
    strategy = Adaptive()
    context = _make_context(
        phase="preflop",
        to_call=0,
        hole_cards=["7d", "2c"],
        my_seat="utg",
        action_history=[ActionRecord(phase="preflop", player="opp1", action="raise", amount=10)],
    )

    strategy.decide(context)
    profile = strategy.opponent_tracker.get_profile("opp1")

    assert profile is not None
    assert profile.pfr_count == 1
    assert profile.raise_count == 1
    assert profile.vpip_count == 1
    assert profile.aggression_factor == 1.0
