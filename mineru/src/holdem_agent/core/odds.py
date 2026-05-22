from __future__ import annotations


def pot_odds(pot: int, to_call: int) -> float:
    """Calculate pot odds as a ratio.

    Returns:
        Pot odds as a decimal (e.g. 0.25 means you need 25% equity to call).
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


def needed_equity(pot: int, to_call: int) -> float:
    """Minimum equity needed to make a call profitable.

    Same as pot_odds but more descriptive name.
    """
    return pot_odds(pot, to_call)


def expected_value(equity: float, pot: int, to_call: int) -> float:
    """Calculate EV of a call.

    Positive = profitable call, Negative = unprofitable.
    """
    win_amount = pot
    lose_amount = to_call
    return equity * win_amount - (1 - equity) * lose_amount


def is_profitable_call(equity: float, pot: int, to_call: int) -> bool:
    """Check if calling is +EV."""
    if to_call == 0:
        return True
    return equity >= needed_equity(pot, to_call)


def m_value(stack: int, small_blind: int, big_blind: int) -> float:
    """Calculate M-value (Harrington's M).

    M = stack / (SB + BB + antes). With no antes, M = stack / (SB + BB).
    """
    total_blinds = small_blind + big_blind
    if total_blinds <= 0:
        return float("inf")
    return stack / total_blinds


def m_zone(m: float) -> str:
    """Classify M-value into Harrington zones.

    Returns: 'deep' | 'comfortable' | 'caution' | 'danger' | 'desperate'
    """
    if m > 20:
        return "deep"
    if m > 10:
        return "comfortable"
    if m > 6:
        return "caution"
    if m > 2:
        return "danger"
    return "desperate"


def suggested_bet_size(pot: int, fraction: float = 0.55) -> int:
    """Calculate suggested bet size as fraction of pot.

    Args:
        pot: Current pot size
        fraction: Fraction of pot to bet (default 55% for c-bet)

    Returns:
        Bet amount in chips (minimum 1)
    """
    return max(1, int(pot * fraction))
