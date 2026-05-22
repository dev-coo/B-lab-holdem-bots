from __future__ import annotations

from holdem_agent.core.odds import m_value


def tournament_phase(hand_number: int, total_hands_estimate: int = 100) -> str:
    """Classify tournament phase based on hand number.

    Returns: 'early' | 'middle' | 'bubble' | 'late'
    """
    progress = hand_number / total_hands_estimate if total_hands_estimate > 0 else 0
    if progress < 0.2:
        return "early"
    if progress < 0.5:
        return "middle"
    if progress < 0.75:
        return "bubble"
    return "late"


def risk_tolerance(
    stack: int,
    small_blind: int,
    big_blind: int,
    phase: str = "middle",
) -> float:
    """Calculate risk tolerance (0.0-1.0).

    Low M = low tolerance (desperate).
    Early tournament = higher tolerance.
    """
    m = m_value(stack, small_blind, big_blind)
    base = min(1.0, m / 20.0)

    phase_adjustments = {
        "early": 1.1,
        "middle": 1.0,
        "bubble": 0.8,
        "late": 0.9,
    }
    adjustment = phase_adjustments.get(phase, 1.0)

    return max(0.0, min(1.0, base * adjustment))


def is_short_stack(stack: int, big_blind: int, threshold: int = 15) -> bool:
    """Check if stack is short (below threshold BBs)."""
    return stack < big_blind * threshold


def is_allin_candidate(
    stack: int,
    big_blind: int,
    equity: float,
    num_players: int = 2,
) -> bool:
    """Should we consider going all-in?

    Push/fold territory: stack < 15BB and equity > threshold.
    """
    bb_count = stack / big_blind if big_blind > 0 else 999

    if bb_count > 15:
        return False

    # Lower equity needed with fewer BBs
    equity_thresholds = {
        range(0, 6): 0.4,    # desperate: any reasonable hand
        range(6, 10): 0.5,   # short: need decent equity
        range(10, 15): 0.6,  # medium short: need good equity
    }

    for bb_range, threshold in equity_thresholds.items():
        if int(bb_count) in bb_range:
            return equity >= threshold

    return False


def stack_to_bb_ratio(stack: int, big_blind: int) -> float:
    """Calculate stack in BB units."""
    return stack / big_blind if big_blind > 0 else 0.0
