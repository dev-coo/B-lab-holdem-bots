from __future__ import annotations

import dataclasses
from random import random
from typing import Any

from holdem_agent.strategy.genome import StrategyGenome


class GenomeBreeder:
    """Breed two strategy genomes via uniform crossover."""

    def breed(self, parent_a: StrategyGenome, parent_b: StrategyGenome) -> StrategyGenome:
        """Create child genome from two parents via uniform crossover.

        Each parameter is selected from either parent with 50% probability.
        For dict parameters, each key is selected independently.
        """
        kwargs: dict[str, Any] = {}
        for field in dataclasses.fields(parent_a):
            val_a = getattr(parent_a, field.name)
            val_b = getattr(parent_b, field.name)
            if isinstance(val_a, dict):
                kwargs[field.name] = {k: val_a[k] if random() < 0.5 else val_b[k] for k in val_a}
            else:
                kwargs[field.name] = val_a if random() < 0.5 else val_b

        result = StrategyGenome(**kwargs)
        return result.clamp()

    def breed_population(self, parents: list[StrategyGenome], n_children: int = 5) -> list[StrategyGenome]:
        """Generate N children from random parent pairs."""
        children: list[StrategyGenome] = []
        for _ in range(n_children):
            a, b = random_pair(parents)
            children.append(self.breed(a, b))
        return children


def random_pair(parents: list[StrategyGenome]) -> tuple[StrategyGenome, StrategyGenome]:
    """Select two random different parents."""
    import random as rng

    if len(parents) < 2:
        return parents[0], parents[0]

    idx = rng.sample(range(len(parents)), 2)
    return parents[idx[0]], parents[idx[1]]
