from __future__ import annotations

from holdem_agent.storage.database import Database


class MetricsStore:
    """Query aggregated metrics from game data."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_strategy_summary(self, strategy_name: str) -> dict:
        """Get aggregated metrics for a strategy."""
        game_count = self._db.execute(
            "SELECT COUNT(*) FROM games WHERE strategy_name=?",
            (strategy_name,),
        ).fetchone()[0]

        avg_rank = self._db.execute(
            "SELECT AVG(final_rank) FROM games WHERE strategy_name=? AND final_rank IS NOT NULL",
            (strategy_name,),
        ).fetchone()[0] or 0.0

        total_hands = self._db.execute(
            "SELECT SUM(total_hands) FROM games WHERE strategy_name=?",
            (strategy_name,),
        ).fetchone()[0] or 0

        wins = self._db.execute(
            "SELECT COUNT(*) FROM games WHERE strategy_name=? AND final_rank=1",
            (strategy_name,),
        ).fetchone()[0]

        win_rate = wins / game_count if game_count > 0 else 0.0

        decision_count = self._db.execute(
            "SELECT COUNT(*) FROM decisions WHERE strategy_name=?",
            (strategy_name,),
        ).fetchone()[0]

        fold_count = self._db.execute(
            "SELECT COUNT(*) FROM decisions WHERE strategy_name=? AND action_type='fold'",
            (strategy_name,),
        ).fetchone()[0]

        raise_count = self._db.execute(
            "SELECT COUNT(*) FROM decisions WHERE strategy_name=? AND action_type='raise'",
            (strategy_name,),
        ).fetchone()[0]

        call_count = self._db.execute(
            "SELECT COUNT(*) FROM decisions WHERE strategy_name=? AND action_type='call'",
            (strategy_name,),
        ).fetchone()[0]

        return {
            "strategy_name": strategy_name,
            "games_played": game_count,
            "win_rate": win_rate,
            "avg_rank": avg_rank,
            "total_hands": total_hands,
            "total_decisions": decision_count,
            "folds": fold_count,
            "raises": raise_count,
            "calls": call_count,
        }

    def get_action_distribution(self, strategy_name: str) -> dict[str, int]:
        """Get action type distribution for a strategy."""
        rows = self._db.execute(
            "SELECT action_type, COUNT(*) as cnt FROM decisions WHERE strategy_name=? GROUP BY action_type",
            (strategy_name,),
        ).fetchall()
        return {row["action_type"]: row["cnt"] for row in rows}
