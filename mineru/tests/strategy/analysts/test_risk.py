from __future__ import annotations

from holdem_agent.strategy.analysts.risk import (
    is_allin_candidate,
    is_short_stack,
    risk_tolerance,
    stack_to_bb_ratio,
    tournament_phase,
)


def test_tournament_phase_early() -> None:
    assert tournament_phase(hand_number=1) == "early"


def test_tournament_phase_middle() -> None:
    assert tournament_phase(hand_number=40) == "middle"


def test_tournament_phase_bubble() -> None:
    assert tournament_phase(hand_number=60) == "bubble"


def test_tournament_phase_late() -> None:
    assert tournament_phase(hand_number=90) == "late"


def test_risk_tolerance_high_stack() -> None:
    tolerance = risk_tolerance(stack=3000, small_blind=50, big_blind=100, phase="early")
    assert tolerance >= 0.9
    assert tolerance <= 1.0


def test_risk_tolerance_low_stack() -> None:
    tolerance = risk_tolerance(stack=300, small_blind=50, big_blind=100, phase="early")
    assert 0.0 <= tolerance < 0.3


def test_risk_tolerance_phase_adjustment() -> None:
    stack = 2000
    middle = risk_tolerance(stack=stack, small_blind=50, big_blind=100, phase="middle")
    bubble = risk_tolerance(stack=stack, small_blind=50, big_blind=100, phase="bubble")
    assert bubble < middle


def test_is_short_stack_true() -> None:
    assert is_short_stack(stack=1000, big_blind=100) is True


def test_is_short_stack_false() -> None:
    assert is_short_stack(stack=3000, big_blind=100) is False


def test_is_allin_candidate_desperate() -> None:
    assert is_allin_candidate(stack=500, big_blind=100, equity=0.45, num_players=2) is True


def test_is_allin_candidate_not_short() -> None:
    assert is_allin_candidate(stack=2000, big_blind=100, equity=0.95, num_players=2) is False


def test_is_allin_candidate_weak_hand() -> None:
    assert is_allin_candidate(stack=500, big_blind=100, equity=0.20, num_players=2) is False


def test_stack_to_bb_ratio() -> None:
    assert stack_to_bb_ratio(stack=300, big_blind=2) == 150.0
