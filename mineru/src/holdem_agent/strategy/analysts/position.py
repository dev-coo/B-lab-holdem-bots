from __future__ import annotations

# Position tiers for strategy adjustment
_LATE_POSITIONS = {"btn", "co"}
_MIDDLE_POSITIONS = {"hj", "mp", "mp1"}
_EARLY_POSITIONS = {"utg", "utg1"}
_BLINDS = {"sb", "bb"}


def position_tier(seat: str) -> str:
    """Classify position into tier: 'late' | 'middle' | 'early' | 'blinds'."""
    if seat in _LATE_POSITIONS:
        return "late"
    if seat in _MIDDLE_POSITIONS:
        return "middle"
    if seat in _EARLY_POSITIONS:
        return "early"
    if seat in _BLINDS:
        return "blinds"
    return "middle"  # default for unknown positions


def is_in_position(seat: str, num_players: int, action_history: list[dict] | None = None) -> bool:
    """Check if we're in position (acting last postflop).

    Simplified: BTN and CO are generally in position.
    """
    return seat in _LATE_POSITIONS


def position_advantage(seat: str) -> float:
    """Return position advantage multiplier (0.0-1.0).

    Late position = high advantage, early = low.
    """
    advantages = {
        "btn": 1.0,
        "co": 0.85,
        "hj": 0.65,
        "mp": 0.55,
        "mp1": 0.45,
        "utg": 0.35,
        "utg1": 0.30,
        "sb": 0.20,
        "bb": 0.40,
    }
    return advantages.get(seat, 0.5)


def position_range_adjustment(seat: str, base_threshold: float) -> float:
    """Adjust hand range threshold based on position.

    Late position = wider range (lower threshold)
    Early position = tighter range (higher threshold)
    """
    advantage = position_advantage(seat)
    # Scale threshold: late position reduces threshold by up to 15%
    # early position increases threshold by up to 20%
    adjustment = (0.5 - advantage) * 0.3
    return max(0.0, min(1.0, base_threshold + adjustment))


def is_blind(seat: str) -> bool:
    return seat in _BLINDS


def is_button(seat: str) -> bool:
    return seat == "btn"
