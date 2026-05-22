from __future__ import annotations

from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.genome import StrategyGenome, calling_station_genome


class CallingStation(Strategy):
    """Simplest strategy: always call or check. Never folds, never raises."""

    def decide(self, context: DecisionContext) -> Action:
        if context.to_call == 0:
            return Action(action="check", reasoning="Calling station: free check")
        return Action(action="call", reasoning="Calling station: always call")

    @property
    def genome(self) -> StrategyGenome:
        return calling_station_genome()

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "CallingStation":
        # CallingStation ignores genome parameters — it always calls
        return cls()

    @property
    def name(self) -> str:
        return "calling-station"
