from __future__ import annotations

from holdem_agent.strategy.analysts.opponent import OpponentProfile, OpponentTracker


def test_opponent_profile_initial() -> None:
    profile = OpponentProfile(name="hero")

    assert profile.name == "hero"
    assert profile.hands_played == 0
    assert profile.vpip_count == 0
    assert profile.pfr_count == 0
    assert profile.raise_count == 0
    assert profile.bet_count == 0
    assert profile.fold_count == 0
    assert profile.call_count == 0
    assert profile.vpip == 0.0
    assert profile.pfr == 0.0
    assert profile.aggression_factor == 0.0
    assert profile.fold_percentage == 0.0
    assert profile.classify() == "tight-passive"


def test_opponent_profile_vpip() -> None:
    profile = OpponentProfile(name="hero", hands_played=10, vpip_count=4)

    assert profile.vpip == 0.4
    assert profile.vpip > 0.35


def test_opponent_profile_pfr() -> None:
    profile = OpponentProfile(name="hero", hands_played=8, pfr_count=3)

    assert profile.pfr == 0.375
    assert profile.pfr > 0.35


def test_opponent_profile_aggression_factor() -> None:
    profile = OpponentProfile(name="hero", raise_count=3, bet_count=2, call_count=2)

    assert profile.aggression_factor == 2.5


def test_opponent_profile_classify_tag() -> None:
    profile = OpponentProfile(name="hero", hands_played=20, vpip_count=2, raise_count=6, call_count=2)

    assert profile.vpip <= 0.35
    assert profile.aggression_factor > 1.5
    assert profile.classify() == "tight-aggressive"


def test_opponent_profile_classify_lag() -> None:
    profile = OpponentProfile(name="hero", hands_played=20, vpip_count=12, raise_count=10, call_count=5)

    assert profile.vpip > 0.35
    assert profile.aggression_factor > 1.5
    assert profile.classify() == "loose-aggressive"


def test_opponent_profile_classify_rock() -> None:
    profile = OpponentProfile(name="hero", hands_played=20, vpip_count=4, call_count=8, raise_count=2, bet_count=1)

    assert profile.vpip <= 0.35
    assert profile.aggression_factor <= 1.5
    assert profile.classify() == "tight-passive"


def test_opponent_profile_classify_fish() -> None:
    profile = OpponentProfile(name="hero", hands_played=20, vpip_count=12, call_count=12, raise_count=2, bet_count=1)

    assert profile.vpip > 0.35
    assert profile.aggression_factor <= 1.5
    assert profile.classify() == "loose-passive"


def test_opponent_tracker_record_action() -> None:
    tracker = OpponentTracker()

    tracker.record_action("alice", action="call", phase="preflop")

    profile = tracker.get_profile("alice")
    assert profile is not None
    assert profile.hands_played == 0
    assert profile.vpip_count == 1
    assert profile.call_count == 1
    assert profile.raise_count == 0
    assert profile.bet_count == 0
    assert profile.fold_count == 0



def test_opponent_tracker_record_hand() -> None:
    tracker = OpponentTracker()

    tracker.record_hand("alice")
    tracker.record_hand("alice")

    profile = tracker.get_profile("alice")
    assert profile is not None
    assert profile.hands_played == 2


def test_opponent_tracker_multiple_opponents() -> None:
    tracker = OpponentTracker()

    tracker.record_action("alice", action="bet", phase="flop")
    tracker.record_action("bob", action="fold", phase="preflop")

    alice = tracker.get_profile("alice")
    bob = tracker.get_profile("bob")

    assert alice is not None
    assert bob is not None
    assert alice.name == "alice"
    assert bob.name == "bob"
    assert alice.vpip_count == 1
    assert bob.vpip_count == 0
    assert bob.fold_count == 1


def test_opponent_tracker_get_or_create() -> None:
    tracker = OpponentTracker()

    first = tracker.get_or_create("alice")
    second = tracker.get_or_create("alice")

    assert first is second
    assert first.name == "alice"
    assert len(tracker.all_profiles) == 1
