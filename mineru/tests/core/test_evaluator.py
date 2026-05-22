import pytest

from holdem_agent.core.evaluator import HandResult, evaluate_hand, hand_rank_name, hand_strength_percentage


def test_evaluate_hand_three_of_a_kind() -> None:
    result = evaluate_hand(["Ah", "Kh"], ["Ks", "Kd", "Qh"])

    assert result == HandResult(rank=result.rank, rank_class="Three of a Kind", percentage=result.percentage)
    assert result.rank_class == "Three of a Kind"


def test_evaluate_hand_full_house() -> None:
    result = evaluate_hand(["Ah", "Ad"], ["Ac", "Ks", "Kd"])

    assert result.rank_class == "Full House"


def test_evaluate_hand_flush() -> None:
    result = evaluate_hand(["Ah", "Kh"], ["Qh", "Jh", "9h"])

    assert result.rank_class == "Flush"


def test_evaluate_hand_straight() -> None:
    result = evaluate_hand(["Ah", "Kh"], ["Qd", "Jd", "Ts", "9d", "2c"])

    assert result.rank_class == "Straight"


def test_evaluate_hand_high_card() -> None:
    result = evaluate_hand(["Ah", "Kd"], ["Qh", "9s", "8d", "7c", "3s"])

    assert result.rank_class == "High Card"


@pytest.mark.parametrize(
    "hole_cards, community_cards, expected",
    [
        (["Ah", "Kh"], ["Ks", "Kd", "Qh"], "Three of a Kind"),
        (["Ah", "Ad"], ["Ac", "Ks", "Kd"], "Full House"),
        (["Ah", "Kh"], ["Qh", "Jh", "9h"], "Flush"),
        (["Ah", "Kh"], ["Qd", "Jd", "Ts", "9d", "2c"], "Straight"),
        (["Ah", "Kd"], ["Qh", "9s", "8d", "7c", "3s"], "High Card"),
    ],
)
def test_hand_rank_name_matches_class(
    hole_cards: list[str],
    community_cards: list[str],
    expected: str,
) -> None:
    result = evaluate_hand(hole_cards, community_cards)

    assert hand_rank_name(result.rank) == expected


def test_hand_strength_percentage_between_zero_and_one() -> None:
    strong = hand_strength_percentage(["Ah", "Kh"], ["Qh", "Jh", "Th", "9d", "2d"])
    weak = hand_strength_percentage(["7c", "2d"], ["3h", "4s", "8c", "Jd", "Ks"])

    assert 0.0 <= strong <= 1.0
    assert 0.0 <= weak <= 1.0
    assert strong > weak


def test_evaluate_hand_rejects_wrong_hole_card_count() -> None:
    with pytest.raises(ValueError):
        evaluate_hand(["Ah"], ["2s", "3d", "4c"])


def test_evaluate_hand_rejects_wrong_community_card_count() -> None:
    with pytest.raises(ValueError):
        evaluate_hand(["Ah", "Kh"], ["As", "Ks"])


def test_preflop_evaluation_uses_placeholder_board() -> None:
    result = evaluate_hand(["Ah", "Kh"], [])

    assert isinstance(result, HandResult)
    assert 0.0 <= result.percentage <= 1.0


def test_preflop_evaluation_uses_unique_placeholder_cards() -> None:
    result = evaluate_hand(["2c", "3d"], [])

    assert isinstance(result, HandResult)
    assert 0.0 <= result.percentage <= 1.0
