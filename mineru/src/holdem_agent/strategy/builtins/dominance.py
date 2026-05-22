from __future__ import annotations

from typing import ClassVar, Self

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.equity_calc import should_call
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.practical import PracticalRead, PracticalStrategy
from holdem_agent.strategy.charts.preflop import get_open_range
from holdem_agent.strategy.charts.pushfold import should_call_push, should_push
from holdem_agent.strategy.genome import StrategyGenome


class DominanceStrategy(PracticalStrategy):
    """Base class for live-oriented dominance candidates.

    These candidates deliberately share the conservative action legalizer and no-I/O
    analyst plumbing from PracticalStrategy, then express different hypotheses for
    where live games may leak chips: seat pressure, squeeze spots, short-stack
    urgency, river discipline, value protection, draw leverage, and counter-punching.
    """

    slug: ClassVar[str] = "dominance"
    label: ClassVar[str] = "Dominance"

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.68,
            cbet_size_pot_fraction=0.62,
            raise_size_pot_fraction=0.92,
            three_bet_size_pot_fraction=1.18,
            bluff_frequency=0.10,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.03,
            fold_to_raise_equity=0.28,
            check_raise_frequency=0.09,
            donk_bet_frequency=0.04,
            m_conservative=13.0,
            m_desperate=4.5,
            exploit_aggression=0.66,
            adapt_speed=0.16,
        )

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> Self:
        return cls(genome=genome)

    def _is_late_position(self, context: DecisionContext) -> bool:
        return context.my_seat in {"btn", "co"}

    def _is_blind(self, context: DecisionContext) -> bool:
        return context.my_seat in {"sb", "bb"}

    def _is_river(self, context: DecisionContext) -> bool:
        return context.phase == "river" or len(context.community_cards) >= 5

    def _bad_large_price(self, context: DecisionContext, read: PracticalRead, equity_cap: float = 0.55) -> bool:
        return context.to_call > max(context.blind[1] * 6, int(context.my_stack * 0.18)) and read.equity < equity_cap

    def _low_spr_commit(self, context: DecisionContext, read: PracticalRead, reason: str) -> Action | None:
        if read.spr.prefer_push_fold and read.equity >= read.spr.commitment_threshold:
            return Action(action="allin", reasoning=f"{self.label}: low-SPR commit {reason}")
        return None


class DominanceSeatPressure(DominanceStrategy):
    """Wins uncontested pots from late position while avoiding early-position bloat."""

    slug = "dominance-seat-pressure"
    label = "DominanceSeatPressure"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0:
            open_range = get_open_range(context.my_seat)
            if self._is_late_position(context) and (read.equity >= 0.36 or hand_in_range(context.hole_cards, open_range + 0.10)):
                return self._raise(context, read, 0.72, "late seat pressure")
            if context.my_seat in {"utg", "utg1"} and read.equity < 0.58:
                return self._check_or_fold(context, f"early discipline equity={read.equity:.2f}")
        if context.to_call > 0 and self._is_late_position(context) and read.equity >= 0.44:
            return Action(action="call", reasoning=f"{self.label}: realize in position equity={read.equity:.2f}")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0 and self._is_late_position(context):
            if read.board.texture_score <= 0.50 and read.equity >= 0.24:
                return self._raise(context, read, 0.52, "dry-board position c-bet")
            if read.blockers.blocker_score >= 0.55 and read.equity >= 0.20:
                return self._raise(context, read, 0.58, "blocker seat pressure")
        return super()._postflop(context, read)


class DominanceShortStackIcm(DominanceStrategy):
    """Push/fold specialist that treats sub-22BB stacks as leverage windows."""

    slug = "dominance-shortstack-icm"
    label = "DominanceShortStackICM"

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= 22.0

    def _short_stack(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0:
            if should_push(context.hole_cards, read.big_blinds) or read.equity >= (0.45 if read.big_blinds <= 10 else 0.52):
                return Action(action="allin", reasoning=f"{self.label}: ICM shove bb={read.big_blinds:.1f}")
            return self._check_or_fold(context, f"ICM pass equity={read.equity:.2f}")
        if should_call_push(context.hole_cards, read.big_blinds) or read.equity >= (0.58 if read.big_blinds > 10 else 0.52):
            return Action(action="allin", reasoning=f"{self.label}: call-off bb={read.big_blinds:.1f}")
        return self._check_or_fold(context, f"ICM fold equity={read.equity:.2f}")

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.big_blinds <= 22.0:
            return self._short_stack(context, read)
        return super()._preflop(context, read)


class DominanceSqueezeIso(DominanceStrategy):
    """Attacks open-plus-call and loose multiway preflop formations."""

    slug = "dominance-squeeze-iso"
    label = "DominanceSqueezeIso"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        squeeze_spot = read.preflop_raise_count >= 1 and read.preflop_call_count >= 1
        if context.to_call > 0 and squeeze_spot:
            if read.blockers.blocks_ace_high or read.equity >= 0.46:
                return self._raise(context, read, 1.25, "blocker squeeze")
            if read.equity >= 0.40 and context.to_call <= max(context.blind[1] * 5, context.pot // 2):
                return Action(action="call", reasoning=f"{self.label}: priced squeeze defense equity={read.equity:.2f}")
        if context.to_call > 0 and read.preflop_call_count >= 2 and read.equity >= 0.52:
            return self._raise(context, read, 1.10, "isolate callers")
        return super()._preflop(context, read)


class DominanceNutDrawLeverager(DominanceStrategy):
    """Turns nut and combo draws into fold-equity pressure, but takes prices."""

    slug = "dominance-nut-draw-leverager"
    label = "DominanceNutDrawLeverager"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        commit = self._low_spr_commit(context, read, "draw/value")
        if commit is not None and (read.has_combo_draw or read.equity >= 0.58):
            return commit
        if read.has_combo_draw and read.equity >= 0.18:
            if context.to_call == 0 or read.spr.category != "high":
                return self._raise(context, read, 0.88, "combo draw leverage")
        if read.has_draw:
            if context.to_call == 0 and (read.blockers.blocker_score >= 0.35 or read.equity >= 0.25):
                return self._raise(context, read, 0.62, "nut draw pressure")
            if context.to_call > 0 and should_call(read.equity, context.pot, context.to_call, margin=read.spr.draw_call_margin - 0.05):
                return Action(action="call", reasoning=f"{self.label}: priced draw equity={read.equity:.2f}")
        return super()._postflop(context, read)


class DominanceWetBoardProtector(DominanceStrategy):
    """Fast-plays high-equity made hands on coordinated boards for protection."""

    slug = "dominance-wet-board-protector"
    label = "DominanceWetBoardProtector"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        wet = read.board.texture_score >= 0.55 or read.board.is_monotone or read.board.is_two_tone
        if read.equity >= 0.62 and wet:
            return self._raise(context, read, 0.95, "wet-board protection")
        if read.equity >= 0.70:
            return self._raise(context, read, 0.74, "clean value")
        if self._is_river(context) and self._bad_large_price(context, read, equity_cap=0.62):
            return self._check_or_fold(context, f"river protection fold equity={read.equity:.2f}")
        return super()._postflop(context, read)


class DominanceRiverSieve(DominanceStrategy):
    """Cuts off expensive river mistakes and value-bets clear edges."""

    slug = "dominance-river-sieve"
    label = "DominanceRiverSieve"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if self._is_river(context):
            if context.to_call > 0:
                if self._bad_large_price(context, read, equity_cap=0.66):
                    return self._check_or_fold(context, f"river sieve fold equity={read.equity:.2f}")
                if should_call(read.equity, context.pot, context.to_call, margin=0.08):
                    return Action(action="call", reasoning=f"{self.label}: river value catch equity={read.equity:.2f}")
                return self._check_or_fold(context, f"river no price equity={read.equity:.2f}")
            if read.equity >= 0.64:
                return self._raise(context, read, 0.58, "river value sieve")
            return Action(action="check", reasoning=f"{self.label}: river showdown control")
        return super()._postflop(context, read)


class DominanceCounterPunch(DominanceStrategy):
    """Bluff-catches aggressive lines and refuses to pay passive strength."""

    slug = "dominance-counter-punch"
    label = "DominanceCounterPunch"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0 and read.opponent_aggression >= 2.0:
            if read.equity >= 0.53:
                return Action(action="call", reasoning=f"{self.label}: preflop counter trap equity={read.equity:.2f}")
            if read.blockers.blocks_ace_high and read.equity >= 0.43:
                return self._raise(context, read, 1.05, "blocker counter 3-bet")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.opponent_aggression >= 2.0:
            if context.to_call > 0 and read.equity >= 0.52:
                return Action(action="call", reasoning=f"{self.label}: bluff-catch aggression equity={read.equity:.2f}")
            if context.to_call == 0 and read.equity >= 0.66:
                return self._raise(context, read, 0.64, "counter value")
            if read.equity < 0.42:
                return self._check_or_fold(context, f"counter fold equity={read.equity:.2f}")
        return super()._postflop(context, read)


class DominanceBlindRestealPro(DominanceStrategy):
    """Defends blinds against small steals while avoiding dominated large calls."""

    slug = "dominance-blind-resteal-pro"
    label = "DominanceBlindRestealPro"

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if self._is_blind(context):
            affordable = context.to_call <= max(context.blind[1] * 5, context.pot // 2)
            if context.to_call > 0 and affordable:
                defend = 0.46 if context.my_seat == "bb" else 0.34
                if read.blockers.blocks_ace_high and read.equity >= 0.38:
                    return self._raise(context, read, 1.05, "blind resteal blocker")
                if hand_in_range(context.hole_cards, defend) or read.equity >= 0.40:
                    return Action(action="call", reasoning=f"{self.label}: blind defend equity={read.equity:.2f}")
            if context.to_call == 0 and read.equity >= 0.47:
                return self._raise(context, read, 0.68, "blind initiative")
        return super()._preflop(context, read)


class DominanceValueExtractor(DominanceStrategy):
    """Anti-station value engine with reduced bluff frequency."""

    slug = "dominance-value-extractor"
    label = "DominanceValueExtractor"

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        passive_table = read.opponent_aggression <= 1.0
        if read.equity >= 0.60:
            size = 0.92 if passive_table or read.board.texture_score >= 0.55 else 0.70
            return self._raise(context, read, size, "value extraction")
        if context.to_call > 0 and read.equity >= 0.50 and should_call(read.equity, context.pot, context.to_call, margin=0.04):
            return Action(action="call", reasoning=f"{self.label}: controlled value call equity={read.equity:.2f}")
        if context.to_call == 0 and read.equity < 0.34:
            return Action(action="check", reasoning=f"{self.label}: skip low-EV bluff")
        return super()._postflop(context, read)


class DominanceLowVarianceGrinder(DominanceStrategy):
    """Keeps pots small without clear edge and compounds small profitable calls."""

    slug = "dominance-low-variance-grinder"
    label = "DominanceLowVarianceGrinder"

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= 9.0

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            if context.to_call > context.my_stack * 0.12 and read.equity < 0.64:
                return self._check_or_fold(context, f"variance cap fold equity={read.equity:.2f}")
            if should_call(read.equity, context.pot, context.to_call, margin=0.03):
                return Action(action="call", reasoning=f"{self.label}: priced preflop equity={read.equity:.2f}")
        if context.to_call == 0 and read.equity >= 0.56:
            return self._raise(context, read, 0.62, "low-variance open")
        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            if self._bad_large_price(context, read, equity_cap=0.68):
                return self._check_or_fold(context, f"variance cap fold equity={read.equity:.2f}")
            if should_call(read.equity, context.pot, context.to_call, margin=0.06):
                return Action(action="call", reasoning=f"{self.label}: low-variance call equity={read.equity:.2f}")
        if context.to_call == 0 and read.equity >= 0.68:
            return self._raise(context, read, 0.60, "protected value")
        return self._check_or_fold(context, f"low-variance decline equity={read.equity:.2f}")


class DominanceAdaptiveConductor(DominanceStrategy):
    """Meta candidate that routes live spots to the strongest dominance archetype."""

    slug = "dominance-adaptive-conductor"
    label = "DominanceAdaptiveConductor"

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        super().__init__(genome=genome)
        self._seat = DominanceSeatPressure(self.genome)
        self._short = DominanceShortStackIcm(self.genome)
        self._squeeze = DominanceSqueezeIso(self.genome)
        self._draw = DominanceNutDrawLeverager(self.genome)
        self._wet = DominanceWetBoardProtector(self.genome)
        self._river = DominanceRiverSieve(self.genome)
        self._counter = DominanceCounterPunch(self.genome)
        self._blind = DominanceBlindRestealPro(self.genome)
        self._value = DominanceValueExtractor(self.genome)
        self._grinder = DominanceLowVarianceGrinder(self.genome)

    def decide(self, context: DecisionContext) -> Action:
        read = self._read_context(context)
        if read.big_blinds <= 18.0:
            action = self._short._short_stack(context, read)
        elif context.phase == "preflop" and read.preflop_raise_count >= 1 and read.preflop_call_count >= 1:
            action = self._squeeze._preflop(context, read)
        elif context.phase == "preflop" and context.my_seat in {"sb", "bb"}:
            action = self._blind._preflop(context, read)
        elif context.phase != "preflop" and (context.phase == "river" or len(context.community_cards) >= 5):
            action = self._river._postflop(context, read)
        elif read.opponent_aggression >= 2.0:
            action = self._counter._preflop(context, read) if context.phase == "preflop" else self._counter._postflop(context, read)
        elif context.phase != "preflop" and read.has_draw:
            action = self._draw._postflop(context, read)
        elif context.phase != "preflop" and (read.board.texture_score >= 0.55 or read.equity >= 0.64):
            action = self._wet._postflop(context, read)
        elif context.phase != "preflop" and read.equity >= 0.58:
            action = self._value._postflop(context, read)
        elif self._is_late_position(context):
            action = self._seat._preflop(context, read) if context.phase == "preflop" else self._seat._postflop(context, read)
        else:
            action = self._grinder._preflop(context, read) if context.phase == "preflop" else self._grinder._postflop(context, read)
        legalized = self._legalize(context, action)
        return Action(
            action=legalized.action,
            amount=legalized.amount,
            reasoning=legalized.reasoning,
            strategy_name=self.name,
        )


DOMINANCE_STRATEGIES: tuple[type[DominanceStrategy], ...] = (
    DominanceSeatPressure,
    DominanceShortStackIcm,
    DominanceSqueezeIso,
    DominanceNutDrawLeverager,
    DominanceWetBoardProtector,
    DominanceRiverSieve,
    DominanceCounterPunch,
    DominanceBlindRestealPro,
    DominanceValueExtractor,
    DominanceAdaptiveConductor,
)
