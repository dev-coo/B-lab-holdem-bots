from __future__ import annotations

from holdem_agent.strategy.analysts import position


def test_position_tier_late() -> None:
    assert position.position_tier("btn") == "late"
    assert position.position_tier("co") == "late"


def test_position_tier_middle() -> None:
    assert position.position_tier("hj") == "middle"


def test_position_tier_early() -> None:
    assert position.position_tier("utg") == "early"


def test_position_tier_blinds() -> None:
    assert position.position_tier("sb") == "blinds"
    assert position.position_tier("bb") == "blinds"


def test_position_tier_unknown() -> None:
    assert position.position_tier("unknown") == "middle"


def test_is_in_position_btn() -> None:
    assert position.is_in_position("btn", 2, []) is True


def test_is_in_position_utg() -> None:
    assert position.is_in_position("utg", 6, []) is False


def test_position_advantage_btn() -> None:
    assert position.position_advantage("btn") == 1.0


def test_position_advantage_utg() -> None:
    assert position.position_advantage("utg") == 0.35


def test_position_advantage_ordering() -> None:
    assert position.position_advantage("btn") > position.position_advantage("co")
    assert position.position_advantage("co") > position.position_advantage("hj")
    assert position.position_advantage("hj") > position.position_advantage("utg")


def test_position_range_adjustment_wider_on_btn() -> None:
    base = 0.8
    adjusted = position.position_range_adjustment("btn", base)
    assert adjusted < base


def test_position_range_adjustment_tighter_utg() -> None:
    base = 0.8
    adjusted = position.position_range_adjustment("utg", base)
    assert adjusted > base


def test_is_blind_true() -> None:
    assert position.is_blind("sb") is True


def test_is_blind_false() -> None:
    assert position.is_blind("btn") is False


def test_is_button_true() -> None:
    assert position.is_button("btn") is True
