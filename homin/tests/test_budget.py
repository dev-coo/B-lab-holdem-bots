from __future__ import annotations

from holdem.meta.budget import BudgetLimits, BudgetTracker


def test_initial_allows_call():
    t = BudgetTracker()
    ok, reason = t.allow_call(room_id=1, hand_number=1)
    assert ok
    assert reason == "ok"


def test_per_hand_limit():
    t = BudgetTracker(limits=BudgetLimits(per_hand=1, per_game=10, per_minute=10, per_day=100))
    t.record_call(room_id=1, hand_number=1)
    ok, reason = t.allow_call(room_id=1, hand_number=1)
    assert not ok
    assert reason == "budget_hand"


def test_per_hand_limit_different_hand_ok():
    t = BudgetTracker(limits=BudgetLimits(per_hand=1, per_game=10, per_minute=10, per_day=100))
    t.record_call(room_id=1, hand_number=1)
    ok, _ = t.allow_call(room_id=1, hand_number=2)
    assert ok


def test_per_game_limit():
    t = BudgetTracker(limits=BudgetLimits(per_hand=10, per_game=2, per_minute=10, per_day=100))
    t.record_call(room_id=1, hand_number=1)
    t.record_call(room_id=1, hand_number=2)
    ok, reason = t.allow_call(room_id=1, hand_number=3)
    assert not ok
    assert reason == "budget_game"


def test_per_minute_limit():
    t = BudgetTracker(limits=BudgetLimits(per_hand=10, per_game=20, per_minute=2, per_day=100))
    t.record_call(now=100.0)
    t.record_call(now=110.0)
    ok, reason = t.allow_call(now=120.0)
    assert not ok
    assert reason == "budget_minute"
    # 70초 지나면 첫 기록 pruning → allow
    ok, _ = t.allow_call(now=180.0)
    assert ok


def test_per_day_limit():
    t = BudgetTracker(limits=BudgetLimits(per_hand=10, per_game=100, per_minute=100, per_day=1))
    t.record_call()
    ok, reason = t.allow_call()
    assert not ok
    assert reason == "budget_day"


def test_on_hand_end_resets_hand():
    t = BudgetTracker(limits=BudgetLimits(per_hand=1, per_game=10, per_minute=10, per_day=100))
    t.record_call(room_id=1, hand_number=1)
    t.on_hand_end(1, 1)
    ok, _ = t.allow_call(room_id=1, hand_number=1)
    assert ok


def test_on_game_end_resets_game():
    t = BudgetTracker(limits=BudgetLimits(per_hand=10, per_game=1, per_minute=10, per_day=100))
    t.record_call(room_id=1, hand_number=1)
    ok, _ = t.allow_call(room_id=1, hand_number=2)
    assert not ok
    t.on_game_end(1)
    ok, _ = t.allow_call(room_id=1, hand_number=2)
    assert ok


def test_from_yaml_loads_limits():
    t = BudgetTracker.from_yaml()
    # configs/llm.yaml 의 값 (per_hand_max_calls: 1)
    assert t.limits.per_hand == 1
    assert t.limits.per_game >= 1
