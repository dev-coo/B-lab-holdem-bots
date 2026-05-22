from __future__ import annotations

import dataclasses
from typing import ClassVar, Self

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.equity_calc import should_call
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.practical import PracticalRead, PracticalStrategy
from holdem_agent.strategy.charts.preflop import get_open_range
from holdem_agent.strategy.charts.pushfold import should_call_push, should_push
from holdem_agent.strategy.genome import StrategyGenome


RANK_VALUES = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}


@dataclasses.dataclass(frozen=True)
class ArenaProfile:
    """Small tuning surface for arena search candidates.

    The candidates deliberately share one practical decision skeleton so the
    validator can compare focused strategic hypotheses instead of ten unrelated
    frameworks.  Profile values move the live-play bias while preserving the
    same high-signal tournament fundamentals.
    """

    late_open_bonus: float = 0.08
    late_open_equity: float = 0.34
    squeeze_equity: float = 0.45
    blind_defend_range: float = 0.46
    blind_call_equity: float = 0.39
    blind_resteal_equity: float = 0.42
    short_stack_bb: float = 18.0
    short_open_equity: float = 0.46
    short_call_equity: float = 0.54
    maniac_call_equity: float = 0.50
    draw_call_margin: float = -0.04
    combo_draw_equity: float = 0.18
    wet_value_equity: float = 0.60
    dry_cbet_equity: float = 0.20
    value_equity: float = 0.66
    river_value_equity: float = 0.64
    large_price_equity_cap: float = 0.66
    pressure_size: float = 0.64
    value_size: float = 0.90
    draw_size: float = 0.78
    squeeze_size: float = 1.16
    blind_mode: str = "call"


class ArenaStrategy(PracticalStrategy):
    """Base class for the 10 autoresearch arena candidates.

    The policy encodes live-useful tournament priorities:
    - push premium short stacks instead of min-raising away fold equity;
    - attack open-plus-call squeeze spots with blockers;
    - defend big blinds against small steals without dominated overfolding;
    - take priced nut draws, but apply pressure with combo draws;
    - bluff-catch clear maniac lines while folding large bad river prices;
    - fast-play wet-board value.
    """

    slug: ClassVar[str] = "arena"
    label: ClassVar[str] = "Arena"
    profile: ClassVar[ArenaProfile] = ArenaProfile()

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> Self:
        return cls(genome=genome)

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.64,
            cbet_size_pot_fraction=0.58,
            raise_size_pot_fraction=0.86,
            three_bet_size_pot_fraction=1.14,
            bluff_frequency=0.08,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.02,
            fold_to_raise_equity=0.30,
            check_raise_frequency=0.06,
            donk_bet_frequency=0.03,
            m_conservative=14.0,
            m_desperate=4.5,
            exploit_aggression=0.62,
            adapt_speed=0.16,
        )

    def decide(self, context: DecisionContext) -> Action:
        read = self._read_context(context)
        if context.phase == "preflop":
            action = self._arena_preflop(context, read)
        else:
            action = self._arena_postflop(context, read)
        legalized = self._legalize(context, action)
        return Action(
            action=legalized.action,
            amount=legalized.amount,
            reasoning=legalized.reasoning,
            strategy_name=self.name,
        )

    def _arena_preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if read.big_blinds <= self.profile.short_stack_bb:
            return self._short_stack_arena(context, read)

        if context.to_call > 0:
            squeeze = read.preflop_raise_count >= 1 and read.preflop_call_count >= 1
            if squeeze and (read.blockers.blocks_ace_high or read.equity >= self.profile.squeeze_equity):
                return self._raise(context, read, self.profile.squeeze_size, "arena blocker squeeze")

            if self._is_blind(context) and self._is_affordable_steal_price(context):
                if (
                    self.profile.blind_mode == "resteal"
                    and read.blockers.blocks_ace_high
                    and read.equity >= self.profile.blind_resteal_equity
                ):
                    return self._raise(context, read, 1.02, "arena blind resteal")
                if (
                    hand_in_range(context.hole_cards, self.profile.blind_defend_range)
                    or read.equity >= self.profile.blind_call_equity
                ):
                    return Action(
                        action="call",
                        reasoning=f"{self.label}: arena blind defend equity={read.equity:.2f}",
                    )

            if read.equity >= 0.58 or should_call(read.equity, context.pot, context.to_call, margin=0.02):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: arena priced preflop continue equity={read.equity:.2f}",
                )
            return self._check_or_fold(context, f"arena preflop fold equity={read.equity:.2f}")

        if self._is_late_position(context):
            open_range = min(1.0, get_open_range(context.my_seat) + self.profile.late_open_bonus)
            if (
                hand_in_range(context.hole_cards, open_range)
                or read.blockers.blocks_ace_high
                or read.equity >= self.profile.late_open_equity
            ):
                return self._raise(context, read, self.profile.pressure_size, "arena late-seat pressure")

        if read.equity >= 0.56 or self._is_broadway_pair_or_ace(context):
            return self._raise(context, read, 0.72, "arena value open")

        return self._check_or_fold(context, f"arena preflop pass equity={read.equity:.2f}")

    def _short_stack_arena(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0:
            if (
                should_push(context.hole_cards, read.big_blinds)
                or read.equity >= self.profile.short_open_equity
                or self._is_premium_broadway(context)
            ):
                return Action(action="allin", reasoning=f"{self.label}: arena short-stack shove")
            return self._check_or_fold(context, f"arena short-stack pass equity={read.equity:.2f}")

        if (
            should_call_push(context.hole_cards, read.big_blinds)
            or read.equity >= self.profile.short_call_equity
            or self._is_premium_broadway(context)
        ):
            return Action(action="allin", reasoning=f"{self.label}: arena short-stack call-off")
        return self._check_or_fold(context, f"arena short-stack fold equity={read.equity:.2f}")

    def _arena_postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if self._is_river(context):
            return self._arena_river(context, read)

        if context.to_call > 0:
            if read.opponent_aggression >= 2.0 and read.equity >= self.profile.maniac_call_equity:
                return Action(
                    action="call",
                    reasoning=f"{self.label}: arena bluff-catch aggression equity={read.equity:.2f}",
                )

            if read.has_draw:
                if should_call(read.equity, context.pot, context.to_call, margin=self.profile.draw_call_margin):
                    return Action(
                        action="call",
                        reasoning=f"{self.label}: arena priced draw equity={read.equity:.2f}",
                    )
                if read.has_combo_draw and read.equity >= 0.30:
                    return self._raise(context, read, self.profile.draw_size, "arena combo draw raise")

            if self._bad_large_price(context, read):
                return self._check_or_fold(context, f"arena large-price fold equity={read.equity:.2f}")

            if read.equity >= 0.68:
                return self._raise(context, read, self.profile.value_size, "arena value raise")
            if should_call(read.equity, context.pot, context.to_call, margin=0.04):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: arena priced call equity={read.equity:.2f}",
                )
            return self._check_or_fold(context, f"arena postflop fold equity={read.equity:.2f}")

        if read.has_combo_draw and read.equity >= self.profile.combo_draw_equity:
            return self._raise(context, read, self.profile.draw_size, "arena combo draw pressure")

        if self._is_wet_board(read) and read.equity >= self.profile.wet_value_equity:
            return self._raise(context, read, self.profile.value_size, "arena wet-board value")

        if self._is_late_position(context) and read.board.texture_score <= 0.50 and read.equity >= self.profile.dry_cbet_equity:
            return self._raise(context, read, self.profile.pressure_size, "arena dry-board c-bet")

        if read.equity >= self.profile.value_equity:
            return self._raise(context, read, 0.68, "arena value pressure")

        return Action(action="check", reasoning=f"{self.label}: arena pot control equity={read.equity:.2f}")

    def _arena_river(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            if self._bad_large_price(context, read):
                return self._check_or_fold(context, f"arena river price fold equity={read.equity:.2f}")
            if read.opponent_aggression >= 2.0 and read.equity >= self.profile.maniac_call_equity:
                return Action(
                    action="call",
                    reasoning=f"{self.label}: arena river bluff-catch equity={read.equity:.2f}",
                )
            if should_call(read.equity, context.pot, context.to_call, margin=0.08):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: arena river priced call equity={read.equity:.2f}",
                )
            return self._check_or_fold(context, f"arena river fold equity={read.equity:.2f}")

        if read.equity >= self.profile.river_value_equity:
            return self._raise(context, read, 0.58, "arena river value")
        return Action(action="check", reasoning=f"{self.label}: arena river showdown control")

    def _bad_large_price(self, context: DecisionContext, read: PracticalRead) -> bool:
        large_price = context.to_call >= max(context.blind[1] * 6, int(context.my_stack * 0.18))
        return large_price and read.equity < self.profile.large_price_equity_cap

    def _is_affordable_steal_price(self, context: DecisionContext) -> bool:
        return context.to_call <= max(context.blind[1] * 5, context.pot // 2)

    def _is_late_position(self, context: DecisionContext) -> bool:
        return context.my_seat in {"btn", "co"}

    def _is_blind(self, context: DecisionContext) -> bool:
        return context.my_seat in {"sb", "bb"}

    def _is_river(self, context: DecisionContext) -> bool:
        return context.phase == "river" or len(context.community_cards) >= 5

    def _is_wet_board(self, read: PracticalRead) -> bool:
        return read.board.texture_score >= 0.55 or read.board.is_monotone or read.board.is_two_tone

    def _is_premium_broadway(self, context: DecisionContext) -> bool:
        ranks = sorted((_rank_value(card) for card in context.hole_cards), reverse=True)
        return len(ranks) == 2 and ranks[0] >= RANK_VALUES["A"] and ranks[1] >= RANK_VALUES["K"]

    def _is_broadway_pair_or_ace(self, context: DecisionContext) -> bool:
        ranks = [_rank_value(card) for card in context.hole_cards]
        if len(ranks) != 2:
            return False
        return (ranks[0] == ranks[1] and ranks[0] >= RANK_VALUES["T"]) or max(ranks) >= RANK_VALUES["A"]


def _rank_value(card: str) -> int:
    if not card:
        return 0
    return RANK_VALUES.get(card[0].upper(), 0)


class ArenaLCBDominator(ArenaStrategy):
    slug = "arena-lcb-dominator"
    label = "ArenaLCBDominator"
    profile = ArenaProfile()


class ArenaPressureConductor(ArenaStrategy):
    slug = "arena-pressure-conductor"
    label = "ArenaPressureConductor"
    profile = ArenaProfile(late_open_bonus=0.12, pressure_size=0.60, dry_cbet_equity=0.18)


class ArenaRiverLock(ArenaStrategy):
    slug = "arena-river-lock"
    label = "ArenaRiverLock"
    profile = ArenaProfile(large_price_equity_cap=0.70, river_value_equity=0.66, draw_call_margin=-0.03)


class ArenaDrawLeverager(ArenaStrategy):
    slug = "arena-draw-leverager"
    label = "ArenaDrawLeverager"
    profile = ArenaProfile(draw_call_margin=-0.06, combo_draw_equity=0.16, draw_size=0.86)


class ArenaShortstackCommander(ArenaStrategy):
    slug = "arena-shortstack-commander"
    label = "ArenaShortstackCommander"
    profile = ArenaProfile(short_stack_bb=22.0, short_open_equity=0.44, short_call_equity=0.52)


class ArenaBlindMatrix(ArenaStrategy):
    slug = "arena-blind-matrix"
    label = "ArenaBlindMatrix"
    profile = ArenaProfile(blind_defend_range=0.52, blind_call_equity=0.37, blind_resteal_equity=0.44)


class ArenaValueSiege(ArenaStrategy):
    slug = "arena-value-siege"
    label = "ArenaValueSiege"
    profile = ArenaProfile(wet_value_equity=0.58, value_equity=0.64, value_size=0.98)


class ArenaCounterpunchLCB(ArenaStrategy):
    slug = "arena-counterpunch-lcb"
    label = "ArenaCounterpunchLCB"
    profile = ArenaProfile(maniac_call_equity=0.48, large_price_equity_cap=0.68)


class ArenaFieldSynthesizer(ArenaStrategy):
    slug = "arena-field-synthesizer"
    label = "ArenaFieldSynthesizer"
    profile = ArenaProfile(
        late_open_bonus=0.10,
        squeeze_equity=0.43,
        blind_defend_range=0.50,
        short_stack_bb=20.0,
    )


class ArenaFinalTableHydra(ArenaStrategy):
    slug = "arena-final-table-hydra"
    label = "ArenaFinalTableHydra"
    profile = ArenaProfile(
        late_open_bonus=0.10,
        squeeze_equity=0.43,
        short_stack_bb=20.0,
        draw_call_margin=-0.05,
        wet_value_equity=0.58,
        large_price_equity_cap=0.68,
        pressure_size=0.62,
        value_size=0.94,
    )


ARENA_STRATEGIES: tuple[type[ArenaStrategy], ...] = (
    ArenaLCBDominator,
    ArenaPressureConductor,
    ArenaRiverLock,
    ArenaDrawLeverager,
    ArenaShortstackCommander,
    ArenaBlindMatrix,
    ArenaValueSiege,
    ArenaCounterpunchLCB,
    ArenaFieldSynthesizer,
    ArenaFinalTableHydra,
)
