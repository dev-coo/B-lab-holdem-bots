from __future__ import annotations

from holdem_agent.strategy.charts.preflop import get_3bet_range, get_call_range, get_open_range
from holdem_agent.strategy.charts.pushfold import get_call_range as get_pushfold_call_range
from holdem_agent.strategy.charts.pushfold import get_push_range, should_call_push, should_push


def test_preflop_open_range_btn() -> None:
    assert get_open_range("btn") == 0.42


def test_preflop_open_range_utg() -> None:
    assert get_open_range("utg") == 0.14


def test_preflop_3bet_range_btn() -> None:
    assert get_3bet_range("btn") > get_3bet_range("utg")


def test_preflop_call_range_bb() -> None:
    assert get_call_range("bb") == 0.35


def test_preflop_unknown_position() -> None:
    assert get_open_range("unknown") == 0.20
    assert get_3bet_range("unknown") == 0.08
    assert get_call_range("unknown") == 0.15


def test_pushfold_push_short() -> None:
    assert get_push_range(5) == 0.75


def test_pushfold_push_deep() -> None:
    assert get_push_range(15) == 0.35


def test_pushfold_call_short() -> None:
    assert get_pushfold_call_range(5) == 0.55


def test_pushfold_call_interpolation() -> None:
    # Between 8BB (0.40) and 10BB (0.35) -> 9BB is 0.375
    assert get_pushfold_call_range(9) == 0.375


def test_should_push_aa() -> None:
    assert should_push(["Ah", "Ad"], 10) is True


def test_should_push_72_deep() -> None:
    assert should_push(["7d", "2c"], 15) is False


def test_should_call_push_aa() -> None:
    assert should_call_push(["Ah", "Ad"], 10) is True


def test_pushfold_clamped() -> None:
    assert get_push_range(2.5) == 0.85
    assert get_push_range(25) == 0.25
    assert get_pushfold_call_range(2.5) == 0.70
    assert get_pushfold_call_range(25) == 0.18
