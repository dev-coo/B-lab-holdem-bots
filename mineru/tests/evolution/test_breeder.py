from __future__ import annotations

import dataclasses

import pytest
from holdem_agent.evolution.breeder import GenomeBreeder
from holdem_agent.strategy.genome import StrategyGenome


def _position_dict(value: float) -> dict[str, float]:
    return {
        "btn": value,
        "sb": value + 0.01,
        "bb": value + 0.02,
        "utg": value + 0.03,
        "co": value + 0.04,
    }


def _constant_genome(value: float = 0.5) -> StrategyGenome:
    return StrategyGenome(
        preflop_raise_threshold=_position_dict(value),
        preflop_call_threshold=_position_dict(value + 0.1),
        preflop_3bet_threshold=_position_dict(value + 0.2),
        cbet_frequency=value,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0 + value,
        three_bet_size_pot_fraction=1.0 + value,
        bluff_frequency=value / 10,
        semi_bluff_equity_threshold=0.15 + value / 10,
        river_bluff_frequency=value / 20,
        fold_to_raise_equity=value / 4,
        check_raise_frequency=value / 50,
        donk_bet_frequency=value / 50,
        m_conservative=15 + value,
        m_desperate=5 + value,
        exploit_aggression=0.5,
        adapt_speed=0.1,
    )


def _next_random(values: list[float]):
    iterator = iter(values)
    last = 0.0

    def _random() -> float:
        nonlocal last
        last = next(iterator, last)
        return last

    return _random


def test_breed_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent_a = _constant_genome(0.2)
    parent_b = _constant_genome(0.6)

    monkeypatch.setattr("holdem_agent.evolution.breeder.random", _next_random([0.0] * 100))
    child = breeder.breed(parent_a, parent_b)

    parent_a_clamped = parent_a.clamp()
    for field in dataclasses.fields(parent_a):
        assert hasattr(child, field.name)
        assert getattr(child, field.name) == getattr(parent_a_clamped, field.name)


def test_breed_inherits_from_parents(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent_a = _constant_genome(0.2).clamp()
    parent_b = _constant_genome(0.6).clamp()

    monkeypatch.setattr("holdem_agent.evolution.breeder.random", _next_random([0.4, 0.6] * 100))
    child = breeder.breed(parent_a, parent_b)

    for field in dataclasses.fields(parent_a):
        parent_a_value = getattr(parent_a, field.name)
        parent_b_value = getattr(parent_b, field.name)
        child_value = getattr(child, field.name)

        if isinstance(parent_a_value, dict):
            for key in parent_a_value:
                assert child_value[key] in (parent_a_value[key], parent_b_value[key])
        else:
            assert child_value in (parent_a_value, parent_b_value)


def test_breed_dict_crossover(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent_a = StrategyGenome(
        preflop_raise_threshold={"btn": 0.10, "sb": 0.20, "bb": 0.30, "utg": 0.40, "co": 0.50},
        preflop_call_threshold={"btn": 0.11, "sb": 0.21, "bb": 0.31, "utg": 0.41, "co": 0.51},
        preflop_3bet_threshold={"btn": 0.12, "sb": 0.22, "bb": 0.32, "utg": 0.42, "co": 0.52},
        cbet_frequency=0.55,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.1,
        bluff_frequency=0.05,
        semi_bluff_equity_threshold=0.2,
        river_bluff_frequency=0.04,
        fold_to_raise_equity=0.2,
        check_raise_frequency=0.05,
        donk_bet_frequency=0.05,
        m_conservative=15,
        m_desperate=5,
        exploit_aggression=0.3,
        adapt_speed=0.1,
    )
    parent_b = StrategyGenome(
        preflop_raise_threshold={"btn": 0.90, "sb": 0.80, "bb": 0.70, "utg": 0.60, "co": 0.50},
        preflop_call_threshold={"btn": 0.91, "sb": 0.81, "bb": 0.71, "utg": 0.61, "co": 0.51},
        preflop_3bet_threshold={"btn": 0.92, "sb": 0.82, "bb": 0.72, "utg": 0.62, "co": 0.52},
        cbet_frequency=0.55,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.1,
        bluff_frequency=0.05,
        semi_bluff_equity_threshold=0.2,
        river_bluff_frequency=0.04,
        fold_to_raise_equity=0.2,
        check_raise_frequency=0.05,
        donk_bet_frequency=0.05,
        m_conservative=15,
        m_desperate=5,
        exploit_aggression=0.3,
        adapt_speed=0.1,
    )

    # btn, bb, co from parent_a; sb, utg from parent_b for first dict field
    monkeypatch.setattr(
        "holdem_agent.evolution.breeder.random",
        _next_random([0.4, 0.6, 0.4, 0.6, 0.4] + [0.4] * 200),
    )
    child = breeder.breed(parent_a, parent_b)

    assert child.preflop_raise_threshold == {
        "btn": 0.10,
        "sb": 0.80,
        "bb": 0.30,
        "utg": 0.60,
        "co": 0.50,
    }


def test_breed_clamps_result(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent_a = _constant_genome(0.2)
    parent_b = StrategyGenome(
        preflop_raise_threshold={"btn": -1.0, "sb": 2.0, "bb": 2.0, "utg": 2.0, "co": -1.0},
        preflop_call_threshold={"btn": -1.0, "sb": 2.0, "bb": 2.0, "utg": 2.0, "co": -1.0},
        preflop_3bet_threshold={"btn": -1.0, "sb": 2.0, "bb": 2.0, "utg": 2.0, "co": -1.0},
        cbet_frequency=2.0,
        cbet_size_pot_fraction=-0.5,
        raise_size_pot_fraction=0.1,
        three_bet_size_pot_fraction=4.0,
        bluff_frequency=2.0,
        semi_bluff_equity_threshold=0.0,
        river_bluff_frequency=0.2,
        fold_to_raise_equity=0.8,
        check_raise_frequency=0.5,
        donk_bet_frequency=0.5,
        m_conservative=-1.0,
        m_desperate=20.0,
        exploit_aggression=2.0,
        adapt_speed=0.0,
    )

    monkeypatch.setattr("holdem_agent.evolution.breeder.random", lambda: 0.6)
    child = breeder.breed(parent_a, parent_b)

    assert child == parent_b.clamp()


def test_breed_population(monkeypatch: pytest.MonkeyPatch) -> None:
    from holdem_agent.evolution import breeder as breeder_module

    breeder = GenomeBreeder()
    parents = [_constant_genome(0.2), _constant_genome(0.4), _constant_genome(0.6)]

    def fake_pair(_: list[StrategyGenome]) -> tuple[StrategyGenome, StrategyGenome]:
        return parents[0], parents[1]

    monkeypatch.setattr("holdem_agent.evolution.breeder.random", lambda: 0.0)
    monkeypatch.setattr(breeder_module, "random_pair", fake_pair)

    children = breeder.breed_population(parents, n_children=4)

    assert len(children) == 4
    for child in children:
        assert isinstance(child, StrategyGenome)
        assert child == parents[0].clamp()


def test_breed_same_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent = _constant_genome(0.3)

    monkeypatch.setattr("holdem_agent.evolution.breeder.random", lambda: 0.4)
    child = breeder.breed(parent, parent)

    assert child == parent.clamp()


def test_breed_two_different(monkeypatch: pytest.MonkeyPatch) -> None:
    breeder = GenomeBreeder()
    parent_a = _constant_genome(0.2).clamp()
    parent_b = _constant_genome(0.8).clamp()

    # 17 fields total => 29 random draws for full crossover
    monkeypatch.setattr("holdem_agent.evolution.breeder.random", _next_random([0.4, 0.6] * 15))
    child = breeder.breed(parent_a, parent_b)

    has_from_a = False
    has_from_b = False

    for field in dataclasses.fields(parent_a):
        parent_a_value = getattr(parent_a, field.name)
        parent_b_value = getattr(parent_b, field.name)
        child_value = getattr(child, field.name)

        if isinstance(parent_a_value, dict):
            for key in parent_a_value:
                assert child_value[key] in (parent_a_value[key], parent_b_value[key])
                if child_value[key] == parent_a_value[key]:
                    has_from_a = True
                if child_value[key] == parent_b_value[key]:
                    has_from_b = True
        else:
            assert child_value in (parent_a_value, parent_b_value)
            if child_value == parent_a_value:
                has_from_a = True
            if child_value == parent_b_value:
                has_from_b = True

    assert has_from_a and has_from_b
    assert child != parent_a
    assert child != parent_b
