from __future__ import annotations

from collections import Counter

from holdem_agent.core.evaluator import HandResult, evaluate_hand
from holdem_agent.core.equity import monte_carlo_equity


RANK_VALUES = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}


def hand_strength(hole_cards: list[str], community_cards: list[str]) -> HandResult:
    """Evaluate current hand strength. Delegates to core/evaluator."""

    return evaluate_hand(hole_cards, community_cards)


def has_flush_draw(hole_cards: list[str], community_cards: list[str]) -> bool:
    """Check if we have a flush draw (4 cards of same suit with 2 hole + community)."""

    all_cards = hole_cards + community_cards
    suits = [c[1] for c in all_cards if len(c) >= 2]
    counts = Counter(suits)
    return any(count >= 4 for count in counts.values())


def has_straight_draw(hole_cards: list[str], community_cards: list[str]) -> bool:
    """Check if we have an open-ended or gutshot straight draw."""

    all_cards = hole_cards + community_cards
    ranks = {RANK_VALUES.get(c[0], 0) for c in all_cards}
    ranks.discard(0)

    if 14 in ranks:
        ranks.add(1)

    # Search all 5-card straight windows for exactly one missing rank.
    for start in range(1, 11):
        window = {start + i for i in range(5)}
        missing = window - ranks
        if len(missing) == 1:
            return True

    return False


def draw_count(hole_cards: list[str], community_cards: list[str]) -> int:
    """Count number of draws (flush + straight draws)."""

    count = 0
    if has_flush_draw(hole_cards, community_cards):
        count += 1
    if has_straight_draw(hole_cards, community_cards):
        count += 1
    return count


def estimated_equity(hole_cards: list[str], community_cards: list[str], num_opponents: int = 1) -> float:
    """Quick equity estimate. Uses fewer simulations for speed."""

    simulations = 500 if len(community_cards) <= 3 else 300
    return monte_carlo_equity(hole_cards, community_cards, num_opponents, simulations)
