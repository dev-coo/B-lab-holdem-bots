from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Weakspot:
    """Identified strategy weakness."""

    area: str
    description: str
    suggestion: str
    param_to_adjust: str
    direction: str  # "increase" | "decrease"


class WeakspotAnalyzer:
    """Diagnose strategy weaknesses from game data."""

    def __init__(self) -> None:
        pass

    def analyze_decisions(self, decisions: list[dict], metrics: dict) -> list[Weakspot]:
        """Analyze decisions and metrics to find weaknesses."""
        weakspots = []

        # Check fold frequency
        total = len(decisions)
        if total == 0:
            return weakspots

        folds = sum(1 for d in decisions if d.get("action_type") == "fold")
        fold_pct = folds / total

        if fold_pct > 0.7:
            weakspots.append(Weakspot(
                area="overfolding",
                description=f"Folding too much ({fold_pct:.0%})",
                suggestion="Lower fold threshold, call more with marginal hands",
                param_to_adjust="fold_to_raise_equity",
                direction="increase",
            ))

        # Check bluff success
        raises = sum(1 for d in decisions if d.get("action_type") == "raise")
        raise_pct = raises / total

        if raise_pct < 0.05:
            weakspots.append(Weakspot(
                area="passive",
                description=f"Very low raise frequency ({raise_pct:.0%})",
                suggestion="Increase aggression, raise more in position",
                param_to_adjust="bluff_frequency",
                direction="increase",
            ))

        # Check if calling too much (calling station detection)
        calls = sum(1 for d in decisions if d.get("action_type") == "call")
        call_pct = calls / total

        if call_pct > 0.6:
            weakspots.append(Weakspot(
                area="calling_station",
                description=f"Calling too much ({call_pct:.0%})",
                suggestion="Fold marginal hands, raise strong hands instead of calling",
                param_to_adjust="preflop_call_threshold",
                direction="decrease",
            ))

        return weakspots

    def analyze_metrics(self, metrics: dict) -> list[Weakspot]:
        """Analyze aggregate metrics for weaknesses."""
        weakspots = []

        win_rate = metrics.get("win_rate", 0.0)
        avg_rank = metrics.get("avg_rank", 0.0)

        if win_rate < 0.15 and metrics.get("games_played", 0) >= 5:
            weakspots.append(Weakspot(
                area="low_win_rate",
                description=f"Low win rate ({win_rate:.1%})",
                suggestion="Tighten preflop range and increase postflop aggression",
                param_to_adjust="preflop_raise_threshold",
                direction="increase",
            ))

        if avg_rank > 2.5 and metrics.get("games_played", 0) >= 5:
            weakspots.append(Weakspot(
                area="poor_finishes",
                description=f"Average finish rank {avg_rank:.1f}",
                suggestion="Improve late-game push/fold strategy",
                param_to_adjust="m_conservative",
                direction="decrease",
            ))

        return weakspots
