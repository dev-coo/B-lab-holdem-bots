from __future__ import annotations

import dataclasses
from collections import Counter

from holdem_agent.strategy.analysts.hand_strength import RANK_VALUES


@dataclasses.dataclass(frozen=True)
class BoardTextureAnalysis:
    """Summarizes how coordinated a public board is."""

    texture_score: float
    connectedness: float
    pairedness: float
    suitedness: float
    is_paired: bool
    is_monotone: bool
    is_two_tone: bool


def analyze_board_texture(community_cards: list[str]) -> BoardTextureAnalysis:
    """Analyze board wetness from 0.0=dry to 1.0=wet.

    Wet boards are connected, suited, or paired enough to create many strong made
    hands and draws. Empty/preflop boards are treated as dry.
    """

    ranks = _rank_values(community_cards)
    suits = [card[1] for card in community_cards if len(card) >= 2]
    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)

    connectedness = _connectedness(ranks)
    pairedness = _pairedness(rank_counts, len(ranks))
    suitedness = _suitedness(suit_counts, len(suits))
    texture_score = _clamp((connectedness * 0.45) + (suitedness * 0.40) + (pairedness * 0.15))

    return BoardTextureAnalysis(
        texture_score=texture_score,
        connectedness=connectedness,
        pairedness=pairedness,
        suitedness=suitedness,
        is_paired=any(count >= 2 for count in rank_counts.values()),
        is_monotone=bool(suit_counts) and max(suit_counts.values()) >= 3,
        is_two_tone=len(suit_counts) == 2 and max(suit_counts.values()) >= 2,
    )


def texture_score(community_cards: list[str]) -> float:
    """Return only the dry-to-wet texture score."""

    return analyze_board_texture(community_cards).texture_score


def _rank_values(cards: list[str]) -> list[int]:
    return [RANK_VALUES[card[0]] for card in cards if len(card) >= 2 and card[0] in RANK_VALUES]


def _connectedness(ranks: list[int]) -> float:
    unique_ranks = set(ranks)
    if len(unique_ranks) < 2:
        return 0.0

    if 14 in unique_ranks:
        unique_ranks.add(1)

    sorted_ranks = sorted(unique_ranks)
    close_links = 0
    total_links = max(1, len(sorted_ranks) - 1)
    for left, right in zip(sorted_ranks, sorted_ranks[1:]):
        if right - left <= 2:
            close_links += 1

    straight_windows = 0
    for start in range(1, 11):
        window = {start + offset for offset in range(5)}
        if len(window & unique_ranks) >= 3:
            straight_windows += 1

    link_score = close_links / total_links
    window_score = min(1.0, straight_windows / 3.0)
    return _clamp((link_score * 0.65) + (window_score * 0.35))


def _pairedness(rank_counts: Counter[int], card_count: int) -> float:
    if card_count == 0:
        return 0.0

    duplicate_cards = sum(count - 1 for count in rank_counts.values() if count > 1)
    return _clamp(duplicate_cards / max(1, card_count - 1))


def _suitedness(suit_counts: Counter[str], card_count: int) -> float:
    if card_count < 2 or not suit_counts:
        return 0.0

    max_suit_count = max(suit_counts.values())
    if max_suit_count < 2:
        return 0.0
    if max_suit_count >= 3:
        return _clamp(0.80 + ((max_suit_count - 3) * 0.10))
    return 0.45


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
