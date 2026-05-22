import pytest
from treys import Card

from holdem_agent.core.card import (
    is_valid_card,
    server_hand_to_treys,
    server_to_treys,
    treys_hand_to_server,
    treys_to_server,
)


def test_server_to_treys_ace_hearts() -> None:
    expected = Card.new("Ah")
    actual = server_to_treys("Ah")

    assert actual == expected


def test_server_to_treys_ten_clubs() -> None:
    expected = Card.new("Tc")
    actual = server_to_treys("Tc")

    assert actual == expected


def test_server_to_treys_roundtrip() -> None:
    cards = ["Ah", "2s", "Tc", "Kd", "9d"]
    converted = [server_to_treys(card) for card in cards]
    restored = [treys_to_server(card) for card in converted]

    assert restored == cards


def test_server_hand_to_treys() -> None:
    cards = ["Ah", "Kh", "Qd", "Jc", "Ts"]

    expected = [server_to_treys(card) for card in cards]
    actual = server_hand_to_treys(cards)

    assert actual == expected


def test_is_valid_card() -> None:
    assert is_valid_card("Ah")
    assert is_valid_card("2s")
    assert is_valid_card("Tc")
    assert is_valid_card("Kd")

    assert not is_valid_card("Xz")
    assert not is_valid_card("Ahh")
    assert not is_valid_card("12")
    assert not is_valid_card("")


def test_invalid_card_raises() -> None:
    with pytest.raises(ValueError):
        server_to_treys("Xz")


def test_roundtrip_hand_helpers() -> None:
    cards = ["Ah", "2s", "Tc", "Kd", "9d"]
    treys_cards = [server_to_treys(card) for card in cards]
    restored = treys_hand_to_server(treys_cards)

    assert restored == cards
