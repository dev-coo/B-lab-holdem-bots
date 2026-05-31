from __future__ import annotations

from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.analysts.equity_calc import should_call
from holdem_agent.strategy.analysts.hand_strength import estimated_equity
from holdem_agent.core.odds import suggested_bet_size


class Aggressive(Strategy):
    """Aggressive strategy: wide range, high bet frequency."""

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or self._default_genome()

    @property
    def name(self) -> str:
        return "aggressive"

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "Aggressive":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        equity = estimated_equity(context.hole_cards, context.community_cards)

        if context.phase == "preflop":
            return self._preflop(context, equity)
        return self._postflop(context, equity)

    def _preflop(self, context: DecisionContext, equity: float) -> Action:
        # Aggressive: raise or re-raise most hands
        if context.to_call == 0:
            raise_amt = suggested_bet_size(context.pot, self._genome.raise_size_pot_fraction)
            if raise_amt < context.min_raise:
                raise_amt = context.min_raise
            return Action(action="raise", amount=raise_amt, reasoning=f"Aggro: open raise equity={equity:.2f}")

        # Facing a bet: still raise with decent equity
        if equity > 0.45:
            raise_amt = suggested_bet_size(context.pot, self._genome.three_bet_size_pot_fraction)
            if raise_amt < context.min_raise:
                raise_amt = context.min_raise
            return Action(action="raise", amount=raise_amt, reasoning=f"Aggro: 3-bet equity={equity:.2f}")

        # Call with any reasonable equity
        if equity > 0.25 or context.to_call <= context.blind[1] * 2:
            return Action(action="call", reasoning=f"Aggro: call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"Aggro: fold equity={equity:.2f}")

    def _postflop(self, context: DecisionContext, equity: float) -> Action:
        # Bet aggressively with any equity > 0.3
        if equity > 0.3:
            if context.to_call == 0:
                raise_amt = suggested_bet_size(context.pot, self._genome.cbet_size_pot_fraction)
                if raise_amt < context.min_raise:
                    raise_amt = context.min_raise
                return Action(action="raise", amount=raise_amt, reasoning=f"Aggro: bet equity={equity:.2f}")
            # Facing bet
            if equity > 0.5:
                raise_amt = suggested_bet_size(context.pot, self._genome.raise_size_pot_fraction)
                if raise_amt < context.min_raise:
                    raise_amt = context.min_raise
                return Action(action="raise", amount=raise_amt, reasoning=f"Aggro: raise equity={equity:.2f}")
            return Action(action="call", reasoning=f"Aggro: call equity={equity:.2f}")

        # Bluff frequently
        import random

        if context.to_call == 0 and random.random() < self._genome.bluff_frequency:
            raise_amt = suggested_bet_size(context.pot, self._genome.cbet_size_pot_fraction)
            if raise_amt < context.min_raise:
                raise_amt = context.min_raise
            return Action(action="raise", amount=raise_amt, reasoning="Aggro: bluff")

        if should_call(equity, context.pot, context.to_call, margin=-0.05):
            return Action(action="call", reasoning=f"Aggro: loose call equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning="Aggro: check")

        return Action(action="fold", reasoning=f"Aggro: fold equity={equity:.2f}")

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            preflop_raise_threshold={"btn": 0.60, "co": 0.55, "hj": 0.50,
                                     "mp": 0.45, "utg": 0.40, "sb": 0.55, "bb": 0.50},
            preflop_call_threshold={"btn": 0.80, "co": 0.75, "hj": 0.70,
                                    "mp": 0.65, "utg": 0.60, "sb": 0.75, "bb": 0.70},
            cbet_frequency=0.75,
            cbet_size_pot_fraction=0.65,
            raise_size_pot_fraction=0.80,
            three_bet_size_pot_fraction=1.0,
            bluff_frequency=0.20,
            exploit_aggression=0.8,
        )
