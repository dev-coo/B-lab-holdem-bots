from __future__ import annotations

import json

from holdem_agent.analytics.weakspot import Weakspot
from holdem_agent.analytics.reporter import Reporter


def test_format_metrics():
    reporter = Reporter()
    metrics = {
        "strategy_name": "balanced-bot",
        "games_played": 12,
        "win_rate": 0.33,
        "avg_rank": 2.2,
        "total_hands": 120,
        "total_decisions": 240,
    }

    text = reporter.format_metrics(metrics)

    assert text == (
        "Strategy: balanced-bot\n"
        "Games: 12\n"
        "Win Rate: 33.0%\n"
        "Avg Rank: 2.2\n"
        "Total Hands: 120\n"
        "Decisions: 240"
    )


def test_format_weakspots_empty():
    reporter = Reporter()
    assert reporter.format_weakspots([]) == "No significant weaknesses found."


def test_format_weakspots_with_data():
    reporter = Reporter()
    weakspots = [
        Weakspot(
            area="overfolding",
            description="Folding too much (80%)",
            suggestion="Lower fold threshold",
            param_to_adjust="fold_to_raise_equity",
            direction="increase",
        ),
        Weakspot(
            area="passive",
            description="Very low raise frequency (4%)",
            suggestion="Increase aggression",
            param_to_adjust="bluff_frequency",
            direction="increase",
        ),
    ]

    text = reporter.format_weakspots(weakspots)

    assert "1. [overfolding] Folding too much (80%)" in text
    assert "2. [passive] Very low raise frequency (4%)" in text
    assert "→ Adjust: bluff_frequency (increase)" in text


def test_format_comparison():
    reporter = Reporter()
    strategies = [
        {"strategy_name": "tight", "win_rate": 0.25, "games_played": 40, "rank": 1},
        {"strategy_name": "aggro", "win_rate": 0.35, "games_played": 25, "rank": 2},
    ]

    text = reporter.format_comparison(strategies)
    assert text == (
        "#1 tight: 25.0% win rate (40 games)\n"
        "#2 aggro: 35.0% win rate (25 games)"
    )


def test_metrics_to_json():
    reporter = Reporter()
    metrics = {"strategy_name": "tight", "games_played": 2, "win_rate": 0.2}
    payload = json.loads(reporter.metrics_to_json(metrics))

    assert payload == metrics


def test_weakspots_to_json():
    reporter = Reporter()
    weakspots = [
        Weakspot(
            area="calling_station",
            description="Calling too much (75%)",
            suggestion="Fold marginal hands",
            param_to_adjust="preflop_call_threshold",
            direction="decrease",
        )
    ]

    payload = json.loads(reporter.weakspots_to_json(weakspots))
    assert payload == [
        {
            "area": "calling_station",
            "description": "Calling too much (75%)",
            "suggestion": "Fold marginal hands",
            "param": "preflop_call_threshold",
            "direction": "decrease",
        }
    ]
