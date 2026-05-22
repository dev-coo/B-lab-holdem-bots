from __future__ import annotations

# Simplified Nash push/fold ranges by effective BB stack depth
# Maps: bb_depth → (push_top_percent, call_top_percent)
PUSH_FOLD_TABLE: dict[int, tuple[float, float]] = {
    3:  (0.85, 0.70),   # 3BB: push 85%, call 70%
    5:  (0.75, 0.55),
    7:  (0.65, 0.45),
    8:  (0.60, 0.40),
    10: (0.50, 0.35),
    12: (0.42, 0.30),
    15: (0.35, 0.25),
    20: (0.25, 0.18),
}


def get_push_range(effective_bb: float) -> float:
    """Get push range percentage for given effective BB stack depth."""
    bb_int = max(3, min(20, int(effective_bb)))
    if bb_int in PUSH_FOLD_TABLE:
        return PUSH_FOLD_TABLE[bb_int][0]
    # Interpolate between nearest entries
    keys = sorted(PUSH_FOLD_TABLE.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= bb_int <= keys[i + 1]:
            lower, upper = PUSH_FOLD_TABLE[keys[i]][0], PUSH_FOLD_TABLE[keys[i + 1]][0]
            frac = (bb_int - keys[i]) / (keys[i + 1] - keys[i])
            return lower + (upper - lower) * frac
    return 0.30  # default


def get_call_range(effective_bb: float) -> float:
    """Get call range percentage for given effective BB stack depth."""
    bb_int = max(3, min(20, int(effective_bb)))
    if bb_int in PUSH_FOLD_TABLE:
        return PUSH_FOLD_TABLE[bb_int][1]
    keys = sorted(PUSH_FOLD_TABLE.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= bb_int <= keys[i + 1]:
            lower, upper = PUSH_FOLD_TABLE[keys[i]][1], PUSH_FOLD_TABLE[keys[i + 1]][1]
            frac = (bb_int - keys[i]) / (keys[i + 1] - keys[i])
            return lower + (upper - lower) * frac
    return 0.20


def should_push(hand: list[str], effective_bb: float) -> bool:
    """Check if hand should be pushed given effective BB depth."""
    from holdem_agent.core.range_ import hand_in_range

    push_pct = get_push_range(effective_bb)
    return hand_in_range(hand, push_pct)


def should_call_push(hand: list[str], effective_bb: float) -> bool:
    """Check if hand should call a push given effective BB depth."""
    from holdem_agent.core.range_ import hand_in_range

    call_pct = get_call_range(effective_bb)
    return hand_in_range(hand, call_pct)
