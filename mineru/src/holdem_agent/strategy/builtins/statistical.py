from __future__ import annotations

import dataclasses
import math
from typing import ClassVar

from holdem_agent.core.range_ import hand_in_range
from holdem_agent.strategy.analysts.equity_calc import should_call
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.practical import PracticalRead, PracticalStrategy
from holdem_agent.strategy.charts.preflop import get_open_range
from holdem_agent.strategy.charts.pushfold import should_call_push, should_push
from holdem_agent.strategy.genome import StrategyGenome

_VOLUNTARY_ACTIONS = {"call", "raise", "bet", "allin"}
_AGGRESSIVE_ACTIONS = {"raise", "bet", "allin"}
_ROBUST_STYLES = ("overfolder", "nit", "calling-station", "maniac", "balanced")


@dataclasses.dataclass
class BayesianOpponentProfile:
    """Bayesian-smoothed opponent tendencies accumulated across hands."""

    name: str
    hands_seen: int = 0
    vpip_count: int = 0
    pfr_count: int = 0
    aggressive_count: int = 0
    call_count: int = 0
    fold_count: int = 0
    check_count: int = 0
    total_actions: int = 0

    @property
    def vpip(self) -> float:
        return (self.vpip_count + 1.5) / (self.hands_seen + 4.0)

    @property
    def pfr(self) -> float:
        return (self.pfr_count + 0.8) / (self.hands_seen + 4.0)

    @property
    def aggression(self) -> float:
        return (self.aggressive_count + 1.0) / (self.call_count + 1.0)

    @property
    def fold_rate(self) -> float:
        opportunities = self.fold_count + self.call_count + self.aggressive_count + self.check_count
        return (self.fold_count + 1.0) / (opportunities + 4.0)

    @property
    def call_rate(self) -> float:
        opportunities = self.fold_count + self.call_count + self.aggressive_count + self.check_count
        return (self.call_count + 1.0) / (opportunities + 4.0)

    @property
    def action_opportunities(self) -> int:
        return self.fold_count + self.call_count + self.aggressive_count + self.check_count

    @property
    def aggressive_rate(self) -> float:
        return (self.aggressive_count + 1.0) / (self.action_opportunities + 4.0)

    @property
    def vpip_lcb(self) -> float:
        return _wilson_lower_bound(self.vpip_count, self.hands_seen)

    @property
    def pfr_lcb(self) -> float:
        return _wilson_lower_bound(self.pfr_count, self.hands_seen)

    @property
    def fold_lcb(self) -> float:
        return _wilson_lower_bound(self.fold_count, self.action_opportunities)

    @property
    def call_lcb(self) -> float:
        return _wilson_lower_bound(self.call_count, self.action_opportunities)

    @property
    def aggressive_lcb(self) -> float:
        return _wilson_lower_bound(self.aggressive_count, self.action_opportunities)

    @property
    def confidence(self) -> float:
        hand_signal = min(1.0, self.hands_seen / 8.0)
        action_signal = min(1.0, self.total_actions / 24.0)
        return max(hand_signal, action_signal)

    def classify(self) -> str:
        if self.confidence < 0.20:
            return "unknown"
        if self.aggression >= 2.2 or self.pfr >= 0.36:
            return "maniac"
        if self.vpip >= 0.42 and self.call_rate >= 0.34 and self.aggression <= 1.45:
            return "calling-station"
        if self.fold_rate >= 0.42 and self.aggression <= 1.30:
            return "overfolder"
        if self.vpip <= 0.26 and self.pfr <= 0.14:
            return "nit"
        return "balanced"


@dataclasses.dataclass(frozen=True)
class TableExploitRead:
    """Aggregate exploit signal for the current decision."""

    style: str
    confidence: float
    vpip: float
    pfr: float
    aggression: float
    fold_rate: float
    call_rate: float
    overfolder_share: float = 0.0
    nit_share: float = 0.0
    station_share: float = 0.0
    maniac_share: float = 0.0
    balanced_share: float = 0.0
    diversity_score: float = 0.0


_UNKNOWN_TABLE_READ = TableExploitRead(
    style="unknown",
    confidence=0.0,
    vpip=0.38,
    pfr=0.20,
    aggression=1.0,
    fold_rate=0.25,
    call_rate=0.25,
)


def _wilson_lower_bound(successes: int, total: int, z_score: float = 1.28) -> float:
    if total <= 0:
        return 0.0

    p_hat = successes / total
    z_squared = z_score * z_score
    denominator = 1.0 + z_squared / total
    center = p_hat + z_squared / (2.0 * total)
    margin = z_score * math.sqrt((p_hat * (1.0 - p_hat) + z_squared / (4.0 * total)) / total)
    return max(0.0, (center - margin) / denominator)


class StatisticalLCBFusion(PracticalStrategy):
    """LCB-oriented candidate built from the current local/live evidence.

    Evidence used for the design:
    - live 100-game pivot summary: `omni` leads by composite LCB, with
      `hybrid-gto`/`gto-baseline` next; this argues for lower-variance,
      equity-realization decisions as the default live prior.
    - local benchmark artifacts: `dominance-adaptive-conductor` has the best
      local score and smallest reported standard error; this argues for keeping
      its clear tactical edges in short-stack, squeeze, draw, river, and
      wet-board spots.

    The resulting policy is deterministic and conservative in marginal pots:
    take the local tactical edges when they are explicit, otherwise choose the
    lower-confidence-bound-friendly action of realizing equity, protecting clear
    value, and folding large bad prices.
    """

    slug: ClassVar[str] = "statistical-lcb-fusion"
    label: ClassVar[str] = "StatisticalLCBFusion"

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.64,
            cbet_size_pot_fraction=0.58,
            raise_size_pot_fraction=0.78,
            three_bet_size_pot_fraction=1.12,
            bluff_frequency=0.08,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.02,
            fold_to_raise_equity=0.30,
            check_raise_frequency=0.05,
            donk_bet_frequency=0.03,
            m_conservative=14.0,
            m_desperate=4.5,
            exploit_aggression=0.58,
            adapt_speed=0.12,
        )

    def _is_push_fold_spot(self, context: DecisionContext, read: PracticalRead) -> bool:
        return read.big_blinds <= 18.0

    def _short_stack(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call == 0:
            equity_gate = 0.45 if read.big_blinds <= 10.0 else 0.52
            if should_push(context.hole_cards, read.big_blinds) or read.equity >= equity_gate:
                return Action(action="allin", reasoning=f"{self.label}: LCB short-stack shove")
            return self._check_or_fold(context, f"LCB short-stack pass equity={read.equity:.2f}")

        equity_gate = 0.52 if read.big_blinds <= 10.0 else 0.58
        if should_call_push(context.hole_cards, read.big_blinds) or read.equity >= equity_gate:
            return Action(action="allin", reasoning=f"{self.label}: LCB short-stack call-off")
        return self._check_or_fold(context, f"LCB short-stack fold equity={read.equity:.2f}")

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            return self._preflop_facing_price(context, read)

        if self._is_late_position(context):
            open_range = min(1.0, get_open_range(context.my_seat) + 0.08)
            if (
                read.equity >= 0.36
                or read.blockers.blocks_ace_high
                or hand_in_range(context.hole_cards, open_range)
            ):
                return self._raise(context, read, 0.72, "LCB late-position pressure")

        if self._is_blind(context) and read.equity >= 0.48:
            return self._raise(context, read, 0.64, "LCB blind initiative")

        if read.equity >= 0.56:
            return self._raise(context, read, 0.70, "LCB value open")

        return self._check_or_fold(context, f"LCB pass preflop equity={read.equity:.2f}")

    def _preflop_facing_price(self, context: DecisionContext, read: PracticalRead) -> Action:
        squeeze_spot = read.preflop_raise_count >= 1 and read.preflop_call_count >= 1
        if squeeze_spot and (read.blockers.blocks_ace_high or read.equity >= 0.46):
            return self._raise(context, read, 1.18, "LCB blocker squeeze")

        if self._is_blind(context) and self._is_affordable_steal_price(context):
            if read.blockers.blocks_ace_high and read.equity >= 0.38:
                return self._raise(context, read, 1.02, "LCB blind resteal")
            defend_range = 0.46 if context.my_seat == "bb" else 0.34
            if hand_in_range(context.hole_cards, defend_range) or read.equity >= 0.40:
                return Action(action="call", reasoning=f"{self.label}: LCB blind defend equity={read.equity:.2f}")

        if self._bad_large_price(context, read, equity_cap=0.60):
            return self._check_or_fold(context, f"LCB preflop price fold equity={read.equity:.2f}")

        if read.opponent_aggression >= 2.0 and read.equity >= 0.53:
            return Action(action="call", reasoning=f"{self.label}: LCB trap aggression equity={read.equity:.2f}")

        if read.equity >= 0.58 or should_call(read.equity, context.pot, context.to_call, margin=0.02):
            return Action(action="call", reasoning=f"{self.label}: LCB priced defend equity={read.equity:.2f}")

        return self._check_or_fold(context, f"LCB preflop fold equity={read.equity:.2f}")

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        if self._is_river(context):
            return self._river(context, read)

        if read.opponent_aggression >= 2.0:
            counter = self._counter_aggression(context, read)
            if counter is not None:
                return counter

        if read.has_draw:
            draw_action = self._draw(context, read)
            if draw_action is not None:
                return draw_action

        wet = read.board.texture_score >= 0.55 or read.board.is_monotone or read.board.is_two_tone
        if read.equity >= 0.72 or (wet and read.equity >= 0.62):
            return self._raise(context, read, 0.90 if wet else 0.68, "LCB value/protection")

        if context.to_call == 0:
            if self._is_late_position(context) and read.board.texture_score <= 0.50 and read.equity >= 0.20:
                return self._raise(context, read, 0.52, "LCB dry-board c-bet")
            if read.equity >= 0.58:
                return self._raise(context, read, 0.56, "LCB thin value")
            return Action(action="check", reasoning=f"{self.label}: LCB pot control equity={read.equity:.2f}")

        if self._bad_large_price(context, read, equity_cap=0.64):
            return self._check_or_fold(context, f"LCB large-price fold equity={read.equity:.2f}")

        if should_call(read.equity, context.pot, context.to_call, margin=0.04):
            return Action(action="call", reasoning=f"{self.label}: LCB priced call equity={read.equity:.2f}")

        return self._check_or_fold(context, f"LCB postflop fold equity={read.equity:.2f}")

    def _river(self, context: DecisionContext, read: PracticalRead) -> Action:
        if context.to_call > 0:
            if self._bad_large_price(context, read, equity_cap=0.66):
                return self._check_or_fold(context, f"LCB river price fold equity={read.equity:.2f}")
            if should_call(read.equity, context.pot, context.to_call, margin=0.08):
                return Action(action="call", reasoning=f"{self.label}: LCB river catch equity={read.equity:.2f}")
            return self._check_or_fold(context, f"LCB river no-price fold equity={read.equity:.2f}")

        if read.equity >= 0.64:
            return self._raise(context, read, 0.58, "LCB river value")
        return Action(action="check", reasoning=f"{self.label}: LCB river showdown control")

    def _counter_aggression(self, context: DecisionContext, read: PracticalRead) -> Action | None:
        if context.to_call > 0:
            if read.equity >= 0.52:
                return Action(action="call", reasoning=f"{self.label}: LCB bluff-catch equity={read.equity:.2f}")
            if read.equity < 0.45:
                return self._check_or_fold(context, f"LCB avoid bluff war equity={read.equity:.2f}")
            return None

        if read.equity >= 0.66:
            return self._raise(context, read, 0.64, "LCB counter value")
        return None

    def _draw(self, context: DecisionContext, read: PracticalRead) -> Action | None:
        if context.to_call > 0:
            margin = read.spr.draw_call_margin - 0.04
            if should_call(read.equity, context.pot, context.to_call, margin=margin):
                return Action(action="call", reasoning=f"{self.label}: LCB draw price equity={read.equity:.2f}")
            if read.has_combo_draw and read.spr.category != "high" and read.equity >= 0.30:
                return self._raise(context, read, 0.82, "LCB combo draw pressure")
            return self._check_or_fold(context, f"LCB unpriced draw fold equity={read.equity:.2f}")

        if read.has_combo_draw and read.equity >= 0.18:
            return self._raise(context, read, 0.86, "LCB combo draw pressure")

        if read.equity >= self.genome.semi_bluff_equity_threshold or read.blockers.blocker_score >= 0.35:
            return self._raise(context, read, 0.58, "LCB blocker draw pressure")

        return Action(action="check", reasoning=f"{self.label}: LCB draw pot control")

    def _bad_large_price(self, context: DecisionContext, read: PracticalRead, equity_cap: float) -> bool:
        return context.to_call > max(context.blind[1] * 6, int(context.my_stack * 0.18)) and read.equity < equity_cap

    def _is_late_position(self, context: DecisionContext) -> bool:
        return context.my_seat in {"btn", "co"}

    def _is_blind(self, context: DecisionContext) -> bool:
        return context.my_seat in {"sb", "bb"}

    def _is_river(self, context: DecisionContext) -> bool:
        return context.phase == "river" or len(context.community_cards) >= 5

    def _is_affordable_steal_price(self, context: DecisionContext) -> bool:
        return context.to_call <= max(context.blind[1] * 5, context.pot // 2)


class BayesianExploit(StatisticalLCBFusion):
    """Opponent-model strategy using smoothed live statistics before exploiting.

    It keeps the low-variance StatisticalLCBFusion fallback, then shifts policy
    only when the accumulated opponent sample is strong enough to identify a
    reliable leak: overfolding, calling too much, or excess aggression.
    """

    slug: ClassVar[str] = "bayesian-exploit"
    label: ClassVar[str] = "BayesianExploit"

    def __init__(self, genome: StrategyGenome | None = None) -> None:
        super().__init__(genome=genome)
        self._profiles: dict[str, BayesianOpponentProfile] = {}
        self._seen_actions: set[tuple[int, int, int, str, str, str, int]] = set()
        self._seen_player_hands: set[tuple[int, int, str]] = set()
        self._table_read = _UNKNOWN_TABLE_READ

    @property
    def opponent_profiles(self) -> dict[str, BayesianOpponentProfile]:
        return dict(self._profiles)

    def decide(self, context: DecisionContext) -> Action:
        self._observe(context)
        self._table_read = self._build_table_read(context)
        return super().decide(context)

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.66,
            cbet_size_pot_fraction=0.60,
            raise_size_pot_fraction=0.88,
            three_bet_size_pot_fraction=1.16,
            bluff_frequency=0.10,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.04,
            fold_to_raise_equity=0.28,
            check_raise_frequency=0.08,
            donk_bet_frequency=0.05,
            m_conservative=15.0,
            m_desperate=4.5,
            exploit_aggression=0.68,
            adapt_speed=0.18,
        )

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        if table.confidence < 0.20:
            return super()._preflop(context, read)

        if table.style in {"overfolder", "nit"}:
            action = self._attack_overfolding_preflop(context, read, table)
            if action is not None:
                return action

        if table.style == "calling-station":
            action = self._value_target_station_preflop(context, read, table)
            if action is not None:
                return action

        if table.style == "maniac":
            action = self._counter_maniac_preflop(context, read, table)
            if action is not None:
                return action

        return super()._preflop(context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        if table.confidence < 0.20:
            return super()._postflop(context, read)

        if table.style == "calling-station":
            action = self._value_target_station_postflop(context, read, table)
            if action is not None:
                return action

        if table.style == "maniac":
            action = self._counter_maniac_postflop(context, read, table)
            if action is not None:
                return action

        if table.style in {"overfolder", "nit"}:
            action = self._attack_overfolding_postflop(context, read, table)
            if action is not None:
                return action

        return super()._postflop(context, read)

    def _attack_overfolding_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        late_or_blind = context.my_seat in {"btn", "co", "sb"}
        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.42
        confidence_bonus = table.confidence * 0.04

        if context.to_call == 0 and late_or_blind:
            open_range = get_open_range(context.my_seat) + 0.10 + confidence_bonus
            if hand_in_range(context.hole_cards, open_range) or read.equity >= 0.32 or blocker_pressure:
                return self._raise(context, read, 0.64, f"bayesian steal vs {table.style}")

        if context.to_call > 0 and blocker_pressure and read.equity >= 0.36:
            affordable = context.to_call <= max(context.blind[1] * 6, context.pot)
            if affordable:
                return self._raise(context, read, 1.08, f"bayesian resteal vs {table.style}")

        return None

    def _value_target_station_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        if context.to_call == 0 and read.equity >= 0.50:
            return self._raise(context, read, 0.92, "bayesian value open vs station")

        if context.to_call > 0:
            if read.equity >= 0.58:
                return self._raise(context, read, 1.18, "bayesian value isolate station")
            if read.equity >= 0.44 and should_call(read.equity, context.pot, context.to_call, margin=0.03):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: priced station defend equity={read.equity:.2f}",
                )
            if read.equity < 0.42 and table.call_rate >= 0.38:
                return self._check_or_fold(context, f"skip bluff vs station equity={read.equity:.2f}")

        return None

    def _counter_maniac_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        if context.to_call > 0:
            if read.equity >= 0.66:
                return self._raise(context, read, 1.22, "bayesian value 3-bet maniac")
            if read.equity >= 0.50 and context.to_call <= max(context.pot, context.my_stack // 6):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: bluff-catch maniac preflop equity={read.equity:.2f}",
                )
            if read.equity < 0.44:
                return self._check_or_fold(context, f"deny maniac tax equity={read.equity:.2f}")

        if context.to_call == 0 and read.equity >= 0.58:
            return self._raise(context, read, 0.78, "bayesian value open before maniac")

        return None

    def _attack_overfolding_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        credible = read.board.texture_score <= 0.50 or read.blockers.blocker_score >= 0.38
        if context.to_call == 0 and credible and read.equity >= 0.18:
            size = 0.48 if table.fold_rate >= 0.48 else 0.56
            return self._raise(context, read, size, f"bayesian pressure vs {table.style}")

        if context.to_call > 0 and table.style == "nit" and read.equity < 0.60:
            return self._check_or_fold(context, f"respect nit pressure equity={read.equity:.2f}")

        if context.to_call > 0 and read.equity >= 0.62:
            return Action(
                action="call",
                reasoning=f"{self.label}: continue vs capped {table.style} equity={read.equity:.2f}",
            )

        return None

    def _value_target_station_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        wet = read.board.texture_score >= 0.55 or read.board.is_two_tone or read.board.is_monotone
        if read.equity >= 0.60:
            size = 1.02 if wet else 0.82
            return self._raise(context, read, size, "bayesian value vs station")

        if context.to_call > 0 and read.equity >= 0.48:
            if should_call(read.equity, context.pot, context.to_call, margin=0.05):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: disciplined call vs station equity={read.equity:.2f}",
                )

        if context.to_call == 0 and read.equity < 0.42 and table.call_rate >= 0.36:
            return Action(action="check", reasoning=f"{self.label}: no low-equity bluff vs station")

        return None

    def _counter_maniac_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        if context.to_call > 0:
            if read.equity >= 0.68:
                return self._raise(context, read, 0.92, "bayesian value raise maniac")
            if read.equity >= 0.50:
                return Action(
                    action="call",
                    reasoning=f"{self.label}: bluff-catch maniac equity={read.equity:.2f}",
                )
            if read.equity < 0.42:
                return self._check_or_fold(context, f"fold weak vs maniac equity={read.equity:.2f}")

        if context.to_call == 0:
            if read.equity >= 0.66:
                return self._raise(context, read, 0.76, "bayesian value into maniac")
            if read.equity < 0.35:
                return Action(action="check", reasoning=f"{self.label}: avoid bluffing maniac")

        return None

    def _observe(self, context: DecisionContext) -> None:
        hero_names = self._hero_names(context)
        for player in context.players:
            if player.name in hero_names:
                continue
            self._record_hand_once(context, player.name)

        for index, action in enumerate(context.action_history):
            if action.player in hero_names:
                continue
            self._record_hand_once(context, action.player)
            action_key = (
                context.room_id,
                context.hand_number,
                index,
                action.phase,
                action.player,
                action.action,
                action.amount,
            )
            if action_key in self._seen_actions:
                continue
            self._seen_actions.add(action_key)
            self._record_action(action.player, action.phase, action.action)

    def _record_hand_once(self, context: DecisionContext, player_name: str) -> None:
        hand_key = (context.room_id, context.hand_number, player_name)
        if hand_key in self._seen_player_hands:
            return
        self._seen_player_hands.add(hand_key)
        self._profile(player_name).hands_seen += 1

    def _record_action(self, player_name: str, phase: str, action: str) -> None:
        profile = self._profile(player_name)
        profile.total_actions += 1

        if action in _VOLUNTARY_ACTIONS and phase == "preflop":
            profile.vpip_count += 1
        if action in _AGGRESSIVE_ACTIONS and phase == "preflop":
            profile.pfr_count += 1
        if action in _AGGRESSIVE_ACTIONS:
            profile.aggressive_count += 1
        elif action == "call":
            profile.call_count += 1
        elif action == "fold":
            profile.fold_count += 1
        elif action == "check":
            profile.check_count += 1

    def _build_table_read(self, context: DecisionContext) -> TableExploitRead:
        pressure = self._pressure_profile(context)
        if pressure is not None and pressure.confidence >= 0.20:
            return self._read_from_profile(pressure)

        profiles = [profile for profile in self._profiles.values() if profile.confidence >= 0.10]
        if not profiles:
            return _UNKNOWN_TABLE_READ

        total_weight = sum(max(0.10, profile.confidence) for profile in profiles)
        vpip = sum(profile.vpip * max(0.10, profile.confidence) for profile in profiles) / total_weight
        pfr = sum(profile.pfr * max(0.10, profile.confidence) for profile in profiles) / total_weight
        aggression = sum(profile.aggression * max(0.10, profile.confidence) for profile in profiles) / total_weight
        fold_rate = sum(profile.fold_rate * max(0.10, profile.confidence) for profile in profiles) / total_weight
        call_rate = sum(profile.call_rate * max(0.10, profile.confidence) for profile in profiles) / total_weight
        confidence = max(profile.confidence for profile in profiles)
        return TableExploitRead(
            style=self._classify_aggregate(vpip, pfr, aggression, fold_rate, call_rate, confidence),
            confidence=confidence,
            vpip=vpip,
            pfr=pfr,
            aggression=aggression,
            fold_rate=fold_rate,
            call_rate=call_rate,
        )

    def _pressure_profile(self, context: DecisionContext) -> BayesianOpponentProfile | None:
        hero_names = self._hero_names(context)
        for action in reversed(context.action_history):
            if action.player in hero_names:
                continue
            if action.action in _AGGRESSIVE_ACTIONS:
                return self._profiles.get(action.player)
        return None

    def _read_from_profile(self, profile: BayesianOpponentProfile) -> TableExploitRead:
        return TableExploitRead(
            style=profile.classify(),
            confidence=profile.confidence,
            vpip=profile.vpip,
            pfr=profile.pfr,
            aggression=profile.aggression,
            fold_rate=profile.fold_rate,
            call_rate=profile.call_rate,
        )

    def _classify_aggregate(
        self,
        vpip: float,
        pfr: float,
        aggression: float,
        fold_rate: float,
        call_rate: float,
        confidence: float,
    ) -> str:
        if confidence < 0.20:
            return "unknown"
        if aggression >= 2.2 or pfr >= 0.36:
            return "maniac"
        if vpip >= 0.42 and call_rate >= 0.34 and aggression <= 1.45:
            return "calling-station"
        if fold_rate >= 0.42 and aggression <= 1.30:
            return "overfolder"
        if vpip <= 0.26 and pfr <= 0.14:
            return "nit"
        return "balanced"

    def _profile(self, player_name: str) -> BayesianOpponentProfile:
        if player_name not in self._profiles:
            self._profiles[player_name] = BayesianOpponentProfile(name=player_name)
        return self._profiles[player_name]

    def _hero_names(self, context: DecisionContext) -> set[str]:
        return {player.name for player in context.players if player.position == context.my_seat}


class RobustFieldExploit(BayesianExploit):
    """Mixed-table exploit strategy with confidence-bound opponent composition.

    The policy treats every opponent as a separate posterior model, converts each
    model into a conservative style only when Wilson lower bounds support it, and
    then chooses the exploit according to table composition. This avoids the common
    failure mode where one calling station and one overfolder average into a fake
    balanced opponent.
    """

    slug: ClassVar[str] = "robust-field-exploit"
    label: ClassVar[str] = "RobustFieldExploit"

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.62,
            cbet_size_pot_fraction=0.57,
            raise_size_pot_fraction=0.84,
            three_bet_size_pot_fraction=1.12,
            bluff_frequency=0.07,
            semi_bluff_equity_threshold=0.23,
            river_bluff_frequency=0.025,
            fold_to_raise_equity=0.31,
            check_raise_frequency=0.06,
            donk_bet_frequency=0.04,
            m_conservative=15.0,
            m_desperate=4.5,
            exploit_aggression=0.64,
            adapt_speed=0.16,
        )

    def _build_table_read(self, context: DecisionContext) -> TableExploitRead:
        pressure = self._pressure_profile(context)
        if pressure is not None and pressure.confidence >= 0.20:
            pressure_style = self._robust_style(pressure)
            if pressure_style == "maniac":
                return self._composition_read([pressure], forced_style="maniac")

        profiles = self._active_profiles(context)
        if not profiles:
            return _UNKNOWN_TABLE_READ
        return self._composition_read(profiles)

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        if table.confidence < 0.20:
            return StatisticalLCBFusion._preflop(self, context, read)

        field_action = self._field_preflop(context, read, table)
        if field_action is not None:
            return field_action

        return StatisticalLCBFusion._preflop(self, context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        if table.confidence < 0.20:
            return StatisticalLCBFusion._postflop(self, context, read)

        field_action = self._field_postflop(context, read, table)
        if field_action is not None:
            return field_action

        return StatisticalLCBFusion._postflop(self, context, read)

    def _field_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        risky_callers = table.station_share + (table.maniac_share * 0.60)
        foldable_field = table.overfolder_share + table.nit_share
        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.42

        if context.to_call == 0:
            if foldable_field >= 0.62 and risky_callers <= 0.22 and context.my_seat in {"btn", "co", "sb"}:
                if read.equity >= 0.31 or blocker_pressure:
                    return self._raise(context, read, 0.62, "field confidence steal")

            if risky_callers >= 0.25:
                if read.equity >= 0.54:
                    return self._raise(context, read, 0.88, "field value open vs callers")
                if read.equity < 0.42:
                    return Action(action="check", reasoning=f"{self.label}: mixed field preflop pot-control")

        if context.to_call > 0:
            if table.maniac_share >= 0.25:
                if read.equity >= 0.64:
                    return self._raise(context, read, 1.16, "field value 3-bet vs maniac")
                if read.equity >= 0.50 and context.to_call <= max(context.pot, context.my_stack // 6):
                    return Action(
                        action="call",
                        reasoning=f"{self.label}: field bluff-catch maniac equity={read.equity:.2f}",
                    )
                if read.equity < 0.44:
                    return self._check_or_fold(context, f"field fold weak vs maniac equity={read.equity:.2f}")

            if table.station_share >= 0.25:
                if read.equity >= 0.59:
                    return self._raise(context, read, 1.12, "field value isolate callers")
                if read.equity < 0.44:
                    return self._check_or_fold(context, f"field no marginal call vs station equity={read.equity:.2f}")

            if foldable_field >= 0.65 and blocker_pressure and read.equity >= 0.37:
                return self._raise(context, read, 1.02, "field blocker resteal")

        return None

    def _field_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
    ) -> Action | None:
        risky_callers = table.station_share + (table.maniac_share * 0.45)
        foldable_field = table.overfolder_share + table.nit_share
        credible_bluff = read.board.texture_score <= 0.48 or read.blockers.blocker_score >= 0.42

        if table.maniac_share >= 0.25 and context.to_call > 0:
            if read.equity >= 0.68:
                return self._raise(context, read, 0.90, "field value raise maniac")
            if read.equity >= 0.50:
                return Action(
                    action="call",
                    reasoning=f"{self.label}: field bluff-catch maniac equity={read.equity:.2f}",
                )
            if read.equity < 0.42:
                return self._check_or_fold(context, f"field fold weak vs maniac equity={read.equity:.2f}")

        if table.station_share >= 0.25:
            if read.equity >= 0.60:
                size = 0.98 if read.board.texture_score >= 0.55 else 0.82
                return self._raise(context, read, size, "field value vs station mix")
            if context.to_call == 0 and read.equity < 0.47:
                return Action(action="check", reasoning=f"{self.label}: no bluff into station mix")
            if context.to_call > 0 and read.equity < 0.48:
                return self._check_or_fold(context, f"field fold station price equity={read.equity:.2f}")

        if context.to_call == 0 and foldable_field >= 0.62 and risky_callers <= 0.22:
            if credible_bluff and read.equity >= 0.18:
                return self._raise(context, read, 0.50, "field confidence pressure")

        if table.diversity_score >= 0.55:
            if context.to_call == 0 and read.equity < 0.54:
                return Action(action="check", reasoning=f"{self.label}: diverse field pot-control")
            if context.to_call > 0 and read.equity < 0.52:
                return self._check_or_fold(context, f"diverse field no thin call equity={read.equity:.2f}")

        return None

    def _composition_read(
        self,
        profiles: list[BayesianOpponentProfile],
        forced_style: str | None = None,
    ) -> TableExploitRead:
        weights: dict[str, float] = {style: 0.0 for style in _ROBUST_STYLES}
        weighted_vpip = 0.0
        weighted_pfr = 0.0
        weighted_aggression = 0.0
        weighted_fold = 0.0
        weighted_call = 0.0
        total_weight = 0.0
        confidence = 0.0

        for profile in profiles:
            weight = max(0.10, profile.confidence)
            style = self._robust_style(profile)
            if style not in weights:
                style = "balanced"
            weights[style] += weight
            weighted_vpip += profile.vpip * weight
            weighted_pfr += profile.pfr * weight
            weighted_aggression += profile.aggression * weight
            weighted_fold += profile.fold_rate * weight
            weighted_call += profile.call_rate * weight
            total_weight += weight
            confidence = max(confidence, profile.confidence)

        if total_weight <= 0.0:
            return _UNKNOWN_TABLE_READ

        shares = {style: weights[style] / total_weight for style in _ROBUST_STYLES}
        diversity = 1.0 - sum(share * share for share in shares.values())
        style = forced_style or self._composition_style(shares, diversity, confidence)

        return TableExploitRead(
            style=style,
            confidence=confidence,
            vpip=weighted_vpip / total_weight,
            pfr=weighted_pfr / total_weight,
            aggression=weighted_aggression / total_weight,
            fold_rate=weighted_fold / total_weight,
            call_rate=weighted_call / total_weight,
            overfolder_share=shares["overfolder"],
            nit_share=shares["nit"],
            station_share=shares["calling-station"],
            maniac_share=shares["maniac"],
            balanced_share=shares["balanced"],
            diversity_score=diversity,
        )

    def _composition_style(
        self,
        shares: dict[str, float],
        diversity: float,
        confidence: float,
    ) -> str:
        if confidence < 0.20:
            return "unknown"
        if shares["maniac"] >= 0.45:
            return "maniac"
        if shares["calling-station"] >= 0.45:
            return "calling-station"
        if shares["overfolder"] + shares["nit"] >= 0.65 and shares["calling-station"] < 0.20:
            return "overfolder"
        if diversity >= 0.45:
            return "mixed"
        return "balanced"

    def _robust_style(self, profile: BayesianOpponentProfile) -> str:
        if profile.confidence < 0.20:
            return "balanced"
        if profile.aggressive_lcb >= 0.30 or profile.pfr_lcb >= 0.30:
            return "maniac"
        if profile.call_lcb >= 0.28 and profile.vpip >= 0.42 and profile.aggression <= 1.55:
            return "calling-station"
        if profile.fold_lcb >= 0.32 and profile.aggression <= 1.35:
            return "overfolder"
        if profile.vpip <= 0.28 and profile.pfr <= 0.16 and profile.fold_rate >= 0.32:
            return "nit"
        return "balanced"

    def _active_profiles(self, context: DecisionContext) -> list[BayesianOpponentProfile]:
        hero_names = self._hero_names(context)
        active_names = [
            player.name
            for player in context.players
            if player.name not in hero_names and player.status.lower() not in {"folded", "out", "eliminated"}
        ]
        if active_names:
            return [
                self._profiles[name]
                for name in active_names
                if name in self._profiles and self._profiles[name].confidence >= 0.10
            ]
        return [profile for profile in self._profiles.values() if profile.confidence >= 0.10]


class LearningFieldExploit(RobustFieldExploit):
    """Field-aware exploit strategy that ramps up as hands and samples accumulate.

    Early decisions stay close to the LCB baseline while the strategy records each
    opponent. Once the hand counter and opponent confidence are both meaningful,
    it relaxes steal/value thresholds and lets composition-based exploits fire
    more often.
    """

    slug: ClassVar[str] = "learning-field-exploit"
    label: ClassVar[str] = "LearningFieldExploit"

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.64,
            cbet_size_pot_fraction=0.58,
            raise_size_pot_fraction=0.86,
            three_bet_size_pot_fraction=1.14,
            bluff_frequency=0.08,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.03,
            fold_to_raise_equity=0.30,
            check_raise_frequency=0.07,
            donk_bet_frequency=0.04,
            m_conservative=15.0,
            m_desperate=4.5,
            exploit_aggression=0.67,
            adapt_speed=0.18,
        )

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        strength = self._learning_strength(context, table)
        if table.confidence < 0.20 or strength < 0.35:
            return StatisticalLCBFusion._preflop(self, context, read)

        if strength >= 0.70:
            late_action = self._late_stage_preflop(context, read, table, strength)
            if late_action is not None:
                return late_action

        field_action = self._field_preflop(context, read, table)
        if field_action is not None:
            return field_action

        if strength < 0.70 and table.diversity_score >= 0.45 and context.to_call == 0 and read.equity < 0.35:
            return Action(action="check", reasoning=f"{self.label}: early mixed-field control")

        return StatisticalLCBFusion._preflop(self, context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        strength = self._learning_strength(context, table)
        if table.confidence < 0.20 or strength < 0.35:
            return StatisticalLCBFusion._postflop(self, context, read)

        if strength >= 0.70:
            late_action = self._late_stage_postflop(context, read, table, strength)
            if late_action is not None:
                return late_action

        field_action = self._field_postflop(context, read, table)
        if field_action is not None:
            return field_action

        return StatisticalLCBFusion._postflop(self, context, read)

    def _learning_strength(self, context: DecisionContext, table: TableExploitRead) -> float:
        hand_progress = min(1.0, max(0.0, (context.hand_number - 3) / 12.0))
        return min(1.0, (table.confidence * 0.65) + (hand_progress * table.confidence * 0.35))

    def _late_stage_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        strength: float,
    ) -> Action | None:
        risky_callers = table.station_share + (table.maniac_share * 0.60)
        foldable_field = table.overfolder_share + table.nit_share
        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.38
        threshold_discount = 0.05 * strength

        if context.to_call == 0:
            if (
                context.my_seat in {"btn", "co", "sb"}
                and foldable_field >= 0.45
                and risky_callers <= 0.30
                and (read.equity >= 0.31 - threshold_discount or blocker_pressure)
            ):
                return self._raise(context, read, 0.60, "learning late-stage steal")

            if risky_callers >= 0.20 and read.equity >= 0.53 - threshold_discount:
                return self._raise(context, read, 0.90, "learning value open vs sticky field")

        if context.to_call > 0:
            if table.maniac_share >= 0.20:
                if read.equity >= 0.62 - threshold_discount:
                    return self._raise(context, read, 1.16, "learning value punish maniac")
                if read.equity >= 0.48 - threshold_discount:
                    return Action(
                        action="call",
                        reasoning=f"{self.label}: learned maniac bluff-catch equity={read.equity:.2f}",
                    )

            if table.station_share >= 0.20 and read.equity >= 0.57 - threshold_discount:
                return self._raise(context, read, 1.10, "learning value isolate station")

            if foldable_field >= 0.50 and blocker_pressure and read.equity >= 0.35:
                return self._raise(context, read, 1.00, "learning late blocker resteal")

        return None

    def _late_stage_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        strength: float,
    ) -> Action | None:
        risky_callers = table.station_share + (table.maniac_share * 0.45)
        foldable_field = table.overfolder_share + table.nit_share
        credible_bluff = read.board.texture_score <= 0.50 or read.blockers.blocker_score >= 0.38
        threshold_discount = 0.05 * strength

        if table.maniac_share >= 0.20 and context.to_call > 0:
            if read.equity >= 0.66 - threshold_discount:
                return self._raise(context, read, 0.90, "learning value raise maniac")
            if read.equity >= 0.48 - threshold_discount:
                return Action(
                    action="call",
                    reasoning=f"{self.label}: learned bluff-catch maniac equity={read.equity:.2f}",
                )

        if table.station_share >= 0.20 and read.equity >= 0.58 - threshold_discount:
            size = 1.00 if read.board.texture_score >= 0.55 else 0.82
            return self._raise(context, read, size, "learning value vs sticky field")

        if context.to_call == 0 and foldable_field >= 0.45 and risky_callers <= 0.30:
            if credible_bluff and read.equity >= 0.16:
                return self._raise(context, read, 0.48, "learning late-stage pressure")

        if table.diversity_score >= 0.55 and context.to_call == 0 and read.equity < 0.50:
            return Action(action="check", reasoning=f"{self.label}: learned diverse-field control")

        return None


class StageSafeFieldCounter(LearningFieldExploit):
    """Stage-aware safe counter strategy for variable table sizes.

    The policy keeps the LCB baseline as its default, then spends exploit budget
    only when the table read, stack pressure, and player count all support it.
    This is deliberately less brittle than the learning-field ramp-up: early
    hands stay protected, middle hands defend steal pressure, and late hands
    increase pressure only with blockers, equity, or a reliable field read.
    """

    slug: ClassVar[str] = "stage-safe-field-counter"
    label: ClassVar[str] = "StageSafeFieldCounter"

    @staticmethod
    def _default_genome() -> StrategyGenome:
        return StrategyGenome(
            cbet_frequency=0.63,
            cbet_size_pot_fraction=0.56,
            raise_size_pot_fraction=0.76,
            three_bet_size_pot_fraction=1.08,
            bluff_frequency=0.055,
            semi_bluff_equity_threshold=0.22,
            river_bluff_frequency=0.018,
            fold_to_raise_equity=0.31,
            check_raise_frequency=0.05,
            donk_bet_frequency=0.025,
            m_conservative=15.0,
            m_desperate=4.5,
            exploit_aggression=0.60,
            adapt_speed=0.14,
        )

    def _preflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        stage = self._stage_pressure(context, read)
        opponents = self._active_opponent_count(context)
        field_tax = self._multiway_tax(opponents)

        anti_steal = self._counter_late_position_pressure(context, read, table, stage, field_tax)
        if anti_steal is not None:
            return anti_steal

        if context.to_call == 0:
            field_action = self._safe_open_pressure(context, read, table, stage, opponents, field_tax)
            if field_action is not None:
                return field_action

            if opponents >= 3 and read.equity < 0.36 + field_tax and not read.blockers.blocks_ace_high:
                return Action(action="check", reasoning=f"{self.label}: multiway early-range control")

            return StatisticalLCBFusion._preflop(self, context, read)

        facing_action = self._safe_facing_preflop(context, read, table, stage, field_tax)
        if facing_action is not None:
            return facing_action

        return StatisticalLCBFusion._preflop(self, context, read)

    def _postflop(self, context: DecisionContext, read: PracticalRead) -> Action:
        table = self._table_read
        stage = self._stage_pressure(context, read)
        opponents = self._active_opponent_count(context)
        field_tax = self._multiway_tax(opponents)

        if context.to_call > 0:
            facing_action = self._safe_facing_postflop(context, read, table, stage, field_tax)
            if facing_action is not None:
                return facing_action
            return StatisticalLCBFusion._postflop(self, context, read)

        if read.equity >= 0.62 + field_tax:
            size = 0.92 if read.board.texture_score >= 0.55 else 0.66
            return self._raise(context, read, size, "safe value/protection")

        if read.has_combo_draw and read.equity >= 0.18 + (field_tax * 0.5):
            return self._raise(context, read, 0.74, "safe combo-draw pressure")

        field_action = self._safe_postflop_pressure(context, read, table, stage, opponents, field_tax)
        if field_action is not None:
            return field_action

        if table.diversity_score >= 0.50 and read.equity < 0.52 + field_tax:
            return Action(action="check", reasoning=f"{self.label}: diverse field control")

        return StatisticalLCBFusion._postflop(self, context, read)

    def _safe_open_pressure(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        stage: float,
        opponents: int,
        field_tax: float,
    ) -> Action | None:
        foldable_field = table.overfolder_share + table.nit_share
        risky_callers = table.station_share + (table.maniac_share * 0.60)
        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.40
        late_or_blind = context.my_seat in {"btn", "co", "sb"}

        if read.equity >= 0.54 + field_tax:
            size = 0.86 if risky_callers >= 0.20 else 0.72
            return self._raise(context, read, size, "safe value open")

        if not late_or_blind or table.confidence < 0.20:
            return None

        fold_threshold = max(0.42, 0.56 - (stage * 0.10))
        equity_threshold = max(0.28, 0.34 + field_tax - (stage * 0.05))
        if foldable_field >= fold_threshold and risky_callers <= 0.28:
            if read.equity >= equity_threshold or blocker_pressure:
                size = 0.54 if opponents <= 2 else 0.62
                return self._raise(context, read, size, "safe field steal")

        return None

    def _safe_facing_preflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        stage: float,
        field_tax: float,
    ) -> Action | None:
        foldable_field = table.overfolder_share + table.nit_share
        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.40

        if self._bad_large_price(context, read, equity_cap=0.61 + field_tax):
            return self._check_or_fold(context, f"safe preflop price fold equity={read.equity:.2f}")

        if table.maniac_share >= 0.18 or read.opponent_aggression >= 2.0:
            if read.equity >= 0.62 + field_tax - (stage * 0.03):
                return self._raise(context, read, 1.10, "safe value punish pressure")
            if read.equity >= 0.49 + field_tax - (stage * 0.04):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: safe bluff-catch preflop equity={read.equity:.2f}",
                )

        if table.station_share >= 0.18:
            if read.equity >= 0.57 + field_tax:
                return self._raise(context, read, 1.06, "safe station isolate")
            if read.equity < 0.44 + field_tax:
                return self._check_or_fold(context, f"safe no marginal station call equity={read.equity:.2f}")

        if table.confidence >= 0.20 and foldable_field >= 0.50 and blocker_pressure and read.equity >= 0.35 + field_tax:
            return self._raise(context, read, 0.98, "safe blocker resteal")

        return None

    def _safe_facing_postflop(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        stage: float,
        field_tax: float,
    ) -> Action | None:
        pressure_read = table.maniac_share >= 0.18 or read.opponent_aggression >= 2.0

        if self._bad_large_price(context, read, equity_cap=0.64 + field_tax):
            return self._check_or_fold(context, f"safe large-price fold equity={read.equity:.2f}")

        if pressure_read:
            if read.equity >= 0.66 + field_tax - (stage * 0.03):
                return self._raise(context, read, 0.86, "safe value raise pressure")
            if read.equity >= 0.48 + field_tax - (stage * 0.04):
                return Action(
                    action="call",
                    reasoning=f"{self.label}: safe pressure bluff-catch equity={read.equity:.2f}",
                )

        if table.station_share >= 0.18 and read.equity >= 0.58 + field_tax:
            size = 0.94 if read.board.texture_score >= 0.55 else 0.78
            return self._raise(context, read, size, "safe value vs sticky field")

        call_margin = max(0.02, 0.055 + field_tax - (stage * 0.025))
        if should_call(read.equity, context.pot, context.to_call, margin=call_margin):
            return Action(action="call", reasoning=f"{self.label}: safe priced continue equity={read.equity:.2f}")

        if read.equity < 0.44 + field_tax:
            return self._check_or_fold(context, f"safe low-equity fold equity={read.equity:.2f}")

        return None

    def _safe_postflop_pressure(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        stage: float,
        opponents: int,
        field_tax: float,
    ) -> Action | None:
        if table.station_share >= 0.18 and read.equity < 0.56 + field_tax:
            return Action(action="check", reasoning=f"{self.label}: no bluff into sticky field")

        foldable_field = table.overfolder_share + table.nit_share
        risky_callers = table.station_share + (table.maniac_share * 0.45)
        credible = read.board.texture_score <= 0.48 or read.blockers.blocker_score >= 0.40
        fold_threshold = max(0.42, 0.56 - (stage * 0.12))
        equity_threshold = max(0.16, 0.22 + field_tax - (stage * 0.05))

        if table.confidence >= 0.20 and foldable_field >= fold_threshold and risky_callers <= 0.28:
            if credible and read.equity >= equity_threshold:
                size = 0.44 if opponents <= 2 else 0.52
                return self._raise(context, read, size, "safe field pressure")

        return None

    def _counter_late_position_pressure(
        self,
        context: DecisionContext,
        read: PracticalRead,
        table: TableExploitRead,
        stage: float,
        field_tax: float,
    ) -> Action | None:
        if context.to_call <= 0 or context.my_seat not in {"sb", "bb"}:
            return None

        aggressor_position = self._latest_aggressor_position(context)
        if aggressor_position not in {"btn", "co", "sb"}:
            return None

        affordable = context.to_call <= max(context.pot, context.blind[1] * 7)
        if not affordable:
            return None

        blocker_pressure = read.blockers.blocks_ace_high or read.blockers.blocker_score >= 0.38
        defend_threshold = max(0.34, 0.42 + field_tax - (stage * 0.05))
        resteal_threshold = max(0.31, defend_threshold - 0.05)

        if blocker_pressure and read.equity >= resteal_threshold and table.station_share < 0.30:
            return self._raise(context, read, 0.96, "safe anti-steal resteal")

        defend_range = 0.40 if context.my_seat == "bb" else 0.30
        if read.equity >= defend_threshold or hand_in_range(context.hole_cards, defend_range):
            return Action(action="call", reasoning=f"{self.label}: safe anti-steal defend equity={read.equity:.2f}")

        return None

    def _latest_aggressor_position(self, context: DecisionContext) -> str | None:
        hero_names = self._hero_names(context)
        positions = {player.name: player.position for player in context.players}
        for action in reversed(context.action_history):
            if action.player in hero_names or action.action not in _AGGRESSIVE_ACTIONS:
                continue
            return positions.get(action.player)
        return None

    def _active_opponent_count(self, context: DecisionContext) -> int:
        hero_names = self._hero_names(context)
        return sum(
            1
            for player in context.players
            if player.name not in hero_names and player.status.lower() not in {"folded", "out", "eliminated"}
        )

    def _multiway_tax(self, opponents: int) -> float:
        return min(0.12, max(0, opponents - 1) * 0.025)

    def _stage_pressure(self, context: DecisionContext, read: PracticalRead) -> float:
        scheduled_hands = sum(max(0, level.hands) for level in context.blind_structure)
        if scheduled_hands > 0:
            hand_progress = min(1.0, max(0.0, context.hand_number / scheduled_hands))
        else:
            hand_progress = min(1.0, max(0.0, (context.hand_number - 3) / 17.0))

        if read.big_blinds <= 12.0:
            stack_pressure = 1.0
        elif read.big_blinds <= 20.0:
            stack_pressure = 0.70
        elif read.big_blinds <= 35.0:
            stack_pressure = 0.35
        else:
            stack_pressure = 0.0

        return max(hand_progress, stack_pressure)


STATISTICAL_STRATEGIES: tuple[type[PracticalStrategy], ...] = (
    StatisticalLCBFusion,
    BayesianExploit,
    RobustFieldExploit,
    LearningFieldExploit,
    StageSafeFieldCounter,
)
