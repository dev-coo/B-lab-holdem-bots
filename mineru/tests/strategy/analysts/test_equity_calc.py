from __future__ import annotations

from holdem_agent.core.odds import needed_equity
from holdem_agent.strategy.analysts.equity_calc import (
    calculate_ev,
    get_m_zone,
    is_push_fold,
    raise_amount,
    should_call,
    should_raise,
)


def test_should_call_profitable() -> None:
    assert should_call(equity=0.8, pot=100, to_call=20)


def test_should_call_unprofitable() -> None:
    assert not should_call(equity=0.1, pot=100, to_call=20)


def test_should_call_with_margin() -> None:
    pot = 100
    to_call = 50
    threshold = needed_equity(pot, to_call) + 0.05

    assert not should_call(equity=threshold - 0.005, pot=pot, to_call=to_call)
    assert should_call(equity=threshold + 0.01, pot=pot, to_call=to_call)


def test_should_raise_strong() -> None:
    assert should_raise(equity=0.8, pot=100, min_raise=20)


def test_should_raise_weak() -> None:
    assert not should_raise(equity=0.2, pot=100, min_raise=20)


def test_raise_amount_normal() -> None:
    assert raise_amount(equity=0.8, pot=200, min_raise=40) == 110


def test_raise_amount_minimum() -> None:
    assert raise_amount(equity=0.8, pot=50, min_raise=100) == 100


def test_get_m_zone_deep() -> None:
    assert get_m_zone(stack=3000, small_blind=25, big_blind=50) == "deep"


def test_get_m_zone_desperate() -> None:
    assert get_m_zone(stack=100, small_blind=25, big_blind=100) == "desperate"


def test_is_push_fold_true() -> None:
    assert is_push_fold(stack=1000, small_blind=100, big_blind=100)


def test_is_push_fold_false() -> None:
    assert not is_push_fold(stack=5000, small_blind=25, big_blind=50)


def test_calculate_ev_positive() -> None:
    assert calculate_ev(equity=0.8, pot=100, to_call=20) > 0


def test_calculate_ev_negative() -> None:
    assert calculate_ev(equity=0.1, pot=100, to_call=20) < 0
