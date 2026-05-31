from __future__ import annotations

import dataclasses
from random import gauss, random as rand_random

from holdem_agent.strategy.genome import StrategyGenome


class GenomeMutator:
    """Mutate strategy genomes via gaussian perturbation."""

    def mutate(
        self,
        genome: StrategyGenome,
        rate: float = 0.1,
        sigma: float = 0.1,
    ) -> StrategyGenome:
        """Mutate genome: each parameter has `rate` probability of perturbation.

        Args:
            genome: Source genome
            rate: Probability of mutating each parameter (0.0-1.0)
            sigma: Standard deviation of gaussian noise

        Returns:
            New mutated genome (original unchanged)
        """
        kwargs: dict = {}
        for field in dataclasses.fields(genome):
            current = getattr(genome, field.name)
            if rand_random() > rate:
                kwargs[field.name] = current
                continue
            if isinstance(current, dict):
                kwargs[field.name] = {
                    k: self._perturb(v, sigma) for k, v in current.items()
                }
            elif isinstance(current, float):
                kwargs[field.name] = self._perturb(current, sigma)
            else:
                kwargs[field.name] = current
        result = StrategyGenome(**kwargs)
        return result.clamp()

    def _perturb(self, value: float, sigma: float) -> float:
        """Add gaussian noise to a value."""
        return value + gauss(0, sigma)

    def mutate_population(
        self,
        genome: StrategyGenome,
        n: int = 5,
        rate: float = 0.1,
        sigma: float = 0.1,
    ) -> list[StrategyGenome]:
        """Generate N mutated offspring from a single genome."""
        return [self.mutate(genome, rate, sigma) for _ in range(n)]
