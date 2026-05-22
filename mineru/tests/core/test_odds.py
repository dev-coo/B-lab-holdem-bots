# pyright: reportMissingImports=false

from __future__ import annotations

from holdem_agent.core.odds import (
    expected_value,
    is_profitable_call,
    m_value,
    m_zone,
    needed_equity,
    pot_odds,
    suggested_bet_size,
)


def test_pot_odds_basic() -> None:
    assert pot_odds(100, 25) == 0.2


def test_pot_odds_zero_call() -> None:
    assert pot_odds(100, 0) == 0.0


def test_needed_equity_matches_pot_odds() -> None:
    assert needed_equity(100, 25) == pot_odds(100, 25)


def test_expected_value_profitable() -> None:
    assert expected_value(0.6, 100, 20) > 0


def test_expected_value_unprofitable() -> None:
    assert expected_value(0.1, 100, 50) < 0


def test_is_profitable_call_good() -> None:
    assert is_profitable_call(0.75, 100, 25) is True


def test_is_profitable_call_bad() -> None:
    assert is_profitable_call(0.1, 100, 25) is False


def test_is_profitable_call_free() -> None:
    assert is_profitable_call(0.0, 100, 0) is True


def test_m_value_basic() -> None:
    assert m_value(300, 1, 2) == 100.0


def test_m_value_short() -> None:
    assert abs(m_value(10, 5, 10) - 0.667) < 0.001


def test_m_zone_deep() -> None:
    assert m_zone(25) == "deep"


def test_m_zone_comfortable() -> None:
    assert m_zone(15) == "comfortable"


def test_m_zone_caution() -> None:
    assert m_zone(8) == "caution"


def test_m_zone_danger() -> None:
    assert m_zone(4) == "danger"


def test_m_zone_desperate() -> None:
    assert m_zone(1) == "desperate"


def test_suggested_bet_size() -> None:
    assert suggested_bet_size(100, 0.55) == 55


def test_suggested_bet_size_minimum() -> None:
    assert suggested_bet_size(0, 0.55) == 1
