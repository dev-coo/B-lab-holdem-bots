from __future__ import annotations

import dataclasses

from holdem_agent.analytics.weakspot import Weakspot
from holdem_agent.evolution.mutator import GenomeMutator
from holdem_agent.strategy.genome import StrategyGenome


class StrategyGenerator:
    """Generate new strategy candidates from analysis."""

    def __init__(self) -> None:
        self._mutator = GenomeMutator()

    def generate_candidates(
        self,
        base_genome: StrategyGenome,
        weakspots: list[Weakspot],
        n_candidates: int = 5,
    ) -> list[StrategyGenome]:
        """Generate candidate genomes from base + weakspots.

        Mix of targeted mutations (addressing specific weakspots)
        and random exploration mutations.
        """
        candidates: list[StrategyGenome] = []

        for ws in weakspots[:n_candidates]:
            targeted = self._targeted_mutation(base_genome, ws)
            candidates.append(targeted)

        while len(candidates) < n_candidates:
            mutated = self._mutator.mutate(base_genome, rate=0.15)
            candidates.append(mutated)

        return candidates[:n_candidates]

    def _targeted_mutation(self, genome: StrategyGenome, ws: Weakspot) -> StrategyGenome:
        """Apply targeted mutation addressing a specific weakspot."""
        kwargs: dict = {}
        for field in dataclasses.fields(genome):
            val = getattr(genome, field.name)
            if field.name == ws.param_to_adjust:
                if isinstance(val, dict):
                    kwargs[field.name] = {
                        k: self._adjust(v, ws.direction, 0.1) for k, v in val.items()
                    }
                elif isinstance(val, float):
                    kwargs[field.name] = self._adjust(val, ws.direction, 0.1)
                else:
                    kwargs[field.name] = val
            else:
                kwargs[field.name] = val

        result = StrategyGenome(**kwargs)
        return result.clamp()

    def _adjust(self, value: float, direction: str, amount: float) -> float:
        if direction == "increase":
            return value + amount
        return value - amount

    def generate_random(self, n: int = 5) -> list[StrategyGenome]:
        """Generate N fully random genomes for exploration."""
        candidates = []
        for _ in range(n):
            base = StrategyGenome()
            candidates.append(self._mutator.mutate(base, rate=1.0, sigma=0.3))
        return candidates
