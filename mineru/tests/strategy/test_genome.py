from __future__ import annotations

from holdem_agent.strategy.genome import StrategyGenome, calling_station_genome


def _position_dict(value: float) -> dict[str, float]:
    return {
        "btn": value,
        "sb": value,
        "bb": value,
        "utg": value,
        "co": value,
    }


def test_genome_creation() -> None:
    genome = StrategyGenome(
        preflop_raise_threshold=_position_dict(0.45),
        preflop_call_threshold=_position_dict(0.55),
        preflop_3bet_threshold=_position_dict(0.12),
        cbet_frequency=0.6,
        cbet_size_pot_fraction=0.9,
        raise_size_pot_fraction=2.0,
        three_bet_size_pot_fraction=1.5,
        bluff_frequency=0.08,
        semi_bluff_equity_threshold=0.22,
        river_bluff_frequency=0.1,
        fold_to_raise_equity=0.3,
        check_raise_frequency=0.1,
        donk_bet_frequency=0.06,
        m_conservative=12.0,
        m_desperate=4.0,
        exploit_aggression=0.4,
        adapt_speed=0.1,
    )

    assert genome.preflop_raise_threshold == _position_dict(0.45)
    assert genome.preflop_call_threshold == _position_dict(0.55)
    assert genome.preflop_3bet_threshold == _position_dict(0.12)
    assert genome.cbet_frequency == 0.6
    assert genome.raise_size_pot_fraction == 2.0
    assert genome.adapt_speed == 0.1


def test_genome_clamp() -> None:
    genome = StrategyGenome(
        preflop_raise_threshold=_position_dict(0.45),
        preflop_call_threshold=_position_dict(0.55),
        preflop_3bet_threshold=_position_dict(0.12),
        cbet_frequency=1.4,
        cbet_size_pot_fraction=0.0,
        raise_size_pot_fraction=0.2,
        three_bet_size_pot_fraction=4.0,
        bluff_frequency=-0.2,
        semi_bluff_equity_threshold=0.1,
        river_bluff_frequency=0.3,
        fold_to_raise_equity=0.7,
        check_raise_frequency=-0.01,
        donk_bet_frequency=0.25,
        m_conservative=2.0,
        m_desperate=20.0,
        exploit_aggression=1.8,
        adapt_speed=0.0,
    )

    clamped = genome.clamp()

    assert clamped.cbet_frequency == 1.0
    assert clamped.cbet_size_pot_fraction == 0.25
    assert clamped.raise_size_pot_fraction == 0.5
    assert clamped.three_bet_size_pot_fraction == 3.0
    assert clamped.bluff_frequency == 0.0
    assert clamped.semi_bluff_equity_threshold == 0.15
    assert clamped.river_bluff_frequency == 0.15
    assert clamped.fold_to_raise_equity == 0.5
    assert clamped.check_raise_frequency == 0.0
    assert clamped.donk_bet_frequency == 0.2
    assert clamped.m_conservative == 10.0
    assert clamped.m_desperate == 8.0
    assert clamped.exploit_aggression == 1.0
    assert clamped.adapt_speed == 0.01


def test_genome_clamp_dict() -> None:
    genome = StrategyGenome(
        preflop_raise_threshold={"btn": -0.2, "sb": 0.3, "bb": 2.0, "utg": 0.5, "co": -1.0},
        preflop_call_threshold={"btn": 2.0, "sb": -0.4, "bb": 0.8, "utg": 0.5, "co": 1.5},
        preflop_3bet_threshold={"btn": -5.0, "sb": 0.4, "bb": 1.0, "utg": 1.2, "co": 0.0},
        cbet_frequency=0.5,
        cbet_size_pot_fraction=0.5,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.0,
        bluff_frequency=0.1,
        semi_bluff_equity_threshold=0.2,
        river_bluff_frequency=0.02,
        fold_to_raise_equity=0.2,
        check_raise_frequency=0.1,
        donk_bet_frequency=0.04,
        m_conservative=14.0,
        m_desperate=4.0,
        exploit_aggression=0.4,
        adapt_speed=0.05,
    )

    clamped = genome.clamp()

    assert clamped.preflop_raise_threshold == {
        "btn": 0.0,
        "sb": 0.3,
        "bb": 1.0,
        "utg": 0.5,
        "co": 0.0,
    }
    assert clamped.preflop_call_threshold == {
        "btn": 1.0,
        "sb": 0.0,
        "bb": 0.8,
        "utg": 0.5,
        "co": 1.0,
    }
    assert clamped.preflop_3bet_threshold == {
        "btn": 0.0,
        "sb": 0.4,
        "bb": 1.0,
        "utg": 1.0,
        "co": 0.0,
    }


def test_genome_roundtrip() -> None:
    payload = {
        "preflop_raise_threshold": _position_dict(0.33),
        "preflop_call_threshold": _position_dict(0.42),
        "preflop_3bet_threshold": _position_dict(0.27),
        "cbet_frequency": 0.44,
        "cbet_size_pot_fraction": 0.88,
        "raise_size_pot_fraction": 2.1,
        "three_bet_size_pot_fraction": 1.7,
        "bluff_frequency": 0.06,
        "semi_bluff_equity_threshold": 0.2,
        "river_bluff_frequency": 0.07,
        "fold_to_raise_equity": 0.31,
        "check_raise_frequency": 0.09,
        "donk_bet_frequency": 0.11,
        "m_conservative": 16.0,
        "m_desperate": 6.0,
        "exploit_aggression": 0.3,
        "adapt_speed": 0.17,
    }

    genome = StrategyGenome.from_dict(payload)
    assert genome.to_dict() == payload
    restored = StrategyGenome.from_dict(genome.to_dict())
    assert restored == genome


def test_calling_station_genome() -> None:
    genome = calling_station_genome()

    assert genome.preflop_raise_threshold == _position_dict(0.95)
    assert genome.preflop_call_threshold == _position_dict(0.50)
    assert genome.cbet_frequency == 0.3
    assert genome.bluff_frequency == 0.05
    assert genome.fold_to_raise_equity == 0.25
    assert genome.m_conservative == 15.0
    assert genome.m_desperate == 5.0
    assert 0 <= genome.cbet_frequency <= 1.0
    assert 0 <= genome.preflop_raise_threshold["btn"] <= 1.0
    assert 0.0 <= genome.bluff_frequency <= 0.30
    assert 10.0 <= genome.m_conservative <= 25.0
    assert 3.0 <= genome.m_desperate <= 8.0
    assert all(value == 0.95 for value in genome.preflop_raise_threshold.values())
    assert all(value == 0.50 for value in genome.preflop_call_threshold.values())
    assert all(value == 0.05 for value in genome.preflop_3bet_threshold.values())


def test_genome_immutability_check() -> None:
    original = StrategyGenome(
        preflop_raise_threshold=_position_dict(-1.0),
        preflop_call_threshold=_position_dict(-1.0),
        preflop_3bet_threshold=_position_dict(2.0),
        cbet_frequency=2.0,
        cbet_size_pot_fraction=2.0,
        raise_size_pot_fraction=2.0,
        three_bet_size_pot_fraction=2.0,
        bluff_frequency=2.0,
        semi_bluff_equity_threshold=2.0,
        river_bluff_frequency=2.0,
        fold_to_raise_equity=2.0,
        check_raise_frequency=2.0,
        donk_bet_frequency=2.0,
        m_conservative=2.0,
        m_desperate=2.0,
        exploit_aggression=2.0,
        adapt_speed=2.0,
    )

    clamped = original.clamp()

    assert clamped is not original
    assert original.cbet_frequency == 2.0
    assert original.preflop_raise_threshold == _position_dict(-1.0)
    assert clamped.cbet_frequency == 1.0
    assert clamped.preflop_raise_threshold == _position_dict(0.0)
