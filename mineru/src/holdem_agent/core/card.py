from __future__ import annotations

from treys import Card

RANKS = "23456789TJQKA"
SUITS = "shdc"


def is_valid_card(card: str) -> bool:
    if len(card) != 2:
        return False

    rank, suit = card[0], card[1]
    return rank in RANKS and suit in SUITS


def server_to_treys(card: str) -> int:
    if not is_valid_card(card):
        raise ValueError(f"Invalid card: {card}")

    return Card.new(card)


def treys_to_server(card_int: int) -> str:
    return Card.int_to_str(card_int)


def server_hand_to_treys(cards: list[str]) -> list[int]:
    return [server_to_treys(card) for card in cards]


def treys_hand_to_server(cards: list[int]) -> list[str]:
    return [treys_to_server(card) for card in cards]
