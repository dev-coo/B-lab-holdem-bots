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
from holdem_agent.strategy.analysts.opponent import OpponentTracker
from holdem_agent.strategy.analysts.position import (
    position_advantage,
    position_range_adjustment,
    position_tier,
)
from holdem_agent.strategy.analysts.risk import is_allin_candidate
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.charts.preflop import get_3bet_range, get_call_range, get_open_range
from holdem_agent.strategy.charts.pushfold import get_call_range as get_pushfold_call_range
from holdem_agent.strategy.charts.pushfold import should_push
from holdem_agent.strategy.genome import StrategyGenome

_TIER_CALL_ADJUSTMENTS: dict[str, float] = {
    "late": -0.05,
    "middle": 0.0,
    "early": 0.05,
    "blinds": 0.02,
}


class HybridGTO(Strategy):
    """GTO baseline with opponent-adaptive exploitation and nuanced postflop play.

    Combines GTO-solid preflop (charts + position-aware ranges), opponent modeling
    (VPIP/AF per opponent), hand-type classification (premium/strong/draw/weak),
    draw-aware semi-bluffing, push/fold Nash equilibrium, and check-raise/donk-bet.
    """

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        self._genome = genome or self._default_genome()
        self._opponent_tracker = OpponentTracker()

    @property
    def name(self) -> str:
        return "hybrid-gto"

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "HybridGTO":
        return cls(genome=genome)

    def decide(self, context: DecisionContext) -> Action:
        self._update_opponents(context)
        equity = estimated_equity(context.hole_cards, context.community_cards)
        tier = position_tier(context.my_seat)
        zone = get_m_zone(context.my_stack, context.blind[0], context.blind[1])

        if is_push_fold(context.my_stack, context.blind[0], context.blind[1], threshold=self._genome.m_conservative):
            return self._push_fold(context, equity, zone)

        if context.phase == "preflop":
            return self._preflop(context, equity, tier)

        return self._postflop(context, equity, tier)

    def _preflop(self, context: DecisionContext, equity: float, tier: str) -> Action:
        open_range = get_open_range(context.my_seat)
        adj_open = position_range_adjustment(context.my_seat, open_range)
        in_open_range = hand_in_range(context.hole_cards, adj_open)

        raise_count = self._count_preflop_raises(context)
        opp_aggression = self._average_opponent_aggression()

        if raise_count >= 2:
            return self._facing_3bet(context, equity, tier)

        if raise_count == 1 and context.to_call > 0:
            return self._facing_raise(context, equity, tier, opp_aggression)

        if context.to_call == 0:
            if in_open_range:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: open {context.my_seat} equity={equity:.2f}")

            pos_adv = position_advantage(context.my_seat)
            if pos_adv > 0.7 and equity > 0.35 and random.random() < self._genome.bluff_frequency * 2:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: steal attempt {context.my_seat}")

            return Action(action="check", reasoning="HybridGTO: check")

        if in_open_range and should_raise(equity, context.pot, context.min_raise, self._genome.exploit_aggression):
            raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
            return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: iso-raise equity={equity:.2f}")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"HybridGTO: limp-call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"HybridGTO: fold preflop equity={equity:.2f}")

    def _facing_raise(self, context: DecisionContext, equity: float, tier: str, opp_aggression: float) -> Action:
        call_threshold = self._position_adjusted_call_threshold(context.my_seat, tier)
        threebet_range = get_3bet_range(context.my_seat)
        adj_3bet = position_range_adjustment(context.my_seat, threebet_range)
        in_3bet_range = hand_in_range(context.hole_cards, adj_3bet)

        if in_3bet_range and equity > 0.5:
            if opp_aggression > 1.5 and equity > 0.45:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.three_bet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: 3-bet vs aggro equity={equity:.2f} af={opp_aggression:.1f}")

            raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.three_bet_size_pot_fraction)
            return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: 3-bet equity={equity:.2f}")

        if opp_aggression < 0.6 and equity > 0.4:
            if random.random() < self._genome.bluff_frequency * 1.5:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.three_bet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: light 3-bet bluff vs tight af={opp_aggression:.1f}")

        call_range_val = get_call_range(context.my_seat)
        adj_call = position_range_adjustment(context.my_seat, call_range_val)
        in_call_range = hand_in_range(context.hole_cards, adj_call)

        if equity >= call_threshold and (in_call_range or equity > 0.55):
            if opp_aggression > 1.5 and equity > 0.65:
                return Action(action="call", reasoning=f"HybridGTO: trap vs aggro equity={equity:.2f}")
            return Action(action="call", reasoning=f"HybridGTO: call vs raise equity={equity:.2f}")

        return Action(action="fold", reasoning=f"HybridGTO: fold vs raise equity={equity:.2f}")

    def _facing_3bet(self, context: DecisionContext, equity: float, tier: str) -> Action:
        call_threshold = self._position_adjusted_call_threshold(context.my_seat, tier) + 0.10

        if equity > 0.6:
            if random.random() < self._genome.exploit_aggression * 0.3:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.three_bet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: 4-bet equity={equity:.2f}")
            return Action(action="call", reasoning=f"HybridGTO: call 3-bet equity={equity:.2f}")

        if equity >= call_threshold:
            return Action(action="call", reasoning=f"HybridGTO: defend 3-bet equity={equity:.2f}")

        return Action(action="fold", reasoning=f"HybridGTO: fold to 3-bet equity={equity:.2f}")

    def _postflop(self, context: DecisionContext, equity: float, tier: str) -> Action:
        hand_type = self._classify_hand(context, equity)
        opp_aggression = self._average_opponent_aggression()
        is_ip = position_advantage(context.my_seat) > 0.5

        match hand_type:
            case "premium":
                return self._play_premium(context, equity, opp_aggression, is_ip)
            case "strong":
                return self._play_strong(context, equity, opp_aggression, is_ip)
            case "draw":
                return self._play_draw(context, equity, opp_aggression, is_ip)
            case _:
                return self._play_weak(context, equity, opp_aggression, is_ip)

    def _classify_hand(self, context: DecisionContext, equity: float) -> str:
        has_flush = has_flush_draw(context.hole_cards, context.community_cards)
        has_straight = has_straight_draw(context.hole_cards, context.community_cards)

        if equity > 0.75:
            return "premium"
        if equity > 0.55:
            return "strong"
        if (has_flush or has_straight) and equity > 0.20:
            return "draw"
        if has_flush and has_straight and equity > 0.15:
            return "draw"
        return "weak"

    def _play_premium(self, context: DecisionContext, equity: float, opp_aggression: float, is_ip: bool) -> Action:
        if context.to_call == 0:
            fraction = self._genome.raise_size_pot_fraction
            if opp_aggression < 0.8:
                fraction = min(1.5, fraction * 1.25)

            if self._was_preflop_raiser(context) and random.random() < self._genome.check_raise_frequency:
                return Action(action="check", reasoning="HybridGTO: check-raise trap (premium)")

            raise_amt = raise_amount(equity, context.pot, context.min_raise, fraction)
            return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: value bet equity={equity:.2f}")

        if should_raise(equity, context.pot, context.min_raise, self._genome.exploit_aggression):
            raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
            return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: value raise equity={equity:.2f}")

        return Action(action="call", reasoning=f"HybridGTO: call with premium equity={equity:.2f}")

    def _play_strong(self, context: DecisionContext, equity: float, opp_aggression: float, is_ip: bool) -> Action:
        if context.to_call == 0:
            if self._was_preflop_raiser(context):
                if random.random() < self._genome.cbet_frequency:
                    raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                    return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: c-bet strong equity={equity:.2f}")
                return Action(action="check", reasoning="HybridGTO: check back strong")

            if not is_ip and random.random() < self._genome.donk_bet_frequency:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: donk bet strong equity={equity:.2f}")

            raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
            return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: bet strong equity={equity:.2f}")

        if opp_aggression > 1.5:
            if random.random() < self._genome.check_raise_frequency * 2:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: raise vs aggro equity={equity:.2f} af={opp_aggression:.1f}")
            if should_call(equity, context.pot, context.to_call):
                return Action(action="call", reasoning=f"HybridGTO: call vs aggro equity={equity:.2f}")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"HybridGTO: call strong equity={equity:.2f}")

        if context.to_call > context.pot * 0.5:
            return Action(action="fold", reasoning=f"HybridGTO: fold to big bet equity={equity:.2f}")

        return Action(action="call", reasoning=f"HybridGTO: peel strong equity={equity:.2f}")

    def _play_draw(self, context: DecisionContext, equity: float, opp_aggression: float, is_ip: bool) -> Action:
        has_flush = has_flush_draw(context.hole_cards, context.community_cards)
        has_straight = has_straight_draw(context.hole_cards, context.community_cards)
        is_combo_draw = has_flush and has_straight

        if is_combo_draw:
            if context.to_call == 0:
                raise_amt = raise_amount(equity + 0.15, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: combo draw semi-bluff")
            if should_call(equity, context.pot, context.to_call, margin=-0.05):
                return Action(action="call", reasoning=f"HybridGTO: combo draw call equity={equity:.2f}")
            if context.to_call <= context.my_stack * 0.1:
                return Action(action="call", reasoning="HybridGTO: combo draw peel")

        semi_bluff_threshold = self._genome.semi_bluff_equity_threshold

        if context.to_call == 0 and is_ip:
            if random.random() < self._genome.cbet_frequency * 0.7 and equity > semi_bluff_threshold:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                draw_type = "flush" if has_flush else "straight"
                return Action(action="raise", amount=raise_amt, reasoning=f"HybridGTO: semi-bluff IP {draw_type} draw")

        if context.to_call == 0 and not is_ip:
            if random.random() < self._genome.check_raise_frequency and equity > semi_bluff_threshold:
                return Action(action="check", reasoning="HybridGTO: check-raise draw trap")

        if should_call(equity, context.pot, context.to_call, margin=-0.03):
            return Action(action="call", reasoning=f"HybridGTO: draw call equity={equity:.2f}")

        if opp_aggression < 0.8 and context.to_call > 0 and equity > semi_bluff_threshold:
            if random.random() < self._genome.bluff_frequency:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: semi-bluff raise vs passive")

        if context.to_call == 0:
            return Action(action="check", reasoning="HybridGTO: check draw")

        return Action(action="fold", reasoning=f"HybridGTO: fold draw equity={equity:.2f}")

    def _play_weak(self, context: DecisionContext, equity: float, opp_aggression: float, is_ip: bool) -> Action:
        if context.to_call == 0:
            if self._was_preflop_raiser(context) and random.random() < self._genome.cbet_frequency * 0.5:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: c-bet bluff")

            if opp_aggression < 0.8 and random.random() < self._genome.bluff_frequency:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.cbet_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: bluff vs passive")

            if context.phase == "river" and random.random() < self._genome.river_bluff_frequency:
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: river bluff")

            return Action(action="check", reasoning="HybridGTO: check weak")

        if opp_aggression > 1.5:
            if random.random() < self._genome.check_raise_frequency * 0.5 and context.phase in ("flop", "turn"):
                raise_amt = raise_amount(equity, context.pot, context.min_raise, self._genome.raise_size_pot_fraction)
                return Action(action="raise", amount=raise_amt, reasoning="HybridGTO: bluff raise vs aggro")

        if should_call(equity, context.pot, context.to_call):
            return Action(action="call", reasoning=f"HybridGTO: call weak equity={equity:.2f}")

        return Action(action="fold", reasoning=f"HybridGTO: fold weak equity={equity:.2f}")

    def _push_fold(self, context: DecisionContext, equity: float, zone: str) -> Action:
        bb_count = context.my_stack / context.blind[1] if context.blind[1] > 0 else 999

        if bb_count <= 10:
            if context.to_call == 0:
                if should_push(context.hole_cards, bb_count):
                    return Action(action="allin", reasoning=f"HybridGTO: {zone} Nash push")
                return Action(action="check", reasoning=f"HybridGTO: {zone} check-fold")

            if should_push(context.hole_cards, bb_count):
                effective_bb = context.my_stack / context.blind[1]
                call_range_pct = get_pushfold_call_range(effective_bb)
                if hand_in_range(context.hole_cards, call_range_pct):
                    return Action(action="allin", reasoning=f"HybridGTO: {zone} Nash call push")

            if context.to_call == 0:
                return Action(action="check", reasoning=f"HybridGTO: {zone} check-fold")
            return Action(action="fold", reasoning=f"HybridGTO: {zone} Nash fold")

        if is_allin_candidate(context.my_stack, context.blind[1], equity):
            return Action(action="allin", reasoning=f"HybridGTO: {zone} allin equity={equity:.2f}")

        if context.to_call == 0:
            return Action(action="check", reasoning=f"HybridGTO: {zone} push-fold check")

        if equity > 0.4 and context.to_call <= context.my_stack * 0.3:
            return Action(action="call", reasoning=f"HybridGTO: {zone} desperate call equity={equity:.2f}")

        return Action(action="fold", reasoning=f"HybridGTO: {zone} fold equity={equity:.2f}")

    @property
    def opponent_tracker(self) -> OpponentTracker:
        return self._opponent_tracker

    def _update_opponents(self, context: DecisionContext) -> None:
        for action in context.action_history:
            self._opponent_tracker.record_action(action.player, action.action, action.phase)

    def _average_opponent_aggression(self) -> float:
        profiles = self._opponent_tracker.all_profiles
        if not profiles:
            return 1.0
        return sum(p.aggression_factor for p in profiles.values()) / len(profiles)

    def _get_opponent_style(self, player_name: str) -> str:
        profile = self._opponent_tracker.get_profile(player_name)
        if profile is None or profile.hands_played < 3:
            return "unknown"
        return profile.classify()

    def _count_preflop_raises(self, context: DecisionContext) -> int:
        return sum(1 for a in context.action_history if a.phase == "preflop" and a.action == "raise")

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

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            preflop_raise_threshold={
                "btn": 0.38, "co": 0.35, "hj": 0.40,
                "mp": 0.45, "utg": 0.50, "sb": 0.40, "bb": 0.48,
            },
            preflop_call_threshold={
                "btn": 0.52, "co": 0.55, "hj": 0.58,
                "mp": 0.60, "utg": 0.65, "sb": 0.55, "bb": 0.50,
            },
            preflop_3bet_threshold={
                "btn": 0.12, "co": 0.10, "hj": 0.08,
                "mp": 0.07, "utg": 0.05, "sb": 0.08, "bb": 0.07,
            },
            cbet_frequency=0.65,
            cbet_size_pot_fraction=0.55,
            raise_size_pot_fraction=0.85,
            three_bet_size_pot_fraction=1.0,
            bluff_frequency=0.12,
            semi_bluff_equity_threshold=0.25,
            river_bluff_frequency=0.06,
            fold_to_raise_equity=0.25,
            check_raise_frequency=0.10,
            donk_bet_frequency=0.08,
            m_conservative=15.0,
            m_desperate=5.0,
            exploit_aggression=0.6,
            adapt_speed=0.10,
        )