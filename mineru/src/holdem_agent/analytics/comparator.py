from __future__ import annotations

from holdem_agent.storage.database import Database
from holdem_agent.analytics.metrics import MetricsCalculator


class StrategyComparator:
    """Compare multiple strategies."""

    def __init__(self, db: Database) -> None:
        self._calc = MetricsCalculator(db)

    def compare(self, strategy_names: list[str]) -> list[dict]:
        """Compare strategies side by side. Returns list sorted by win_rate desc."""
        results = []
        for name in strategy_names:
            metrics = self._calc.get_strategy_metrics(name)
            results.append(metrics)
        results.sort(key=lambda x: x.get("win_rate", 0.0), reverse=True)
        return results

    def best_strategy(self, strategy_names: list[str]) -> str | None:
        """Find the best strategy by win rate."""
        results = self.compare(strategy_names)
        if not results or results[0].get("games_played", 0) == 0:
            return None
        return results[0]["strategy_name"]

    def rank_strategies(self, strategy_names: list[str]) -> list[dict]:
        """Rank strategies with rank number."""
        results = self.compare(strategy_names)
        for i, r in enumerate(results):
            r["rank"] = i + 1
        return results
