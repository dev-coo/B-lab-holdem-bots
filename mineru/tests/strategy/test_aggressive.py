from __future__ import annotations

from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.aggressive import Aggressive
from holdem_agent.strategy.genome import StrategyGenome


def _ctx(**kw):
    defaults = dict(
        hand_number=1,
        hole_cards=["Ah", "Kh"],
        community_cards=[],
        phase="preflop",
        pot=10,
        my_stack=300,
        my_seat="btn",
        to_call=0,
        min_raise=4,
        blind=(1, 2),
        players=[],
        action_history=[],
        blind_structure=[],
        starting_stack=300,
        room_id=1,
    )
    defaults.update(kw)
    return DecisionContext(**defaults)


def test_aggressive_name() -> None:
    assert Aggressive().name == "aggressive"


def test_aggressive_from_genome() -> None:
    genome = StrategyGenome(
        cbet_size_pot_fraction=0.7,
        raise_size_pot_fraction=0.9,
        bluff_frequency=0.12,
    )
    strategy = Aggressive.from_genome(genome)

    assert isinstance(strategy, Aggressive)
    assert strategy.genome == genome


def test_aggressive_raises_preflop_first_in(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.10,
    )
    strategy = Aggressive()

    action = strategy.decide(_ctx(to_call=0, pot=10, min_raise=4))

    assert action == Action(action="raise", amount=8, reasoning="Aggro: open raise equity=0.10")


def test_aggressive_3bets_with_decent_equity(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.50,
    )
    strategy = Aggressive()

    action = strategy.decide(_ctx(to_call=4, pot=20, min_raise=4))

    assert action == Action(action="raise", amount=20, reasoning="Aggro: 3-bet equity=0.50")


def test_aggressive_calls_with_weak_equity(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.15,
    )
    strategy = Aggressive()

    action = strategy.decide(_ctx(to_call=4))

    assert action == Action(action="call", reasoning="Aggro: call equity=0.15")


def test_aggressive_bets_postflop(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.40,
    )
    strategy = Aggressive()

    action = strategy.decide(_ctx(phase="flop", to_call=0, pot=20))

    assert action == Action(action="raise", amount=13, reasoning="Aggro: bet equity=0.40")


def test_aggressive_bluffs(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.05,
    )
    # Force the random-based bluff branch.
    monkeypatch.setattr("random.random", lambda: 0.01)
    strategy = Aggressive()

    action = strategy.decide(_ctx(phase="flop", to_call=0, pot=20))

    assert action == Action(action="raise", amount=13, reasoning="Aggro: bluff")


def test_aggressive_folds_very_weak(monkeypatch) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.aggressive.estimated_equity",
        lambda *_args, **_kwargs: 0.01,
    )
    strategy = Aggressive()

    action = strategy.decide(_ctx(to_call=10, pot=20))

    assert action == Action(action="fold", reasoning="Aggro: fold equity=0.01")
