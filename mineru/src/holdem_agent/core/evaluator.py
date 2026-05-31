from __future__ import annotations

import dataclasses

from treys import Card, Evaluator

from holdem_agent.core.card import server_to_treys, server_hand_to_treys


_evaluator = Evaluator()

_BEST_TREYS_RANK = 1
_WORST_TREYS_RANK = 7462
_EMPTY_BOARD_PLACEHOLDERS = [
    Card.new("2c"),
    Card.new("3d"),
    Card.new("4h"),
    Card.new("5s"),
    Card.new("6c"),
    Card.new("7d"),
    Card.new("8h"),
    Card.new("9c"),
    Card.new("Ts"),
    Card.new("Jc"),
    Card.new("Qh"),
    Card.new("Kd"),
    Card.new("Ad"),
]


@dataclasses.dataclass(frozen=True)
class HandResult:
    rank: int
    rank_class: str
    percentage: float


def hand_rank_name(rank: int) -> str:
    rank_class = _evaluator.get_rank_class(rank)

    return _evaluator.class_to_string(rank_class)


def _validate_inputs(hole_cards: list[str], community_cards: list[str]) -> None:
    if len(hole_cards) != 2:
        raise ValueError("Expected exactly 2 hole cards")

    if len(community_cards) not in {0, 3, 4, 5}:
        raise ValueError("Expected 0, 3, 4, or 5 community cards")


def _fill_preflop_board(hole_cards_treys: list[int]) -> list[int]:
    board_cards: list[int] = []

    for card in _EMPTY_BOARD_PLACEHOLDERS:
        if card not in hole_cards_treys:
            board_cards.append(card)
            if len(board_cards) == 3:
                break

    if len(board_cards) != 3:
        raise AssertionError("Not enough placeholder cards to build preflop board")

    return board_cards


def evaluate_hand(hole_cards: list[str], community_cards: list[str]) -> HandResult:
    _validate_inputs(hole_cards, community_cards)

    hole_cards_treys = [server_to_treys(card) for card in hole_cards]
    community_cards_treys = server_hand_to_treys(community_cards)

    if len(community_cards_treys) == 0:
        # Evaluate against a deterministic placeholder board for preflop hand handling.
        # This keeps evaluation total-card count at 5 and preserves function stability.
        community_cards_treys = _fill_preflop_board(hole_cards_treys)

    rank = _evaluator.evaluate(hole_cards_treys, community_cards_treys)
    rank_class = hand_rank_name(rank)
    percentage = (_WORST_TREYS_RANK - rank) / (_WORST_TREYS_RANK - _BEST_TREYS_RANK)

    return HandResult(rank=rank, rank_class=rank_class, percentage=percentage)


def hand_strength_percentage(hole_cards: list[str], community_cards: list[str]) -> float:
    return evaluate_hand(hole_cards, community_cards).percentage
