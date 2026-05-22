from __future__ import annotations

# pyright: reportMissingImports=false
import pytest

from holdem_agent.evolution.mutator import GenomeMutator
from holdem_agent.strategy.genome import StrategyGenome


def _position_dict(value: float) -> dict[str, float]:
    return {
        "btn": value,
        "sb": value,
        "bb": value,
        "utg": value,
        "co": value,
    }


def _base_genome() -> StrategyGenome:
    return StrategyGenome(
        preflop_raise_threshold=_position_dict(0.30),
        preflop_call_threshold=_position_dict(0.60),
        preflop_3bet_threshold=_position_dict(0.10),
        cbet_frequency=0.40,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.10,
        three_bet_size_pot_fraction=1.20,
        bluff_frequency=0.08,
        semi_bluff_equity_threshold=0.20,
        river_bluff_frequency=0.05,
        fold_to_raise_equity=0.20,
        check_raise_frequency=0.05,
        donk_bet_frequency=0.05,
        m_conservative=15.0,
        m_desperate=5.0,
        exploit_aggression=0.30,
        adapt_speed=0.08,
    )


def test_mutate_basic(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 0.1)

    original = _base_genome()
    mutated = mutator.mutate(original, rate=1.0)

    assert mutated != original
    assert mutated != original.to_dict()


def test_mutate_preserves_structure(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.9)
    original = _base_genome()

    mutated = mutator.mutate(original, rate=0.0)

    assert set(mutated.to_dict().keys()) == set(original.to_dict().keys())
    assert mutated == original


def test_mutate_clamps_values(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 10.0)

    original = _base_genome()
    mutated = mutator.mutate(original, rate=1.0, sigma=10.0)

    assert mutated.preflop_raise_threshold == _position_dict(1.0)
    assert mutated.preflop_call_threshold == _position_dict(1.0)
    assert mutated.preflop_3bet_threshold == _position_dict(1.0)
    assert mutated.cbet_frequency == 1.0
    assert mutated.cbet_size_pot_fraction == 1.0
    assert mutated.raise_size_pot_fraction == 3.0
    assert mutated.three_bet_size_pot_fraction == 3.0
    assert mutated.bluff_frequency == 0.30
    assert mutated.semi_bluff_equity_threshold == 0.40
    assert mutated.river_bluff_frequency == 0.15
    assert mutated.fold_to_raise_equity == 0.50
    assert mutated.check_raise_frequency == 0.20
    assert mutated.donk_bet_frequency == 0.20
    assert mutated.m_conservative == 25.0
    assert mutated.m_desperate == 8.0
    assert mutated.exploit_aggression == 1.0
    assert mutated.adapt_speed == 0.50


def test_mutate_zero_rate(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.9)

    original = _base_genome()
    original_snapshot = original.to_dict()
    mutated = mutator.mutate(original, rate=0.0)

    assert mutated == original
    assert original.to_dict() == original_snapshot


def test_mutate_high_rate(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 0.1)

    original = _base_genome()
    mutated = mutator.mutate(original, rate=1.0)

    diff_count = 0
    for field_name, value in original.to_dict().items():
        if field_name in {"preflop_raise_threshold", "preflop_call_threshold", "preflop_3bet_threshold"}:
            if value != getattr(mutated, field_name):
                diff_count += 1
        else:
            if value != getattr(mutated, field_name):
                diff_count += 1

    assert mutated != original
    assert diff_count >= 10


def test_mutate_population(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 0.1)

    original = _base_genome()
    population = mutator.mutate_population(original, n=4)

    assert len(population) == 4
    assert all(genome != original for genome in population)


def test_mutate_dict_parameters(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 0.05)

    original = _base_genome()
    mutated = mutator.mutate(original, rate=1.0)

    assert mutated.preflop_raise_threshold == {
        k: pytest.approx(v + 0.05) for k, v in original.preflop_raise_threshold.items()
    }
    assert mutated.preflop_call_threshold == {
        k: pytest.approx(v + 0.05) for k, v in original.preflop_call_threshold.items()
    }
    assert mutated.preflop_3bet_threshold == {
        k: pytest.approx(v + 0.05) for k, v in original.preflop_3bet_threshold.items()
    }


def test_mutate_original_unchanged(monkeypatch) -> None:
    mutator = GenomeMutator()
    monkeypatch.setattr("holdem_agent.evolution.mutator.rand_random", lambda: 0.0)
    monkeypatch.setattr("holdem_agent.evolution.mutator.gauss", lambda _mean, _sigma: 0.1)

    original = _base_genome()
    before = original.to_dict()
    _ = mutator.mutate(original, rate=1.0)

    assert original.to_dict() == before
