from __future__ import annotations

# pyright: reportMissingImports=false

from holdem_agent.analytics.weakspot import Weakspot
from holdem_agent.evolution.generator import StrategyGenerator
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
        preflop_raise_threshold=_position_dict(0.32),
        preflop_call_threshold=_position_dict(0.62),
        preflop_3bet_threshold=_position_dict(0.09),
        cbet_frequency=0.40,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.2,
        bluff_frequency=0.12,
        semi_bluff_equity_threshold=0.25,
        river_bluff_frequency=0.05,
        fold_to_raise_equity=0.25,
        check_raise_frequency=0.06,
        donk_bet_frequency=0.05,
        m_conservative=15.0,
        m_desperate=5.0,
        exploit_aggression=0.5,
        adapt_speed=0.08,
    )


def test_generate_candidates_basic() -> None:
    generator = StrategyGenerator()
    base = _base_genome()

    candidates = generator.generate_candidates(base, [], n_candidates=3)

    assert len(candidates) == 3
    assert all(isinstance(candidate, StrategyGenome) for candidate in candidates)


def test_generate_candidates_with_weakspots() -> None:
    generator = StrategyGenerator()
    base = _base_genome()
    weakspots = [
        Weakspot(
            area="a",
            description="",
            suggestion="",
            param_to_adjust="preflop_call_threshold",
            direction="decrease",
        ),
        Weakspot(
            area="b",
            description="",
            suggestion="",
            param_to_adjust="bluff_frequency",
            direction="increase",
        ),
    ]

    candidates = generator.generate_candidates(base, weakspots, n_candidates=2)

    assert len(candidates) == 2
    assert candidates[0].preflop_call_threshold["btn"] < base.preflop_call_threshold["btn"]
    assert candidates[1].bluff_frequency > base.bluff_frequency


def test_generate_candidates_respects_count() -> None:
    generator = StrategyGenerator()
    base = _base_genome()
    weakspots = [
        Weakspot(
            area="a",
            description="",
            suggestion="",
            param_to_adjust="bluff_frequency",
            direction="increase",
        ),
    ] * 10

    candidates = generator.generate_candidates(base, weakspots, n_candidates=5)

    assert len(candidates) == 5
    assert all(isinstance(candidate, StrategyGenome) for candidate in candidates)


def test_generate_random() -> None:
    generator = StrategyGenerator()
    random_genomes = generator.generate_random(4)

    assert len(random_genomes) == 4
    assert all(isinstance(candidate, StrategyGenome) for candidate in random_genomes)


def test_targeted_mutation_increases() -> None:
    generator = StrategyGenerator()
    base = _base_genome()
    weakspot = Weakspot(
        area="aggression",
        description="",
        suggestion="",
        param_to_adjust="preflop_raise_threshold",
        direction="increase",
    )

    mutated = generator._targeted_mutation(base, weakspot)

    for pos in base.preflop_raise_threshold:
        assert mutated.preflop_raise_threshold[pos] > base.preflop_raise_threshold[pos]


def test_targeted_mutation_decreases() -> None:
    generator = StrategyGenerator()
    base = _base_genome()
    weakspot = Weakspot(
        area="safety",
        description="",
        suggestion="",
        param_to_adjust="bluff_frequency",
        direction="decrease",
    )

    mutated = generator._targeted_mutation(base, weakspot)

    assert mutated.bluff_frequency < base.bluff_frequency
