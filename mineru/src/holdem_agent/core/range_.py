from __future__ import annotations

RANKS = "23456789TJQKA"
RANK_MAP = {r: i for i, r in enumerate(RANKS)}  # 2=0, A=12


def hand_to_combo(card1: str, card2: str) -> str:
    """Convert two card ranks to a canonical combo string.

    Examples:
        "A", "K" -> "AK"  (suited or offsuit handled separately)
        "K", "A" -> "AK"  (always high card first)
        "A", "A" -> "AA"  (pair)
    """
    r1, r2 = card1[0].upper(), card2[0].upper()
    if RANK_MAP[r1] < RANK_MAP[r2]:
        r1, r2 = r2, r1
    return r1 + r2


def is_suited(card1: str, card2: str) -> bool:
    """Check if two cards are suited."""
    return len(card1) >= 2 and len(card2) >= 2 and card1[1] == card2[1]


def is_pair(card1: str, card2: str) -> bool:
    """Check if two cards form a pair."""
    return card1[0] == card2[0]


def combo_rank(combo: str) -> int:
    """Rank a 2-char combo string (higher = better hand).

    AA=0 (best), 72o=168 (worst) — there are 169 unique combos.
    Pairs ranked first, then suited, then offsuit.
    """
    r1 = RANK_MAP.get(combo[0].upper(), -1)
    r2 = RANK_MAP.get(combo[1].upper(), -1)
    if r1 < r2:
        r1, r2 = r2, r1

    # Pair ranking: AA=0, KK=1, ..., 22=12
    if r1 == r2:
        return 12 - r1

    # Non-pair: 13*12/2 = 78 combinations for suited, 78 for offsuit
    pair_offset = 13
    high = r1
    low = r2
    non_pair_index = 0
    for h in range(12, 0, -1):  # A down to 2
        for low_rank in range(h - 1, -1, -1):
            if h == high and low_rank == low:
                return pair_offset + non_pair_index
            non_pair_index += 1

    return 168  # fallback


def hand_in_range(hand: list[str], top_percent: float) -> bool:
    """Check if a 2-card hand is in the top X% of hands.

    Args:
        hand: Two card strings like ["Ah", "Ks"]
        top_percent: 0.0-1.0, percentage of best hands to include

    There are 169 unique hand combos. top_percent=0.1 means top ~17 combos.
    """
    if len(hand) != 2:
        return False

    c1, c2 = hand[0], hand[1]
    combo = hand_to_combo(c1, c2)
    rank = combo_rank(combo)

    # Suit bonus: suited hands are slightly better
    suit_bonus = -1 if is_suited(c1, c2) and not is_pair(c1, c2) else 0
    adjusted_rank = rank + suit_bonus

    max_rank = int(169 * top_percent)
    return adjusted_rank < max_rank


def classify_hand_strength(hand: list[str], top_percent: float) -> str:
    """Classify hand as premium/strong/medium/weak.

    Args:
        hand: Two card strings
        top_percent: Threshold for current range (e.g. from genome)
    """
    c1, c2 = hand[0], hand[1]

    if is_pair(c1, c2):
        rank_val = RANK_MAP[c1[0]]
        if rank_val >= RANK_MAP["T"]:  # TT+
            return "premium"
        if rank_val >= RANK_MAP["7"]:  # 77+
            return "strong"
        return "medium"

    combo = hand_to_combo(c1, c2)
    high = RANK_MAP[combo[0]]
    low = RANK_MAP[combo[1]]

    suited = is_suited(c1, c2)

    # AK, AQ
    if high == RANK_MAP["A"] and low >= RANK_MAP["Q"]:
        return "premium"
    # AJ, AT, KQ
    if high == RANK_MAP["A"] and low >= RANK_MAP["T"]:
        return "strong"
    if high == RANK_MAP["K"] and low >= RANK_MAP["Q"]:
        return "strong"

    # Suited connectors and one-gappers above 7
    if suited and high >= RANK_MAP["9"] and low >= RANK_MAP["7"]:
        return "medium"

    if hand_in_range(hand, top_percent):
        return "medium"

    return "weak"