from __future__ import annotations

import dataclasses
from typing import ClassVar, Self

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.blockers import BlockerAnalysis, analyze_blockers
from holdem_agent.strategy.analysts.board_texture import BoardTextureAnalysis, analyze_board_texture
from holdem_agent.strategy.analysts.equity_calc import raise_amount, should_call, should_raise
from holdem_agent.strategy.analysts.hand_strength import (
    estimated_equity,
    has_flush_draw,
    has_straight_draw,
)
from holdem_agent.strategy.analysts.position import position_advantage, position_range_adjustment
from holdem_agent.strategy.analysts.spr import SPRAnalysis, analyze_spr
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.charts.preflop import get_3bet_range, get_call_range, get_open_range
from holdem_agent.strategy.charts.pushfold import should_call_push, should_push
from holdem_agent.strategy.genome import StrategyGenome


AGGRESSIVE_ACTIONS = {"raise", "bet", "allin"}
CALLING_ACTIONS = {"call", "raise", "bet", "allin"}


@dataclasses.dataclass(frozen=True)
class PracticalRead:
    """Deterministic analyst snapshot shared by practical built-in strategies."""

    equity: float
    board: BoardTextureAnalysis
    blockers: BlockerAnalysis
    spr: SPRAnalysis
    position_advantage: float
    opponent_aggression: float
    big_blinds: float
    preflop_raise_count: int
    preflop_call_count: int
    has_flush_draw: bool
    has_straight_draw: bool

    @property
    def has_draw(self) -> bool:
        return self.has_flush_draw or self.has_straight_draw

    @property
    def has_combo_draw(self) -> bool:
        return self.has_flush_draw and self.has_straight_draw


class PracticalStrategy(Strategy):
    """Base for local practical archetypes with shared legality and analyst plumbing."""

    slug: ClassVar[str] = "practical"
    label: ClassVar[str] = "Practical"

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or self._default_genome()

    @property
    def name(self) -> str:
        return self.slug

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> Self:
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        read = self._read_context(context)
        if self._is_push_fold_spot(context, read):
            action = self._short_stack(context, read)
        elif context.phase == "preflop":
            action = self._preflop(context, read)
        else:
            action = self._postflop(context, read)
        return self._legalize(context, action)

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        open_range = position_range_adjustment(context.my_seat, get_open_range(context.my_seat))
        call_range = position_range_adjustment(context.my_seat, get_call_range(context.my_seat))
        three_bet_range = position_range_adjustment(context.my_seat, get_3bet_range(context.my_seat))

        if context.to_call == 0:
            if hand_in_range(context.hole_cards, open_range) or read.equity >= 0.52:
                return self._raise(context, read, self.genome.raise_size_pot_fraction, "open pressure")
            return self._check_or_fold(context, "outside opening range")

        if hand_in_range(context.hole_cards, three_bet_range) and read.equity >= 0.48:
            return self._raise(context, read, self.genome.three_bet_size_pot_fraction, "value 3-bet")
        if hand_in_range(context.hole_cards, call_range) or should_call(read.equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"{self.label}: defend equity={read.equity:.2f}")
        return self._check_or_fold(context, f"fold preflop equity={read.equity:.2f}")

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.equity >= 0.66:
            if context.to_call == 0 or should_raise(
                read.equity,
                context.pot,
                context.min_raise,
                self.genome.exploit_aggression,
            ):
                return self._raise(context, read, self.genome.raise_size_pot_fraction, "value pressure")
            return Action(action="call", reasoning=f"{self.label}: value call equity={read.equity:.2f}")

        if read.has_draw and read.equity >= self.genome.semi_bluff_equity_threshold:
            if context.to_call == 0 and read.position_advantage >= 0.55:
                return self._raise(context, read, self.genome.cbet_size_pot_fraction, "semi-bluff draw")
            if should_call(read.equity, context.pot, context.to_call, margin=-0.02):
                return Action(action="call", reasoning=f"{self.label}: draw price equity={read.equity:.2f}")

        if should_call(read.equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"{self.label}: pot-odds continue equity={read.equity:.2f}")
        return self._check_or_fold(context, f"low equity={read.equity:.2f}")

    def _short_stack(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0:
            if should_push(context.hole_cards, read.big_blinds) or read.equity >= 0.48:
                return Action(action="allin", reasoning=f"{self.label}: push-fold shove")
            return self._check_or_fold(context, "push-fold pass")

        if should_call_push(context.hole_cards, read.big_blinds) or read.equity >= 0.55:
            return Action(action="allin", reasoning=f"{self.label}: push-fold call-off")
        return self._check_or_fold(context, "push-fold fold")

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= self.genome.m_conservative

    def _read_context(self, context: DecisionContext) -> PracticalRead:
        return PracticalRead(
            equity=estimated_equity(context.hole_cards, context.community_cards),
            board=analyze_board_texture(context.community_cards),
            blockers=analyze_blockers(context.hole_cards, context.community_cards),
            spr=analyze_spr(context.my_stack, context.pot),
            position_advantage=position_advantage(context.my_seat),
            opponent_aggression=_opponent_aggression(context),
            big_blinds=_big_blinds(context),
            preflop_raise_count=sum(
                1 for action in context.action_history
                if action.phase == "preflop" and action.action in AGGRESSIVE_ACTIONS
            ),
            preflop_call_count=sum(
                1 for action in context.action_history
                if action.phase == "preflop" and action.action == "call"
            ),
            has_flush_draw=has_flush_draw(context.hole_cards, context.community_cards),
            has_straight_draw=has_straight_draw(context.hole_cards, context.community_cards),
        )

    def _raise(
        self,
        context: DecisionContext,
        read: PracticalRead,
        fraction: float,
        reason: str,
    ) -> Action:
        amount = raise_amount(read.equity, context.pot, context.min_raise, fraction)
        if amount >= context.my_stack:
            return Action(action="allin", reasoning=f"{self.label}: {reason} all-in")
        return Action(
            action="raise",
            amount=amount,
            reasoning=f"{self.label}: {reason} equity={read.equity:.2f}",
        )

    def _check_or_fold(self, context: DecisionContext, reason: str) -> Action:
        if context.to_call == 0:
            return Action(action="check", reasoning=f"{self.label}: {reason}")
        return Action(action="fold", reasoning=f"{self.label}: {reason}")

    def _legalize(self, context: DecisionContext, action: Action) -> Action:
        if context.my_stack <= 0:
            return self._check_or_fold(context, "no stack")

        if action.action == "check" and context.to_call > 0:
            return Action(action="fold", reasoning=f"{self.label}: converted illegal check")
        if action.action == "call" and context.to_call == 0:
            return Action(action="check", reasoning=f"{self.label}: converted free call")
        if action.action == "fold" and context.to_call == 0:
            return Action(action="check", reasoning=f"{self.label}: converted free fold")
        if action.action == "raise":
            amount = action.amount if action.amount is not None else context.min_raise
            amount = max(context.min_raise, amount)
            if amount >= context.my_stack:
                return Action(action="allin", reasoning=action.reasoning, strategy_name=self.name)
            return Action(
                action="raise",
                amount=amount,
                reasoning=action.reasoning,
                strategy_name=self.name,
            )
        return Action(
            action=action.action,
            amount=action.amount,
            reasoning=action.reasoning,
            strategy_name=self.name,
        )

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.62,
            cbet_size_pot_fraction=0.58,
            raise_size_pot_fraction=0.82,
            three_bet_size_pot_fraction=1.05,
            bluff_frequency=0.12,
            semi_bluff_equity_threshold=0.24,
            river_bluff_frequency=0.05,
            fold_to_raise_equity=0.24,
            check_raise_frequency=0.08,
            donk_bet_frequency=0.07,
            m_conservative=14.0,
            m_desperate=5.0,
            exploit_aggression=0.58,
            adapt_speed=0.12,
        )


class PositionalPressure(PracticalStrategy):
    """Late-position steals and dry-board continuation pressure."""

    slug = "positional-pressure"
    label = "PositionalPressure"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        widened = max(0.05, get_open_range(context.my_seat) - (read.position_advantage * 0.10))
        if context.to_call == 0 and (read.position_advantage >= 0.65 or hand_in_range(context.hole_cards, widened)):
            return self._raise(context, read, self.genome.raise_size_pot_fraction, "position steal")
        if context.to_call > 0 and read.position_advantage >= 0.65 and read.equity >= 0.42:
            return Action(action="call", reasoning=f"{self.label}: position defend equity={read.equity:.2f}")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        dry_or_blocked = read.board.texture_score <= 0.45 or read.blockers.blocker_score >= 0.45
        if context.to_call == 0 and read.position_advantage >= 0.65 and dry_or_blocked:
            if read.equity >= 0.20:
                return self._raise(context, read, self.genome.cbet_size_pot_fraction, "positional c-bet")
        return super()._postflop(context, read)


class ShortStackPushFold(PracticalStrategy):
    """Tournament short-stack push/fold specialist using local Nash-style charts."""

    slug = "short-stack-push-fold"
    label = "ShortStackPushFold"

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= 20.0

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.big_blinds <= 20.0:
            return self._short_stack(context, read)
        return super()._preflop(context, read)


class SqueezeAggressor(PracticalStrategy):
    """Punishes open-plus-call spots with blocker-aware squeezes."""

    slug = "squeeze-aggressor"
    label = "SqueezeAggressor"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        squeeze_spot = read.preflop_raise_count >= 1 and read.preflop_call_count >= 1
        blocker_pressure = read.blockers.blocks_ace_high or read.equity >= 0.48
        if context.to_call > 0 and squeeze_spot and blocker_pressure:
            return self._raise(context, read, self.genome.three_bet_size_pot_fraction, "squeeze")
        if context.to_call > 0 and read.preflop_raise_count >= 1 and read.equity >= 0.58:
            return self._raise(context, read, self.genome.three_bet_size_pot_fraction, "anti-open 3-bet")
        return super()._preflop(context, read)


class PotOddsGrinder(PracticalStrategy):
    """Low-variance grinder that continues only when price and equity cooperate."""

    slug = "pot-odds-grinder"
    label = "PotOddsGrinder"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            if should_call(read.equity, context.pot, context.to_call, margin=0.0):
                return Action(action="call", reasoning=f"{self.label}: priced preflop equity={read.equity:.2f}")
            return self._check_or_fold(context, f"bad preflop price equity={read.equity:.2f}")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.equity >= 0.72 and context.to_call == 0:
            return self._raise(context, read, 0.62, "thin value")
        if context.to_call > 0 and should_call(read.equity, context.pot, context.to_call, margin=-0.01):
            return Action(action="call", reasoning=f"{self.label}: pot odds equity={read.equity:.2f}")
        return self._check_or_fold(context, f"decline price equity={read.equity:.2f}")


class DrawSemiBluffPressure(PracticalStrategy):
    """Applies fold equity with flush, straight, and combo-draw pressure."""

    slug = "draw-semi-bluff-pressure"
    label = "DrawSemiBluffPressure"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.has_combo_draw and read.equity >= 0.18:
            if context.to_call == 0 or read.spr.category != "high":
                return self._raise(context, read, self.genome.raise_size_pot_fraction, "combo draw pressure")
        if read.has_draw and read.equity >= 0.22:
            if context.to_call == 0:
                return self._raise(context, read, self.genome.cbet_size_pot_fraction, "draw semi-bluff")
            if should_call(read.equity, context.pot, context.to_call, margin=-0.04):
                return Action(action="call", reasoning=f"{self.label}: draw price equity={read.equity:.2f}")
        return super()._postflop(context, read)


class ValueHeavyStationPunisher(PracticalStrategy):
    """Value-heavy anti-calling-station strategy with deliberately scarce bluffs."""

    slug = "value-heavy-station-punisher"
    label = "ValueHeavyStationPunisher"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.equity >= 0.62:
            return self._raise(context, read, 0.90 if read.board.texture_score > 0.55 else 0.72, "value-heavy bet")
        if read.equity >= 0.48 and context.to_call > 0 and should_call(read.equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"{self.label}: controlled value equity={read.equity:.2f}")
        return self._check_or_fold(context, f"no thin bluff equity={read.equity:.2f}")


class AntiManiacTrapper(PracticalStrategy):
    """Keeps strong hands in against aggressive opponents and avoids bluff wars."""

    slug = "anti-maniac-trapper"
    label = "AntiManiacTrapper"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0 and read.opponent_aggression >= 2.0 and read.equity >= 0.54:
            return Action(action="call", reasoning=f"{self.label}: trap maniac preflop equity={read.equity:.2f}")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.opponent_aggression >= 2.0:
            if read.equity >= 0.58 and context.to_call > 0:
                return Action(action="call", reasoning=f"{self.label}: trap aggression equity={read.equity:.2f}")
            if read.equity < 0.45:
                return self._check_or_fold(context, f"avoid bluff war equity={read.equity:.2f}")
        return super()._postflop(context, read)


class BlindDefenseResteal(PracticalStrategy):
    """Defends blinds and resteals against likely late-position pressure."""

    slug = "blind-defense-resteal"
    label = "BlindDefenseResteal"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        in_blinds = context.my_seat in {"sb", "bb"}
        affordable_steal = context.to_call <= max(context.blind[1] * 4, context.min_raise * 2)
        defend_range = 0.42 if context.my_seat == "bb" else 0.32
        if in_blinds and context.to_call > 0 and affordable_steal:
            if read.blockers.blocks_ace_high and read.equity >= 0.36:
                return self._raise(context, read, self.genome.three_bet_size_pot_fraction, "blind resteal")
            if hand_in_range(context.hole_cards, defend_range) or read.equity >= 0.38:
                return Action(action="call", reasoning=f"{self.label}: blind defend equity={read.equity:.2f}")
        if in_blinds and context.to_call == 0 and read.equity >= 0.48:
            return self._raise(context, read, self.genome.raise_size_pot_fraction, "blind steal")
        return super()._preflop(context, read)


class BankrollPreserver(PracticalStrategy):
    """Risk-managed strategy that protects stack depth and avoids marginal gambles."""

    slug = "bankroll-preserver"
    label = "BankrollPreserver"

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= 8.0

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        stack_pressure = context.my_stack < context.starting_stack * 0.65
        if stack_pressure and context.to_call > context.my_stack * 0.08 and read.equity < 0.62:
            return self._check_or_fold(context, f"preserve stack equity={read.equity:.2f}")
        if context.to_call == 0 and read.equity >= 0.58:
            return self._raise(context, read, 0.65, "careful open")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > context.my_stack * 0.15 and read.equity < 0.68:
            return self._check_or_fold(context, f"avoid large call equity={read.equity:.2f}")
        if read.equity >= 0.70:
            return self._raise(context, read, 0.65, "protected value")
        if context.to_call > 0 and should_call(read.equity, context.pot, context.to_call, margin=0.08):
            return Action(action="call", reasoning=f"{self.label}: high-confidence call equity={read.equity:.2f}")
        return self._check_or_fold(context, f"preserve chips equity={read.equity:.2f}")


class MetaAdaptiveBlend(PracticalStrategy):
    """Adaptive blend that routes each spot to the strongest practical archetype."""

    slug = "meta-adaptive-blend"
    label = "MetaAdaptiveBlend"

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        super().__init__(genome=genome)
        self._short = ShortStackPushFold(self.genome)
        self._trap = AntiManiacTrapper(self.genome)
        self._draw = DrawSemiBluffPressure(self.genome)
        self._blind = BlindDefenseResteal(self.genome)
        self._squeeze = SqueezeAggressor(self.genome)
        self._position = PositionalPressure(self.genome)
        self._grinder = PotOddsGrinder(self.genome)
        self._value = ValueHeavyStationPunisher(self.genome)

    def decide(self, context: DecisionContext) -> Action:
        read = self._read_context(context)
        if read.big_blinds <= 14.0:
            action = self._short._short_stack(context, read)
        elif context.phase == "preflop" and read.preflop_raise_count >= 1 and read.preflop_call_count >= 1:
            action = self._squeeze._preflop(context, read)
        elif context.my_seat in {"sb", "bb"} and context.phase == "preflop":
            action = self._blind._preflop(context, read)
        elif read.opponent_aggression >= 2.0:
            action = self._trap._preflop(context, read) if context.phase == "preflop" else self._trap._postflop(context, read)
        elif context.phase != "preflop" and read.has_draw:
            action = self._draw._postflop(context, read)
        elif context.phase != "preflop" and read.equity >= 0.62:
            action = self._value._postflop(context, read)
        elif read.position_advantage >= 0.65:
            action = self._position._preflop(context, read) if context.phase == "preflop" else self._position._postflop(context, read)
        else:
            action = self._grinder._preflop(context, read) if context.phase == "preflop" else self._grinder._postflop(context, read)
        legalized = self._legalize(context, action)
        return Action(
            action=legalized.action,
            amount=legalized.amount,
            reasoning=legalized.reasoning.replace(legalized.strategy_name, self.label)
            if legalized.strategy_name else f"{self.label}: {legalized.reasoning}",
            strategy_name=self.name,
        )


PRACTICAL_STRATEGIES: tuple[type[PracticalStrategy], ...] = (
    PositionalPressure,
    ShortStackPushFold,
    SqueezeAggressor,
    PotOddsGrinder,
    DrawSemiBluffPressure,
    ValueHeavyStationPunisher,
    AntiManiacTrapper,
    BlindDefenseResteal,
    BankrollPreserver,
    MetaAdaptiveBlend,
)


def _big_blinds(context: DecisionContext) -> float:
    big_blind = max(1, context.blind[1])
    return context.my_stack / big_blind


def _opponent_aggression(context: DecisionContext) -> float:
    aggressive = sum(1 for action in context.action_history if action.action in AGGRESSIVE_ACTIONS)
    calls = sum(1 for action in context.action_history if action.action == "call")
    if aggressive == 0:
        return 1.0
    if calls == 0:
        return float(aggressive)
    return aggressive / calls
