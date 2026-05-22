from __future__ import annotations

from holdem_agent.core.odds import (
    expected_value,
    m_value,
    m_zone,
    needed_equity,
    suggested_bet_size,
)


def should_call(equity: float, pot: int, to_call: int, margin: float = 0.05) -> bool:
    """Decide if calling is profitable with a safety margin."""
    return equity >= needed_equity(pot, to_call) + margin


def should_raise(equity: float, pot: int, min_raise: int, aggression: float = 0.5) -> bool:
    """Decide if raising is appropriate based on equity and aggression."""
    return equity > (0.5 + aggression * 0.3)


def raise_amount(equity: float, pot: int, min_raise: int, fraction: float = 0.55) -> int:
    """Calculate raise amount based on equity and pot fraction."""
    base = suggested_bet_size(pot, fraction)
    if base < min_raise:
        return min_raise
    return base


def get_m_zone(stack: int, small_blind: int, big_blind: int) -> str:
    """Get current Harrington M-zone."""
    return m_zone(m_value(stack, small_blind, big_blind))


def is_push_fold(stack: int, small_blind: int, big_blind: int, threshold: float = 10.0) -> bool:
    """Check if we're in push/fold mode (M below threshold)."""
    return m_value(stack, small_blind, big_blind) <= threshold


def calculate_ev(equity: float, pot: int, to_call: int) -> float:
    """Public wrapper for EV calculation."""
    return expected_value(equity, pot, to_call)
