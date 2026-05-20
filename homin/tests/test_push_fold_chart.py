from __future__ import annotations

from holdem.decide.push_fold_chart import PushFoldChart, default_chart


def test_loads_from_yaml():
    chart = default_chart()
    assert chart.jam
    assert chart.hybrid_open
    assert chart.call_vs_jam


def test_jam_bucket_picks_smallest_matching_max_M():
    chart = default_chart()
    # M=1.5 → bucket with max_M=2.0 (any)
    b = chart.pick("jam", 1.5)
    assert b is not None
    assert b.max_M == 2.0


def test_any_two_when_very_short():
    chart = default_chart()
    b = chart.pick("jam", 1.0)
    assert b is not None
    assert b.lookup("72o", "LP") is True


def test_jam_AA_always_in():
    chart = default_chart()
    for m in (1.0, 3.0, 5.0, 7.0):
        b = chart.pick("jam", m)
        assert b is not None
        assert b.lookup("AA", "LP") is True


def test_jam_72o_not_in_mid_stack_EP():
    chart = default_chart()
    b = chart.pick("jam", 7.0)   # max_M=8.0 bucket
    assert b is not None
    assert b.lookup("72o", "EP") is False


def test_call_vs_jam_tight_at_high_m():
    chart = default_chart()
    b = chart.pick("call_vs_jam", 15.0)   # max_M=20 bucket (99+, AKs, AKo)
    assert b is not None
    assert b.lookup("AA", "LP") is True
    assert b.lookup("KQs", "LP") is False   # not in range


def test_hybrid_open_LP_wide():
    chart = default_chart()
    b = chart.pick("hybrid_open", 12.0)
    assert b is not None
    # LP (btn) 범위에 22 포함
    assert b.lookup("22", "LP") is True
    # EP 범위는 타이트 (22 불포함)
    assert b.lookup("22", "EP") is False


def test_pick_returns_none_above_all_buckets_without_catchall_for_hybrid():
    chart = default_chart()
    # hybrid_open 의 max_M=15 뿐, 그 이상은 None
    assert chart.pick("hybrid_open", 50.0) is None


def test_pick_has_catchall_for_call_vs_jam():
    chart = default_chart()
    # call_vs_jam 마지막 bucket 이 max_M=null (inf) → 항상 반환
    b = chart.pick("call_vs_jam", 999.0)
    assert b is not None
