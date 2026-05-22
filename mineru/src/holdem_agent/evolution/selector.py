from __future__ import annotations

import random

from holdem_agent.strategy.genome import StrategyGenome


class FitnessSelector:
    """Select genomes based on fitness scores."""

    def tournament_select(
        self,
        genomes: list[StrategyGenome],
        fitnesses: list[float],
        tournament_size: int = 3,
    ) -> StrategyGenome:
        """Tournament selection: pick best from random subset.

        Args:
            genomes: List of StrategyGenome instances
            fitnesses: Corresponding fitness scores (higher = better)
            tournament_size: Number of candidates per tournament

        Returns:
            Winner genome
        """
        if not genomes:
            raise ValueError("Empty genome list")

        indices = random.sample(range(len(genomes)), min(tournament_size, len(genomes)))
        best_idx = max(indices, key=lambda i: fitnesses[i])
        return genomes[best_idx]

    def select_top_n(
        self,
        genomes: list[StrategyGenome],
        fitnesses: list[float],
        n: int = 5,
    ) -> list[StrategyGenome]:
        """Select top N genomes by fitness (elitism).

        Args:
            genomes: List of StrategyGenome instances
            fitnesses: Corresponding fitness scores
            n: Number to select

        Returns:
            Top N genomes sorted by fitness descending
        """
        paired = list(zip(fitnesses, genomes))
        paired.sort(key=lambda x: x[0], reverse=True)
        return [genome for _, genome in paired[:n]]

    def roulette_select(
        self,
        genomes: list[StrategyGenome],
        fitnesses: list[float],
    ) -> StrategyGenome:
        """Roulette wheel selection (fitness-proportionate).

        Higher fitness = higher probability of selection.
        """
        if not genomes:
            raise ValueError("Empty genome list")

        min_fit = min(fitnesses)
        shifted = [fitness - min_fit + 0.001 for fitness in fitnesses]
        total = sum(shifted)

        r = random.random() * total
        cumulative = 0.0
        for index, weight in enumerate(shifted):
            cumulative += weight
            if cumulative >= r:
                return genomes[index]

        return genomes[-1]

    def select_diverse(
        self,
        genomes: list[StrategyGenome],
        fitnesses: list[float],
        n: int = 5,
        elite_ratio: float = 0.6,
    ) -> list[StrategyGenome]:
        """Select top genomes with diversity: some elite + some random.

        Args:
            genomes: List of StrategyGenome
            fitnesses: Fitness scores
            n: Total to select
            elite_ratio: Fraction that are pure elite selections
        """
        n_elite = max(1, int(n * elite_ratio))
        n_random = n - n_elite

        elite = self.select_top_n(genomes, fitnesses, n_elite)

        remaining = [genome for genome in genomes if genome not in elite]
        random_picks = random.sample(remaining, min(n_random, len(remaining))) if remaining else []

        return elite + random_picks
