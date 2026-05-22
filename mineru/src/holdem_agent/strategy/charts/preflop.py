from __future__ import annotations

# Simplified preflop opening ranges by position (top X% of hands)
# These are conservative approximations of GTO ranges
PREFLOP_OPEN_RANGES: dict[str, float] = {
    "utg": 0.14,   # ~14% of hands
    "utg1": 0.16,
    "mp": 0.18,
    "mp1": 0.20,
    "hj": 0.24,
    "co": 0.30,
    "btn": 0.42,
    "sb": 0.35,
    "bb": 0.45,    # BB defends wide
}

# 3-bet ranges (for facing an open)
PREFLOP_3BET_RANGES: dict[str, float] = {
    "utg": 0.05,
    "utg1": 0.05,
    "mp": 0.06,
    "mp1": 0.07,
    "hj": 0.08,
    "co": 0.10,
    "btn": 0.12,
    "sb": 0.09,
    "bb": 0.10,
}

# Call vs open ranges
PREFLOP_CALL_RANGES: dict[str, float] = {
    "utg": 0.08,
    "utg1": 0.09,
    "mp": 0.10,
    "mp1": 0.12,
    "hj": 0.15,
    "co": 0.20,
    "btn": 0.28,
    "sb": 0.22,
    "bb": 0.35,
}


def get_open_range(seat: str) -> float:
    """Get preflop opening range percentage for a seat."""
    return PREFLOP_OPEN_RANGES.get(seat, 0.20)


def get_3bet_range(seat: str) -> float:
    """Get 3-betting range percentage for a seat."""
    return PREFLOP_3BET_RANGES.get(seat, 0.08)


def get_call_range(seat: str) -> float:
    """Get calling range percentage for a seat."""
    return PREFLOP_CALL_RANGES.get(seat, 0.15)
