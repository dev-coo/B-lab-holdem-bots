from __future__ import annotations

from holdem_agent.strategy.base import DecisionContext
from holdem_agent.strategy.builtins.gto_baseline import GTOBaseline
from holdem_agent.strategy.genome import StrategyGenome


def _ctx(**overrides) -> DecisionContext:
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
    defaults.update(overrides)
    return DecisionContext(**defaults)


def test_gto_baseline_name() -> None:
    assert GTOBaseline().name == "gto-baseline"


def test_gto_baseline_genome_default() -> None:
    assert GTOBaseline().genome == StrategyGenome()


def test_gto_baseline_from_genome() -> None:
    genome = StrategyGenome(cbet_frequency=0.9, bluff_frequency=0.01)
    strategy = GTOBaseline.from_genome(genome)

    assert isinstance(strategy, GTOBaseline)
    assert strategy.genome == genome


def test_gto_baseline_fold_weak_preflop(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.08)

    action = GTOBaseline().decide(_ctx(hole_cards=["2h", "7d"], my_seat="utg", to_call=4))

    assert action.action == "fold"


def test_gto_baseline_call_good_equity(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.72)

    action = GTOBaseline().decide(_ctx(to_call=6, action_history=[]))

    assert action.action == "call"


def test_gto_baseline_check_free(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.05)

    action = GTOBaseline().decide(_ctx(hole_cards=["2h", "7d"], my_seat="utg", to_call=0))

    assert action.action == "check"


def test_gto_baseline_raise_strong(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.85)

    action = GTOBaseline().decide(_ctx(hole_cards=["As", "Ad"], my_seat="btn", to_call=0, pot=20, min_raise=6))

    assert action.action == "raise"
    assert action.amount is not None and action.amount >= 6


def test_gto_baseline_postflop_value_bet(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.82)

    action = GTOBaseline().decide(
        _ctx(
            phase="flop",
            community_cards=["Qs", "Jh", "2c"],
            to_call=4,
            pot=30,
            min_raise=10,
        )
    )

    assert action.action in {"raise", "call"}


def test_gto_push_fold_allin(monkeypatch) -> None:
    monkeypatch.setattr("holdem_agent.strategy.builtins.gto_baseline.estimated_equity", lambda *_: 0.72)

    action = GTOBaseline().decide(_ctx(my_stack=20, blind=(1, 2), to_call=0))

    assert action.action == "allin"
