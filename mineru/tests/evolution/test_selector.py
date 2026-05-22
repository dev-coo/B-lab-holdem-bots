import random

import pytest

from holdem_agent.evolution.selector import FitnessSelector
from holdem_agent.strategy.genome import StrategyGenome


def _make_genomes(n: int) -> list[StrategyGenome]:
    return [StrategyGenome(bluff_frequency=0.1 * i) for i in range(n)]


def test_tournament_select_basic() -> None:
    genomes = _make_genomes(5)
    fitnesses = [0.1, 0.5, 0.9, 1.4, 1.1]

    selector = FitnessSelector()
    winner = selector.tournament_select(genomes, fitnesses, tournament_size=5)

    assert winner is genomes[3]


def test_tournament_select_best_wins() -> None:
    genomes = _make_genomes(4)
    fitnesses = [1.0, 10.0, 2.0, 3.0]

    random.seed(0)
    selector = FitnessSelector()

    wins = 0
    for _ in range(200):
        if selector.tournament_select(genomes, fitnesses) is genomes[1]:
            wins += 1

    assert wins > 120


def test_tournament_select_empty_raises() -> None:
    selector = FitnessSelector()

    with pytest.raises(ValueError, match="Empty genome list"):
        selector.tournament_select([], [])


def test_select_top_n() -> None:
    genomes = _make_genomes(6)
    fitnesses = [1.0, 5.0, 2.0, 0.5, 4.0, 3.0]

    selected = FitnessSelector().select_top_n(genomes, fitnesses, n=3)

    assert selected == [genomes[1], genomes[4], genomes[5]]


def test_select_top_n_fewer_than_n() -> None:
    genomes = _make_genomes(3)
    fitnesses = [0.2, 0.9, 0.5]

    selected = FitnessSelector().select_top_n(genomes, fitnesses, n=10)

    assert selected == [genomes[1], genomes[2], genomes[0]]


def test_roulette_select_basic() -> None:
    genomes = _make_genomes(3)
    fitnesses = [0.2, 0.7, 1.2]

    random.seed(0)
    selected = FitnessSelector().roulette_select(genomes, fitnesses)

    assert selected in genomes


def test_roulette_select_empty_raises() -> None:
    selector = FitnessSelector()

    with pytest.raises(ValueError, match="Empty genome list"):
        selector.roulette_select([], [])


def test_select_diverse() -> None:
    genomes = _make_genomes(6)
    fitnesses = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    random.seed(0)
    selected = FitnessSelector().select_diverse(genomes, fitnesses, n=5, elite_ratio=0.6)

    assert len(selected) == 5
    assert selected[:3] == [genomes[5], genomes[4], genomes[3]]

    remaining_ids = {id(genomes[i]) for i in range(3)}
    selected_ids = [id(g) for g in selected]

    assert len(selected_ids) == len(set(selected_ids))
    assert set(selected_ids[3:]).issubset(remaining_ids)


def test_select_diverse_elite_first() -> None:
    genomes = _make_genomes(6)
    fitnesses = [1.0, 2.0, 5.0, 6.0, 4.0, 3.0]

    random.seed(1)
    selected = FitnessSelector().select_diverse(genomes, fitnesses, n=4, elite_ratio=0.75)

    assert selected[:3] == [genomes[3], genomes[2], genomes[4]]
