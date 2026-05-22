from __future__ import annotations

import random

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.equity_calc import raise_amount, should_call, should_raise
from holdem_agent.strategy.analysts.hand_strength import estimated_equity
from holdem_agent.strategy.analysts.opponent import OpponentTracker
from holdem_agent.strategy.analysts.risk import risk_tolerance
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.genome import StrategyGenome


class Adaptive(Strategy):
    """Adaptive strategy that adjusts to opponent tendencies."""

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or StrategyGenome()
        self._opponent_tracker = OpponentTracker()

    @property
    def name(self) -> str:
        return "adaptive"

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "Adaptive":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        self._update_opponents(context)
        equity = estimated_equity(context.hole_cards, context.community_cards)
        tolerance = risk_tolerance(context.my_stack, context.blind[0], context.blind[1])

        if context.phase == "preflop":
            return self._preflop(context, equity, tolerance)
        return self._postflop(context, equity, tolerance)

    def _preflop(self, context: DecisionContext, equity: float, tolerance: float) -> Action:
        threshold = self._genome.preflop_raise_threshold.get(context.my_seat, 0.35)
        in_range = hand_in_range(context.hole_cards, threshold)
        weak_equity_cutoff = max(0.2, 0.3 - (tolerance * 0.05))

        if not in_range and equity < weak_equity_cutoff:
            if context.to_call == 0:
                return Action(action="check", reasoning="Adaptive: out of range")
            return Action(action="fold", reasoning="Adaptive: out of range, weak")

        opp_aggression = self._average_opponent_aggression()
        if opp_aggression > 1.5 and equity > 0.55 and context.to_call > 0:
            return Action(action="call", reasoning="Adaptive: trap vs aggro")

        if opp_aggression < 0.8 and context.to_call == 0:
            amount = raise_amount(
                equity,
                context.pot,
                context.min_raise,
                self._genome.raise_size_pot_fraction,
            )
            return Action(action="raise", amount=amount, reasoning="Adaptive: exploit passive")

        if context.to_call == 0 and in_range:
            amount = raise_amount(
                equity,
                context.pot,
                context.min_raise,
                self._genome.raise_size_pot_fraction,
            )
            return Action(action="raise", amount=amount, reasoning=f"Adaptive: open equity={equity:.2f}")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"Adaptive: call equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning="Adaptive: check")

        return Action(action="fold", reasoning=f"Adaptive: fold equity={equity:.2f}")

    def _postflop(self, context: DecisionContext, equity: float, tolerance: float) -> Action:
        opp_aggression = self._average_opponent_aggression()

        if equity > 0.6:
            if should_raise(
                equity,
                context.pot,
                context.min_raise,
                self._genome.exploit_aggression,
            ):
                amount = raise_amount(
                    equity,
                    context.pot,
                    context.min_raise,
                    self._genome.raise_size_pot_fraction,
                )
                return Action(
                    action="raise",
                    amount=amount,
                    reasoning=f"Adaptive: value raise equity={equity:.2f}",
                )
            return Action(action="call", reasoning=f"Adaptive: value call equity={equity:.2f}")

        if opp_aggression < 0.8 and context.to_call == 0:
            adjusted_bluff = self._genome.bluff_frequency * (1 + self._genome.exploit_aggression * tolerance)
            if random.random() < adjusted_bluff:
                amount = raise_amount(equity, context.pot, context.min_raise)
                return Action(action="raise", amount=amount, reasoning="Adaptive: exploit bluff")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"Adaptive: call equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning="Adaptive: check")

        return Action(action="fold", reasoning=f"Adaptive: fold equity={equity:.2f}")

    def _update_opponents(self, context: DecisionContext) -> None:
        """Update opponent tracking from action history."""
        for action in context.action_history:
            self._opponent_tracker.record_action(action.player, action.action, action.phase)

    def _average_opponent_aggression(self) -> float:
        """Get average aggression factor of opponents."""
        profiles = self._opponent_tracker.all_profiles
        if not profiles:
            return 1.0
        return sum(profile.aggression_factor for profile in profiles.values()) / len(profiles)

    @property
    def opponent_tracker(self) -> OpponentTracker:
        return self._opponent_tracker
