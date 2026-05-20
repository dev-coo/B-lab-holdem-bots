from __future__ import annotations

from holdem.estimate.stat_updater import update_from_hand
from holdem.state.player_profile import PlayerProfile
from holdem.transport.protocol import HistoryEntry


def _h(phase, player, action, amount=0):
    return HistoryEntry(phase=phase, player=player, action=action, amount=amount)


def test_preflop_vpip_pfr_fold():
    # A raises (PFR), B calls (VPIP only), C folds (nothing)
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
        _h("preflop", "C", "fold"),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B", "C"])

    assert profiles["A"].vpip() == 1.0
    assert profiles["A"].pfr() == 1.0
    assert profiles["B"].vpip() == 1.0
    assert profiles["B"].pfr() == 0.0
    assert profiles["C"].vpip() == 0.0
    assert profiles["C"].pfr() == 0.0
    assert profiles["A"].hands_seen == 1


def test_three_bet_detection():
    # A opens, B 3bets, A folds to 3bet
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "raise", 18),
        _h("preflop", "A", "fold"),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B"])

    assert profiles["A"].get("THREE_BET").rate(default=0) == 0.0   # A didn't 3bet
    assert profiles["B"].get("THREE_BET").rate(default=0) == 1.0   # B did 3bet
    assert profiles["A"].get("FOLD_TO_THREE_BET").rate(default=0) == 1.0


def test_cbet_and_fold_to_cbet():
    # A raises PF (aggressor), B calls. Flop: A bets, B folds → cbet + fold_to_cbet
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
        _h("flop", "A", "raise", 8),     # cbet
        _h("flop", "B", "fold"),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B"])

    assert profiles["A"].get("CBET").rate(default=0) == 1.0
    assert profiles["B"].get("FOLD_TO_CBET").rate(default=0) == 1.0


def test_cbet_opp_only_when_pfr_aggressor():
    # B raises PF, A calls. On flop A bets first — this is NOT a cbet (A wasn't aggressor).
    history = [
        _h("preflop", "B", "raise", 6),
        _h("preflop", "A", "call", 6),
        _h("flop", "A", "raise", 8),
        _h("flop", "B", "call", 8),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B"])

    # A 는 PFR 아님 → CBET metric 갱신 안 됨
    assert profiles["A"].get("CBET").n_obs == 0
    # B 는 PFR 이지만 cbet 기회 있었는데 체크 안 했음... 사실 B 가 call 했으므로 cbet 기회 자체 미발생.
    # 우리 구현: pfr_aggressor=B, flop 에서 B 의 첫 액션은 call → cbet=False 로 관측.
    # 다만 "first bet on street" 은 A 가 먼저 했으므로 is_first_bet_on_street = True for A only.
    # B 의 경우 cbet_opp=False — 관측 없음. 이는 구현의 한계이지만 첫 설계로 허용.


def test_aggression_factor():
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
        _h("flop", "A", "raise", 8),
        _h("flop", "B", "call", 8),
        _h("turn", "A", "raise", 16),
        _h("turn", "B", "call", 16),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B"])

    # AF 는 postflop 만 집계 (PFR 과 분리).
    # A: flop raise + turn raise = 2, 0 call. B: 0 raise, 2 postflop call.
    assert profiles["A"].aggression.aggressive == 2
    assert profiles["A"].aggression.passive == 0
    assert profiles["B"].aggression.aggressive == 0
    assert profiles["B"].aggression.passive == 2


def test_empty_history_just_increments_hands():
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, [], participants=["A", "B"])
    assert profiles["A"].hands_seen == 1
    assert profiles["B"].hands_seen == 1
    # 아무 metric 도 관측 안 됨
    assert profiles["A"].get("VPIP").n_obs == 1   # VPIP 는 기회 부여됨 (False 관측)


def test_multiple_hands_accumulate():
    profiles: dict[str, PlayerProfile] = {}
    # Hand 1: A vpip+pfr, B vpip only
    update_from_hand(profiles, [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
    ], participants=["A", "B"])
    # Hand 2: A fold, B fold
    update_from_hand(profiles, [
        _h("preflop", "A", "fold"),
        _h("preflop", "B", "fold"),
    ], participants=["A", "B"])

    # A: 1/2 VPIP, 1/2 PFR
    assert profiles["A"].vpip() == 0.5
    assert profiles["A"].pfr() == 0.5
    # B: 1/2 VPIP, 0/2 PFR
    assert profiles["B"].vpip() == 0.5
    assert profiles["B"].pfr() == 0.0
    assert profiles["A"].hands_seen == 2


def test_check_raise():
    history = [
        _h("preflop", "A", "raise", 6),
        _h("preflop", "B", "call", 6),
        _h("flop", "B", "check"),
        _h("flop", "A", "raise", 8),
        _h("flop", "B", "raise", 24),       # check-raise
        _h("flop", "A", "fold"),
    ]
    profiles: dict[str, PlayerProfile] = {}
    update_from_hand(profiles, history, participants=["A", "B"])

    assert profiles["B"].get("CHECK_RAISE").rate(default=0) == 1.0
