from __future__ import annotations

# pyright: reportMissingImports=false

from holdem_agent.evolution.validator import StrategyValidator
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
        preflop_raise_threshold=_position_dict(0.35),
        preflop_call_threshold=_position_dict(0.60),
        preflop_3bet_threshold=_position_dict(0.08),
        cbet_frequency=0.55,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.2,
        bluff_frequency=0.12,
        semi_bluff_equity_threshold=0.25,
        river_bluff_frequency=0.05,
        fold_to_raise_equity=0.25,
        check_raise_frequency=0.07,
        donk_bet_frequency=0.07,
        m_conservative=15.0,
        m_desperate=5.0,
        exploit_aggression=0.5,
        adapt_speed=0.08,
    )


def test_validate_valid_genome() -> None:
    validator = StrategyValidator()
    genome = _base_genome()

    assert validator.validate(genome) == []


def test_validate_missing_position() -> None:
    validator = StrategyValidator()
    bad_raise = {"btn": 0.35, "sb": 0.35, "bb": 0.35, "co": 0.35}
    genome = StrategyGenome(
        preflop_raise_threshold=bad_raise,
        preflop_call_threshold=_position_dict(0.60),
        preflop_3bet_threshold=_position_dict(0.08),
    )

    issues = validator.validate(genome)

    assert "preflop_raise_threshold missing position utg" in issues


def test_validate_suspicious_thresholds() -> None:
    validator = StrategyValidator()
    suspicious = StrategyGenome(
        preflop_raise_threshold={
            "btn": 0.20,
            "sb": 0.20,
            "bb": 0.20,
            "utg": 0.10,
            "co": 0.20,
        },
        preflop_call_threshold={
            "btn": 0.40,
            "sb": 0.40,
            "bb": 0.40,
            "utg": 0.90,
            "co": 0.40,
        },
        preflop_3bet_threshold=_position_dict(0.08),
    )

    issues = validator.validate(suspicious)

    assert "utg: raise threshold suspiciously low vs call threshold" in issues


def test_validate_m_values_reversed(monkeypatch) -> None:
    validator = StrategyValidator()
    genome = StrategyGenome(m_conservative=6.0, m_desperate=7.0)

    monkeypatch.setattr(
        "holdem_agent.strategy.genome.StrategyGenome.clamp",
        lambda self: self,
    )

    issues = validator.validate(genome)

    assert "m_desperate should be less than m_conservative" in issues


def test_is_valid_default() -> None:
    validator = StrategyValidator()

    assert validator.is_valid(StrategyGenome())


def test_sanitize_returns_clamped() -> None:
    validator = StrategyValidator()
    out_of_range = StrategyGenome(
        bluff_frequency=1.0,
        m_conservative=100.0,
        m_desperate=-1.0,
    )

    sanitized = validator.sanitize(out_of_range)

    assert sanitized.bluff_frequency == 0.30
    assert sanitized.m_conservative == 25.0
    assert sanitized.m_desperate == 3.0
