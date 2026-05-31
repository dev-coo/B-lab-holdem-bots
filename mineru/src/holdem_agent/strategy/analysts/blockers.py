from __future__ import annotations

import dataclasses
from collections import Counter

from holdem_agent.strategy.analysts.hand_strength import RANK_VALUES

_HIGH_CARD_RANKS = {"A", "K", "Q"}


@dataclasses.dataclass(frozen=True)
class BlockerAnalysis:
    """How much our hole cards block likely opponent value hands."""

    blocker_score: float
    blocks_flush: bool
    blocks_straight: bool
    blocks_ace_high: bool
    nut_blocker_count: int


def analyze_blockers(hole_cards: list[str], community_cards: list[str]) -> BlockerAnalysis:
    """Detect blockers to flushes, straights, and ace-high value hands."""

    flush = _blocks_flush(hole_cards, community_cards)
    straight = _blocks_straight(hole_cards, community_cards)
    ace_high = any(card.startswith("A") for card in hole_cards)
    nut_blocker_count = sum((flush, straight, ace_high))
    score = _clamp((0.40 if flush else 0.0) + (0.35 if straight else 0.0) + (0.25 if ace_high else 0.0))

    return BlockerAnalysis(
        blocker_score=score,
        blocks_flush=flush,
        blocks_straight=straight,
        blocks_ace_high=ace_high,
        nut_blocker_count=nut_blocker_count,
    )


def blocker_strength(hole_cards: list[str], community_cards: list[str]) -> float:
    """Return only blocker strength from 0.0 to 1.0."""

    return analyze_blockers(hole_cards, community_cards).blocker_score


def _blocks_flush(hole_cards: list[str], community_cards: list[str]) -> bool:
    board_suits = [card[1] for card in community_cards if len(card) >= 2]
    if not board_suits:
        return False

    suit_counts = Counter(board_suits)
    likely_flush_suits = {suit for suit, count in suit_counts.items() if count >= 2}
    for card in hole_cards:
        if len(card) >= 2 and card[0] in _HIGH_CARD_RANKS and card[1] in likely_flush_suits:
            return True
    return False


def _blocks_straight(hole_cards: list[str], community_cards: list[str]) -> bool:
    board_ranks = _rank_values(community_cards)
    hole_ranks = set(_rank_values(hole_cards))
    if 14 in board_ranks:
        board_ranks.append(1)
    if 14 in hole_ranks:
        hole_ranks.add(1)

    board_rank_set = set(board_ranks)
    for start in range(1, 11):
        window = {start + offset for offset in range(5)}
        board_hits = window & board_rank_set
        if len(board_hits) >= 3 and hole_ranks & window:
            return True
    return False


def _rank_values(cards: list[str]) -> list[int]:
    return [RANK_VALUES[card[0]] for card in cards if len(card) >= 2 and card[0] in RANK_VALUES]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
