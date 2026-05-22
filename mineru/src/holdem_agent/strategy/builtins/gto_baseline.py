from __future__ import annotations

import random

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.equity_calc import (
    get_m_zone,
    is_push_fold,
    raise_amount,
    should_call,
    should_raise,
)
from holdem_agent.strategy.analysts.hand_strength import (
    estimated_equity,
    has_flush_draw,
    has_straight_draw,
)
from holdem_agent.strategy.analysts.position import (
    position_range_adjustment,
    position_tier,
)
from holdem_agent.strategy.analysts.risk import is_allin_candidate
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.genome import StrategyGenome


_TIER_CALL_ADJUSTMENTS = {
    "late": -0.05,
    "middle": 0.0,
    "early": 0.05,
    "blinds": 0.02,
}


class GTOBaseline(Strategy):
    """GTO-inspired baseline strategy using preflop charts + postflop heuristics."""

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or StrategyGenome()

    @property
    def name(self) -> str:
        return "gto-baseline"

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "GTOBaseline":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        equity = estimated_equity(context.hole_cards, context.community_cards)
        tier = position_tier(context.my_seat)
        zone = get_m_zone(context.my_stack, context.blind[0], context.blind[1])

        if is_push_fold(
            context.my_stack,
            context.blind[0],
            context.blind[1],
            threshold=self._genome.m_conservative,
        ):
            return self._push_fold_decision(context, equity, zone)

        if context.phase == "preflop":
            return self._preflop(context, equity, tier)

        return self._postflop(context, equity)

    def _preflop(self, context: DecisionContext, equity: float, tier: str) -> Action:
        threshold = self._genome.preflop_raise_threshold.get(context.my_seat, 0.35)
        adjusted_range = position_range_adjustment(context.my_seat, threshold)
        in_range = hand_in_range(context.hole_cards, adjusted_range)
        call_threshold = self._position_adjusted_call_threshold(context.my_seat, tier)

        if self._facing_raise(context):
            if equity >= call_threshold:
                return Action(action="call", reasoning=f"GTO: defend vs raise equity={equity:.2f}")
            return Action(action="fold", reasoning=f"GTO: fold to raise equity={equity:.2f}")

        if in_range and context.to_call <= context.blind[1]:
            raise_amt = raise_amount(
                equity,
                context.pot,
                context.min_raise,
                self._genome.raise_size_pot_fraction,
            )
            return Action(action="raise", amount=raise_amt, reasoning=f"GTO: open raise equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning="GTO: free check")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"GTO: pot-odds call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"GTO: fold equity={equity:.2f}")

    def _postflop(self, context: DecisionContext, equity: float) -> Action:
        has_draw = has_flush_draw(context.hole_cards, context.community_cards) or has_straight_draw(
            context.hole_cards,
            context.community_cards,
        )

        if equity > 0.65 or (equity >= self._genome.semi_bluff_equity_threshold and has_draw):
            if should_raise(
                equity,
                context.pot,
                context.min_raise,
                self._genome.exploit_aggression,
            ):
                raise_amt = raise_amount(
                    equity,
                    context.pot,
                    context.min_raise,
                    self._genome.cbet_size_pot_fraction,
                )
                return Action(action="raise", amount=raise_amt, reasoning=f"GTO: value raise equity={equity:.2f}")
            if should_call(equity, context.pot, context.to_call):
                return Action(action="call", reasoning=f"GTO: continue equity={equity:.2f}")

        if context.to_call == 0 and self._was_preflop_raiser(context):
            if random.random() < self._genome.cbet_frequency:
                raise_amt = raise_amount(
                    equity,
                    context.pot,
                    context.min_raise,
                    self._genome.cbet_size_pot_fraction,
                )
                return Action(action="raise", amount=raise_amt, reasoning="GTO: c-bet")

        if context.to_call == 0 and equity >= self._genome.fold_to_raise_equity:
            if random.random() < self._genome.bluff_frequency:
                raise_amt = raise_amount(
                    equity,
                    context.pot,
                    context.min_raise,
                    self._genome.cbet_size_pot_fraction,
                )
                return Action(action="raise", amount=raise_amt, reasoning="GTO: bluff")

        if context.to_call == 0:
            return Action(action="check", reasoning="GTO: check back")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"GTO: pot-odds call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"GTO: fold equity={equity:.2f}")

    def _push_fold_decision(self, context: DecisionContext, equity: float, zone: str) -> Action:
        if is_allin_candidate(context.my_stack, context.blind[1], equity):
            return Action(action="allin", reasoning=f"GTO: {zone} push equity={equity:.2f}")
        if context.to_call == 0:
            return Action(action="check", reasoning=f"GTO: {zone} push-fold check")
        if equity > 0.4 and context.to_call <= context.my_stack * 0.3:
            return Action(action="call", reasoning=f"GTO: {zone} desperate call equity={equity:.2f}")
        return Action(action="fold", reasoning=f"GTO: {zone} desperate fold equity={equity:.2f}")

    def _facing_raise(self, context: DecisionContext) -> bool:
        return any(action.phase == "preflop" and action.action == "raise" for action in context.action_history)

    def _was_preflop_raiser(self, context: DecisionContext) -> bool:
        if not context.players:
            return False

        actor_names = {player.name for player in context.players if player.position == context.my_seat}
        if not actor_names:
            return False

        return any(
            action.phase == "preflop" and action.action == "raise" and action.player in actor_names
            for action in context.action_history
        )

    def _position_adjusted_call_threshold(self, seat: str, tier: str) -> float:
        base = self._genome.preflop_call_threshold.get(seat, 0.60)
        return max(0.0, min(1.0, base + _TIER_CALL_ADJUSTMENTS.get(tier, 0.0)))
