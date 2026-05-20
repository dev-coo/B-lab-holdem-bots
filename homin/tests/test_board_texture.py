from __future__ import annotations

import pytest

from holdem.estimate.board_texture import analyze


def test_dry_rainbow_high_card():
    # K 7 2 rainbow — 전형적 dry 보드.
    t = analyze(["Kh", "7d", "2c"])
    assert not t.paired
    assert not t.monotone
    assert t.rainbow
    assert t.connectedness < 0.3
    assert t.wetness < 0.3
    assert t.high_card == "K"
    assert t.range_advantage_hint > 0.3


def test_monotone_wet_board():
    # J-9-8 monotone (플러시 + 스트레이트 가능성) — 매우 wet.
    t = analyze(["Jh", "9h", "8h"])
    assert t.monotone
    assert not t.two_tone
    assert t.connectedness > 0.7
    assert t.wetness > 0.7


def test_paired_board():
    t = analyze(["8c", "8d", "2s"])
    assert t.paired
    assert not t.trips_on_board
    # 페어 보드 → PFR 이점 감쇠
    assert abs(t.range_advantage_hint) < 0.25


def test_trips_on_board_damps_wetness():
    t = analyze(["7s", "7h", "7d"])
    assert t.trips_on_board
    assert t.wetness <= 0.25


def test_two_tone_moderate():
    t = analyze(["As", "Ts", "3d"])
    assert t.two_tone
    assert not t.monotone
    # flush factor 0.6 → wetness ≥ 0.3 (two-tone 최저선).
    assert t.wetness >= 0.3
    assert t.wetness < 0.7


def test_low_connected_caller_advantage():
    # 5-6-7 low 커넥티드 → PFR 이점 없음, caller/BB 이점.
    t = analyze(["5c", "6d", "7h"])
    assert t.range_advantage_hint < 0


def test_turn_card_extends():
    t = analyze(["Jh", "9h", "8h", "2c"])
    assert t.n_cards == 4
    assert t.monotone   # 여전히 3장은 같은 무늬


def test_river_card_all_five():
    t = analyze(["Jh", "9h", "8h", "2c", "Qd"])
    assert t.n_cards == 5
    assert t.high_card == "Q"


def test_too_few_cards_raises():
    with pytest.raises(ValueError):
        analyze(["As", "Kd"])


def test_too_many_cards_raises():
    with pytest.raises(ValueError):
        analyze(["As", "Kd", "Qc", "Jh", "Ts", "9s"])


def test_ace_high_dry():
    t = analyze(["Ad", "8c", "3h"])
    assert t.rainbow
    assert t.high_card == "A"
    assert t.range_advantage_hint > 0.2
