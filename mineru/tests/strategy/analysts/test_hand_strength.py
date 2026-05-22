from __future__ import annotations

from holdem_agent.core.evaluator import HandResult
from holdem_agent.strategy.analysts.hand_strength import (
    draw_count,
    hand_strength,
    has_flush_draw,
    has_straight_draw,
    estimated_equity,
)


def test_hand_strength_returns_result() -> None:
    result = hand_strength(["Ah", "Kh"], ["2s", "7d", "Kc"])

    assert isinstance(result, HandResult)
    assert result.rank > 0
    assert result.rank_class
    assert 0.0 <= result.percentage <= 1.0


def test_has_flush_draw_true() -> None:
    assert has_flush_draw(["Ah", "Kh"], ["2h", "9h", "Kd"]) is True


def test_has_flush_draw_false() -> None:
    assert has_flush_draw(["Ah", "Kh"], ["2h", "9s", "Kd"]) is False


def test_has_straight_draw_open_ended() -> None:
    assert has_straight_draw(["9h", "Td"], ["Jc", "Qd", "2s"]) is True


def test_has_straight_draw_gutshot() -> None:
    assert has_straight_draw(["7h", "Ts"], ["8c", "Jd", "2s"]) is True


def test_has_straight_draw_false() -> None:
    assert has_straight_draw(["Ah", "7h"], ["2c", "9d", "Qh"]) is False


def test_draw_count_both() -> None:
    assert draw_count(["Ah", "Kh"], ["Qh", "Jh", "9h"]) == 2


def test_draw_count_none() -> None:
    assert draw_count(["As", "Kd"], ["Qc", "2h", "7d"]) == 0


def test_estimated_equity_range() -> None:
    equity = estimated_equity(["Ah", "Kd"], ["2s", "7d", "Kc"], num_opponents=1)

    assert 0.0 <= equity <= 1.0
