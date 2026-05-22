from __future__ import annotations

import json
from holdem_agent.analytics.weakspot import Weakspot


class Reporter:
    """Generate analysis reports."""

    def format_metrics(self, metrics: dict) -> str:
        """Format metrics as readable text."""
        lines = [
            f"Strategy: {metrics.get('strategy_name', 'unknown')}",
            f"Games: {metrics.get('games_played', 0)}",
            f"Win Rate: {metrics.get('win_rate', 0.0):.1%}",
            f"Avg Rank: {metrics.get('avg_rank', 0.0):.1f}",
            f"Total Hands: {metrics.get('total_hands', 0)}",
            f"Decisions: {metrics.get('total_decisions', 0)}",
        ]
        return "\n".join(lines)

    def format_weakspots(self, weakspots: list[Weakspot]) -> str:
        """Format weakspots as readable text."""
        if not weakspots:
            return "No significant weaknesses found."
        # Fix: join correctly
        result = []
        for i, ws in enumerate(weakspots):
            result.append(f"{i+1}. [{ws.area}] {ws.description}")
            result.append(f"   → {ws.suggestion}")
            result.append(f"   → Adjust: {ws.param_to_adjust} ({ws.direction})")
        return "\n".join(result)

    def format_comparison(self, strategies: list[dict]) -> str:
        """Format strategy comparison table."""
        lines = []
        for s in strategies:
            name = s.get("strategy_name", "?")
            wr = s.get("win_rate", 0.0)
            games = s.get("games_played", 0)
            rank = s.get("rank", "?")
            lines.append(f"#{rank} {name}: {wr:.1%} win rate ({games} games)")
        return "\n".join(lines) if lines else "No data to compare."

    def metrics_to_json(self, metrics: dict) -> str:
        return json.dumps(metrics, indent=2)

    def weakspots_to_json(self, weakspots: list[Weakspot]) -> str:
        data = [{"area": ws.area, "description": ws.description,
                 "suggestion": ws.suggestion, "param": ws.param_to_adjust,
                 "direction": ws.direction} for ws in weakspots]
        return json.dumps(data, indent=2)
