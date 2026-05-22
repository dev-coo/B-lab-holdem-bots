from __future__ import annotations

import dataclasses
import random

from holdem_agent.strategy.analysts.blockers import BlockerAnalysis, analyze_blockers
from holdem_agent.strategy.analysts.board_texture import BoardTextureAnalysis, analyze_board_texture
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
from holdem_agent.strategy.analysts.image import SelfImageAnalysis, analyze_self_image
from holdem_agent.strategy.analysts.position import position_advantage, position_tier
from holdem_agent.strategy.analysts.spr import SPRAnalysis, analyze_spr
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.hybrid_gto import HybridGTO
from holdem_agent.strategy.genome import StrategyGenome


@dataclasses.dataclass(frozen=True)
class OmniAnalysis:
    """One decision snapshot combining all Omni analyst outputs."""

    board: BoardTextureAnalysis
    blockers: BlockerAnalysis
    spr: SPRAnalysis
    image: SelfImageAnalysis


class OmniStrategy(HybridGTO):
    """Hybrid-GTO architecture enhanced with texture, blockers, SPR, and self-image.

    Omni starts from HybridGTO's chart/range/opponent/risk framework, then adjusts
    c-bets, bluffs, value sizing, and commitment thresholds with board texture,
    nut blockers, stack-to-pot ratio, and our perceived table image.
    """

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        super().__init__(genome=genome or self._default_genome())

    @property
    def name(self) -> str:
        return "omni"

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "OmniStrategy":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        self._update_opponents(context)
        equity = estimated_equity(context.hole_cards, context.community_cards)
        tier = position_tier(context.my_seat)
        zone = get_m_zone(context.my_stack, context.blind[0], context.blind[1])
        analysis = self._analyze(context)

        if is_push_fold(context.my_stack, context.blind[0], context.blind[1], threshold=self.genome.m_conservative):
            return self._brand_action(super()._push_fold(context, equity, zone))

        if context.phase == "preflop":
            return self._preflop_omni(context, equity, tier, analysis)

        return self._postflop_omni(context, equity, tier, analysis)

    def _analyze(self, context: DecisionContext) -> OmniAnalysis:
        hero_names = self._hero_names(context)
        return OmniAnalysis(
            board=analyze_board_texture(context.community_cards),
            blockers=analyze_blockers(context.hole_cards, context.community_cards),
            spr=analyze_spr(context.my_stack, context.pot),
            image=analyze_self_image(
                context.action_history,
                hero_names if hero_names else {"__omni_hero__"},
            ),
        )

    def _preflop_omni(
        self,
        context: DecisionContext,
        equity: float,
        tier: str,
        analysis: OmniAnalysis,
    ) -> Action:
        adjusted_equity = min(
            1.0,
            equity + (analysis.blockers.blocker_score * 0.04) + analysis.image.bluff_success_bonus,
        )
        base_action = self._brand_action(super()._preflop(context, adjusted_equity, tier))

        if base_action.action not in {"check", "fold"}:
            return base_action

        bluff_frequency = self._adjusted_bluff_frequency(analysis)
        late_position = position_advantage(context.my_seat) >= 0.70
        can_apply_pressure = analysis.blockers.blocks_ace_high and late_position

        if context.to_call == 0 and can_apply_pressure and random.random() < bluff_frequency:
            amount = raise_amount(adjusted_equity, context.pot, context.min_raise, self.genome.raise_size_pot_fraction)
            return Action(
                action="raise",
                amount=amount,
                reasoning="Omni: ace-blocker position steal",
            )

        opp_aggression = self._average_opponent_aggression()
        if context.to_call > 0 and opp_aggression < 0.8 and analysis.blockers.blocker_score >= 0.50:
            if random.random() < bluff_frequency * 0.8:
                amount = raise_amount(
                    adjusted_equity,
                    context.pot,
                    context.min_raise,
                    self.genome.three_bet_size_pot_fraction,
                )
                return Action(
                    action="raise",
                    amount=amount,
                    reasoning="Omni: blocker squeeze vs passive range",
                )

        return base_action

    def _postflop_omni(
        self,
        context: DecisionContext,
        equity: float,
        tier: str,
        analysis: OmniAnalysis,
    ) -> Action:
        hand_type = self._classify_hand(context, equity)
        opp_aggression = self._average_opponent_aggression()
        is_ip = position_advantage(context.my_seat) > 0.5

        match hand_type:
            case "premium":
                return self._play_premium_omni(context, equity, opp_aggression, is_ip, analysis)
            case "strong":
                return self._play_strong_omni(context, equity, opp_aggression, is_ip, analysis)
            case "draw":
                return self._play_draw_omni(context, equity, opp_aggression, is_ip, analysis)
            case _:
                return self._play_weak_omni(context, equity, opp_aggression, is_ip, analysis)

    def _play_premium_omni(
        self,
        context: DecisionContext,
        equity: float,
        opp_aggression: float,
        is_ip: bool,
        analysis: OmniAnalysis,
    ) -> Action:
        if self._should_commit(context, equity, analysis):
            return Action(action="allin", reasoning=f"Omni: low-SPR premium commit equity={equity:.2f}")

        fraction = self._value_fraction(self.genome.raise_size_pot_fraction, analysis)
        if opp_aggression < 0.8:
            fraction = min(1.5, fraction * 1.15)
        if not is_ip and analysis.board.texture_score > 0.65:
            fraction = min(1.5, fraction * 1.10)

        if context.to_call == 0:
            amount = raise_amount(equity, context.pot, context.min_raise, fraction)
            return Action(action="raise", amount=amount, reasoning=f"Omni: value bet equity={equity:.2f}")

        if should_raise(equity, context.pot, context.min_raise, self.genome.exploit_aggression):
            amount = raise_amount(equity, context.pot, context.min_raise, fraction)
            return Action(action="raise", amount=amount, reasoning=f"Omni: value raise equity={equity:.2f}")

        return Action(action="call", reasoning=f"Omni: premium pot-control equity={equity:.2f}")

    def _play_strong_omni(
        self,
        context: DecisionContext,
        equity: float,
        opp_aggression: float,
        is_ip: bool,
        analysis: OmniAnalysis,
    ) -> Action:
        if self._should_commit(context, equity, analysis):
            return Action(action="allin", reasoning=f"Omni: low-SPR strong commit equity={equity:.2f}")

        cbet_frequency = self._adjusted_cbet_frequency(analysis)
        value_fraction = self._value_fraction(self.genome.cbet_size_pot_fraction, analysis)

        if context.to_call == 0:
            if self._was_preflop_raiser(context) and random.random() > cbet_frequency:
                return Action(action="check", reasoning="Omni: texture-aware check back strong")
            if not is_ip and random.random() < self.genome.donk_bet_frequency:
                amount = raise_amount(equity, context.pot, context.min_raise, value_fraction)
                return Action(action="raise", amount=amount, reasoning="Omni: donk bet strong")
            amount = raise_amount(equity, context.pot, context.min_raise, value_fraction)
            return Action(action="raise", amount=amount, reasoning=f"Omni: bet strong equity={equity:.2f}")

        margin = 0.01 if analysis.spr.category == "low" else 0.04
        if opp_aggression > 1.5 and equity > analysis.spr.commitment_threshold:
            amount = raise_amount(equity, context.pot, context.min_raise, self.genome.raise_size_pot_fraction)
            return Action(action="raise", amount=amount, reasoning="Omni: raise strong vs aggro")
        if should_call(equity, context.pot, context.to_call, margin=margin):
            return Action(action="call", reasoning=f"Omni: call strong equity={equity:.2f}")

        return Action(action="fold", reasoning=f"Omni: fold strong below SPR threshold equity={equity:.2f}")

    def _play_draw_omni(
        self,
        context: DecisionContext,
        equity: float,
        opp_aggression: float,
        is_ip: bool,
        analysis: OmniAnalysis,
    ) -> Action:
        has_flush = has_flush_draw(context.hole_cards, context.community_cards)
        has_straight = has_straight_draw(context.hole_cards, context.community_cards)
        is_combo_draw = has_flush and has_straight
        effective_equity = min(1.0, equity + (analysis.blockers.blocker_score * 0.06))
        semi_bluff_threshold = max(
            0.15,
            self.genome.semi_bluff_equity_threshold - (analysis.blockers.blocker_score * 0.05),
        )

        if analysis.spr.prefer_push_fold and context.to_call > 0:
            if is_combo_draw and effective_equity >= analysis.spr.commitment_threshold:
                return Action(action="allin", reasoning="Omni: combo draw low-SPR shove")
            return Action(action="fold", reasoning="Omni: low-SPR avoid speculative draw call")

        if context.to_call == 0:
            pressure_frequency = self._adjusted_cbet_frequency(analysis)
            if effective_equity > semi_bluff_threshold and random.random() < pressure_frequency:
                amount = raise_amount(effective_equity, context.pot, context.min_raise, self.genome.cbet_size_pot_fraction)
                draw_type = "combo" if is_combo_draw else "flush" if has_flush else "straight"
                return Action(action="raise", amount=amount, reasoning=f"Omni: {draw_type} draw semi-bluff")
            return Action(action="check", reasoning="Omni: check draw on poor bluff texture")

        draw_margin = analysis.spr.draw_call_margin
        if should_call(effective_equity, context.pot, context.to_call, margin=draw_margin):
            return Action(action="call", reasoning=f"Omni: draw call equity={effective_equity:.2f}")

        if opp_aggression < 0.8 and effective_equity > semi_bluff_threshold:
            if random.random() < self._adjusted_bluff_frequency(analysis):
                amount = raise_amount(effective_equity, context.pot, context.min_raise, self.genome.raise_size_pot_fraction)
                return Action(action="raise", amount=amount, reasoning="Omni: blocker semi-bluff raise")

        return Action(action="fold", reasoning=f"Omni: fold draw equity={effective_equity:.2f}")

    def _play_weak_omni(
        self,
        context: DecisionContext,
        equity: float,
        opp_aggression: float,
        is_ip: bool,
        analysis: OmniAnalysis,
    ) -> Action:
        bluff_frequency = self._adjusted_bluff_frequency(analysis)
        cbet_frequency = self._adjusted_cbet_frequency(analysis) * 0.65
        credible_bluff = analysis.blockers.blocker_score >= 0.45 or analysis.image.image == "tight"

        if context.to_call == 0:
            if self._was_preflop_raiser(context) and random.random() < cbet_frequency:
                amount = raise_amount(equity, context.pot, context.min_raise, self.genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=amount, reasoning="Omni: texture-aware c-bet bluff")

            if credible_bluff and random.random() < bluff_frequency:
                amount = raise_amount(equity, context.pot, context.min_raise, self.genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=amount, reasoning="Omni: blocker/image bluff")

            if context.phase == "river" and analysis.blockers.blocker_score >= 0.50:
                if random.random() < self.genome.river_bluff_frequency + analysis.image.bluff_success_bonus:
                    amount = raise_amount(equity, context.pot, context.min_raise, self.genome.raise_size_pot_fraction)
                    return Action(action="raise", amount=amount, reasoning="Omni: river nut-blocker bluff")

            return Action(action="check", reasoning="Omni: check weak")

        if analysis.spr.prefer_push_fold:
            return Action(action="fold", reasoning="Omni: low-SPR fold weak hand")

        if opp_aggression < 0.8 and credible_bluff and random.random() < bluff_frequency * 0.7:
            amount = raise_amount(equity, context.pot, context.min_raise, self.genome.raise_size_pot_fraction)
            return Action(action="raise", amount=amount, reasoning="Omni: pressure passive capped range")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"Omni: call weak with price equity={equity:.2f}")

        return Action(action="fold", reasoning=f"Omni: fold weak equity={equity:.2f}")

    def _adjusted_cbet_frequency(self, analysis: OmniAnalysis) -> float:
        texture_adjustment = (0.50 - analysis.board.texture_score) * 0.25
        blocker_adjustment = analysis.blockers.blocker_score * 0.10
        return self._clamp_probability(
            self.genome.cbet_frequency
            + texture_adjustment
            + blocker_adjustment
            + analysis.image.bluff_success_bonus,
        )

    def _adjusted_bluff_frequency(self, analysis: OmniAnalysis) -> float:
        dry_board_bonus = max(0.0, 0.45 - analysis.board.texture_score) * 0.12
        blocker_bonus = analysis.blockers.blocker_score * 0.18
        return self._clamp_probability(
            self.genome.bluff_frequency
            + dry_board_bonus
            + blocker_bonus
            + analysis.image.bluff_success_bonus,
        )

    def _value_fraction(self, base_fraction: float, analysis: OmniAnalysis) -> float:
        wet_board_bonus = analysis.board.texture_score * 0.12
        return max(0.35, min(1.8, (base_fraction + wet_board_bonus) * analysis.image.value_size_multiplier))

    def _should_commit(self, context: DecisionContext, equity: float, analysis: OmniAnalysis) -> bool:
        if not analysis.spr.prefer_push_fold:
            return False
        if context.to_call == 0:
            return False
        return equity >= analysis.spr.commitment_threshold

    def _brand_action(self, action: Action) -> Action:
        if action.reasoning.startswith("Omni"):
            return action
        reasoning = action.reasoning.replace("HybridGTO", "Omni", 1) if action.reasoning else "Omni"
        return Action(
            action=action.action,
            amount=action.amount,
            reasoning=reasoning,
            strategy_name=action.strategy_name,
        )

    def _hero_names(self, context: DecisionContext) -> set[str]:
        return {player.name for player in context.players if player.position == context.my_seat}

    @staticmethod
    def _clamp_probability(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            preflop_raise_threshold={
                "btn": 0.36, "co": 0.34, "hj": 0.39,
                "mp": 0.44, "utg": 0.50, "sb": 0.39, "bb": 0.47,
            },
            preflop_call_threshold={
                "btn": 0.50, "co": 0.53, "hj": 0.57,
                "mp": 0.60, "utg": 0.65, "sb": 0.54, "bb": 0.49,
            },
            preflop_3bet_threshold={
                "btn": 0.13, "co": 0.11, "hj": 0.09,
                "mp": 0.08, "utg": 0.05, "sb": 0.09, "bb": 0.08,
            },
            cbet_frequency=0.68,
            cbet_size_pot_fraction=0.58,
            raise_size_pot_fraction=0.90,
            three_bet_size_pot_fraction=1.05,
            bluff_frequency=0.14,
            semi_bluff_equity_threshold=0.24,
            river_bluff_frequency=0.07,
            fold_to_raise_equity=0.25,
            check_raise_frequency=0.11,
            donk_bet_frequency=0.09,
            m_conservative=15.0,
            m_desperate=5.0,
            exploit_aggression=0.65,
            adapt_speed=0.12,
        )
