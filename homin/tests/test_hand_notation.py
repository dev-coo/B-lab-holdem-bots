from __future__ import annotations

import pytest

from holdem.decide.hand_notation import (
    all_hands,
    canonicalize_hand,
    expand_range,
)


def test_pair():
    assert canonicalize_hand("Ah", "As") == "AA"
    assert canonicalize_hand("2d", "2c") == "22"


def test_suited_high_first():
    assert canonicalize_hand("Kh", "Ah") == "AKs"
    assert canonicalize_hand("7s", "9s") == "97s"


def test_offsuit_high_first():
    assert canonicalize_hand("7d", "2c") == "72o"
    assert canonicalize_hand("Ah", "Kc") == "AKo"


def test_invalid_rank():
    with pytest.raises(ValueError):
        canonicalize_hand("1h", "Kh")


def test_duplicate_card():
    with pytest.raises(ValueError):
        canonicalize_hand("Ah", "Ah")


def test_all_hands_count():
    assert len(all_hands()) == 169   # 13 pairs + 78 suited + 78 offsuit


def test_expand_pair_single():
    assert expand_range("AA") == {"AA"}


def test_expand_pair_range():
    assert expand_range("22+") == {r + r for r in "23456789TJQKA"}


def test_expand_TT_plus():
    assert expand_range("TT+") == {"TT", "JJ", "QQ", "KK", "AA"}


def test_expand_suited_range():
    assert expand_range("A2s+") == {"A2s", "A3s", "A4s", "A5s", "A6s", "A7s",
                                    "A8s", "A9s", "ATs", "AJs", "AQs", "AKs"}


def test_expand_offsuit_range():
    assert expand_range("KTo+") == {"KTo", "KJo", "KQo"}


def test_expand_any():
    assert expand_range("any") == all_hands()


def test_expand_multi_token():
    out = expand_range("22+, A2s+, KTo+")
    assert "AA" in out
    assert "22" in out
    assert "AKs" in out
    assert "A2s" in out
    assert "KTo" in out
    assert "KJo" in out
    assert "99" in out


def test_expand_invalid_token():
    with pytest.raises(ValueError):
        expand_range("ZZZ+")
