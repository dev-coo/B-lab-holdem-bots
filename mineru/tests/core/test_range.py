from holdem_agent.core.range_ import (
    hand_in_range,
    hand_to_combo,
    classify_hand_strength,
    combo_rank,
    is_pair,
    is_suited,
)


def test_hand_to_combo_ak() -> None:
    assert hand_to_combo("A", "K") == "AK"


def test_hand_to_combo_ka() -> None:
    assert hand_to_combo("K", "A") == "AK"


def test_hand_to_combo_pair() -> None:
    assert hand_to_combo("A", "A") == "AA"


def test_is_suited_true() -> None:
    assert is_suited("Ah", "Kh")


def test_is_suited_false() -> None:
    assert not is_suited("Ah", "Ks")


def test_is_pair_true() -> None:
    assert is_pair("Ah", "Ad")


def test_is_pair_false() -> None:
    assert not is_pair("Ah", "Kh")


def test_combo_rank_aa_best() -> None:
    assert combo_rank("AA") == 0


def test_combo_rank_ordering() -> None:
    assert combo_rank("AK") < combo_rank("AQ") < combo_rank("AJ")


def test_hand_in_range_aa() -> None:
    assert hand_in_range(["Ah", "Ad"], 0.05)


def test_hand_in_range_72() -> None:
    assert not hand_in_range(["7d", "2c"], 0.05)


def test_classify_premium_pair() -> None:
    assert classify_hand_strength(["T", "T"], 0.05) == "premium"


def test_classify_medium_pair() -> None:
    assert classify_hand_strength(["5", "5"], 0.05) == "medium"


def test_classify_premium_ak() -> None:
    assert classify_hand_strength(["Ah", "Kh"], 0.05) == "premium"


def test_classify_weak() -> None:
    assert classify_hand_strength(["7d", "2c"], 0.05) == "weak"