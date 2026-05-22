from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class OpponentProfile:
    """Tracks observed tendencies for a single opponent."""

    name: str
    hands_played: int = 0
    vpip_count: int = 0  # voluntarily put $ in pot
    pfr_count: int = 0  # preflop raise count
    raise_count: int = 0  # total raises
    bet_count: int = 0
    fold_count: int = 0
    call_count: int = 0

    @property
    def vpip(self) -> float:
        """Voluntarily Put $ In Pot - measures how loose a player is."""
        return self.vpip_count / self.hands_played if self.hands_played > 0 else 0.0

    @property
    def pfr(self) -> float:
        """Pre-Flop Raise percentage."""
        return self.pfr_count / self.hands_played if self.hands_played > 0 else 0.0

    @property
    def aggression_factor(self) -> float:
        """AF = (raises + bets) / calls. Higher = more aggressive."""
        if self.call_count == 0:
            return float(self.raise_count + self.bet_count)
        return (self.raise_count + self.bet_count) / self.call_count

    @property
    def fold_percentage(self) -> float:
        return self.fold_count / self.hands_played if self.hands_played > 0 else 0.0

    def classify(self) -> str:
        """Classify opponent style: 'tight-passive' | 'tight-aggressive' | 'loose-passive' | 'loose-aggressive'."""
        loose = self.vpip > 0.35
        aggressive = self.aggression_factor > 1.5

        if loose and aggressive:
            return "loose-aggressive"
        if loose:
            return "loose-passive"
        if aggressive:
            return "tight-aggressive"
        return "tight-passive"


class OpponentTracker:
    """Tracks multiple opponents across a game."""

    def __init__(self) -> None:
        self._opponents: dict[str, OpponentProfile] = {}

    def get_or_create(self, name: str) -> OpponentProfile:
        if name not in self._opponents:
            self._opponents[name] = OpponentProfile(name=name)
        return self._opponents[name]

    def record_action(self, player_name: str, action: str, phase: str) -> None:
        """Record an observed opponent action."""
        opp = self.get_or_create(player_name)

        if action in ("call", "raise", "bet"):
            opp.vpip_count += 1

        if phase == "preflop" and action in ("raise", "bet"):
            opp.pfr_count += 1

        if action == "raise":
            opp.raise_count += 1
        elif action == "bet":
            opp.bet_count += 1
        elif action == "fold":
            opp.fold_count += 1
        elif action == "call":
            opp.call_count += 1

    def record_hand(self, player_name: str) -> None:
        """Record that an opponent played a hand."""
        opp = self.get_or_create(player_name)
        opp.hands_played += 1

    def get_profile(self, name: str) -> OpponentProfile | None:
        return self._opponents.get(name)

    @property
    def all_profiles(self) -> dict[str, OpponentProfile]:
        return dict(self._opponents)
