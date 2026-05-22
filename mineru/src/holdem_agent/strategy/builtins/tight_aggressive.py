from __future__ import annotations

from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.analysts.equity_calc import (
    should_call,
    should_raise,
    raise_amount,
)
from holdem_agent.strategy.analysts.position import position_range_adjustment
from holdem_agent.strategy.analysts.hand_strength import estimated_equity
from holdem_agent.core.range_ import hand_in_range


class TightAggressive(Strategy):
    """Tight-Aggressive: narrow range, aggressive betting."""

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or self._default_tag_genome()

    @property
    def name(self) -> str:
        return "tight-aggressive"

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "TightAggressive":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        equity = estimated_equity(context.hole_cards, context.community_cards)

        if context.phase == "preflop":
            return self._preflop(context, equity)
        return self._postflop(context, equity)

    def _preflop(self, context: DecisionContext, equity: float) -> Action:
        threshold = self._genome.preflop_raise_threshold.get(context.my_seat, 0.35)
        adjusted = position_range_adjustment(context.my_seat, threshold)
        in_range = hand_in_range(context.hole_cards, adjusted)

        if not in_range:
            if context.to_call == 0:
                return Action(action="check", reasoning="TAG: out of range, free check")
            return Action(action="fold", reasoning="TAG: out of range")

        # In range — play aggressively
        if context.to_call == 0:
            raise_amt = raise_amount(equity, context.pot, context.min_raise,
                                     self._genome.raise_size_pot_fraction)
            return Action(action="raise", amount=raise_amt,
                         reasoning=f"TAG: raise in range equity={equity:.2f}")

        if should_raise(equity, context.pot, context.min_raise,
                        self._genome.exploit_aggression):
            raise_amt = raise_amount(equity, context.pot, context.min_raise,
                                     self._genome.three_bet_size_pot_fraction)
            return Action(action="raise", amount=raise_amt,
                         reasoning=f"TAG: 3-bet equity={equity:.2f}")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"TAG: call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"TAG: fold equity={equity:.2f}")

    def _postflop(self, context: DecisionContext, equity: float) -> Action:
        if equity > 0.6:
            raise_amt = raise_amount(equity, context.pot, context.min_raise,
                                     self._genome.raise_size_pot_fraction)
            return Action(action="raise", amount=raise_amt,
                         reasoning=f"TAG: value raise equity={equity:.2f}")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"TAG: call equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning="TAG: check back")

        return Action(action="fold", reasoning=f"TAG: fold equity={equity:.2f}")

    @staticmethod
    def _default_tag_genome() -> StrategyGenome:
        return StrategyGenome(
            preflop_raise_threshold={"btn": 0.30, "co": 0.35, "hj": 0.40,
                                     "mp": 0.45, "utg": 0.50, "sb": 0.40, "bb": 0.45},
            preflop_call_threshold={"btn": 0.55, "co": 0.55, "hj": 0.50,
                                    "mp": 0.50, "utg": 0.45, "sb": 0.50, "bb": 0.50},
            cbet_frequency=0.65,
            cbet_size_pot_fraction=0.55,
            raise_size_pot_fraction=0.75,
            bluff_frequency=0.08,
        )
