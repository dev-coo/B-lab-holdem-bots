from __future__ import annotations

from holdem_agent.storage.database import Database
from holdem_agent.storage.metrics_store import MetricsStore


class MetricsCalculator:
    """Calculate strategy performance metrics."""

    def __init__(self, db: Database) -> None:
        self._store = MetricsStore(db)

    def get_strategy_metrics(self, strategy_name: str) -> dict:
        """Get comprehensive metrics for a strategy."""
        return self._store.get_strategy_summary(strategy_name)

    def get_win_rate(self, strategy_name: str) -> float:
        """Get win rate for a strategy."""
        return self.get_strategy_metrics(strategy_name).get("win_rate", 0.0)

    def get_vpip(self, strategy_name: str) -> float:
        """Calculate VPIP (Voluntarily Put $ In Pot)."""
        summary = self._store.get_strategy_summary(strategy_name)
        total = summary.get("total_decisions", 0)
        folds = summary.get("folds", 0)
        if total == 0:
            return 0.0
        # VPIP = non-fold actions preflop / total preflop actions
        voluntary = total - folds
        return voluntary / total

    def get_aggression_factor(self, strategy_name: str) -> float:
        """Calculate aggression factor = (raises + bets) / calls."""
        summary = self._store.get_strategy_summary(strategy_name)
        calls = summary.get("calls", 0)
        raises = summary.get("raises", 0)
        if calls == 0:
            return float(raises)
        return raises / calls

    def get_action_distribution(self, strategy_name: str) -> dict[str, int]:
        """Get action type distribution."""
        return self._store.get_action_distribution(strategy_name)
