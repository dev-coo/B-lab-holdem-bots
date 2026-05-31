from __future__ import annotations

from holdem_agent.analytics.weakspot import WeakspotAnalyzer


def test_no_weakspots_empty():
    analyzer = WeakspotAnalyzer()
    result = analyzer.analyze_decisions([], {})
    assert result == []


def test_overfolding_detected():
    analyzer = WeakspotAnalyzer()
    decisions = [{"action_type": "fold"} for _ in range(8)] + [
        {"action_type": "call"},
        {"action_type": "raise"},
    ]
    result = analyzer.analyze_decisions(decisions, {})

    assert len(result) == 1
    ws = result[0]
    assert ws.area == "overfolding"
    assert ws.description == "Folding too much (80%)"
    assert ws.param_to_adjust == "fold_to_raise_equity"
    assert ws.direction == "increase"


def test_passive_detected():
    analyzer = WeakspotAnalyzer()
    decisions = [
        {"action_type": "call"},
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "call"},
        {"action_type": "call"},
        {"action_type": "call"},
        {"action_type": "fold"},
        {"action_type": "fold"},
    ]  # 10 decisions, 0 raises => 0%
    result = analyzer.analyze_decisions(decisions, {})

    assert len(result) == 1
    ws = result[0]
    assert ws.area == "passive"
    assert ws.description == "Very low raise frequency (0%)"
    assert ws.param_to_adjust == "bluff_frequency"


def test_calling_station_detected():
    analyzer = WeakspotAnalyzer()
    decisions = [{"action_type": "call"} for _ in range(7)] + [
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "raise"},
    ]  # 10 decisions, 70% calls
    result = analyzer.analyze_decisions(decisions, {})

    assert len(result) == 1
    ws = result[0]
    assert ws.area == "calling_station"
    assert ws.description == "Calling too much (70%)"
    assert ws.param_to_adjust == "preflop_call_threshold"


def test_low_win_rate():
    analyzer = WeakspotAnalyzer()
    result = analyzer.analyze_metrics({"win_rate": 0.1, "games_played": 5})

    assert len(result) == 1
    ws = result[0]
    assert ws.area == "low_win_rate"
    assert ws.description == "Low win rate (10.0%)"
    assert ws.param_to_adjust == "preflop_raise_threshold"


def test_poor_finishes():
    analyzer = WeakspotAnalyzer()
    result = analyzer.analyze_metrics({"win_rate": 0.2, "avg_rank": 3.0, "games_played": 5})

    assert len(result) == 1
    ws = result[0]
    assert ws.area == "poor_finishes"
    assert ws.description == "Average finish rank 3.0"
    assert ws.param_to_adjust == "m_conservative"


def test_good_strategy_no_weakspots():
    analyzer = WeakspotAnalyzer()
    decisions = [
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "fold"},
        {"action_type": "call"},
        {"action_type": "call"},
        {"action_type": "call"},
        {"action_type": "raise"},
        {"action_type": "raise"},
        {"action_type": "raise"},
    ]

    metrics = {"win_rate": 0.4, "avg_rank": 2.1, "games_played": 10}
    decision_weakspots = analyzer.analyze_decisions(decisions, metrics)
    metric_weakspots = analyzer.analyze_metrics(metrics)

    assert decision_weakspots == []
    assert metric_weakspots == []
