"""M ratio 골든 케이스."""
from __future__ import annotations

import math

from holdem.math.m_ratio import compute_m


def test_lv1_deep_stack():
    # 시작 스택 300, SB=1, BB=2 → M = 100
    assert compute_m(300, 1, 2) == 100.0


def test_lv10_mid():
    # SB=50, BB=100 → 300 / 150 = 2 (이미 short)
    assert compute_m(300, 50, 100) == 2.0


def test_lv20_micro():
    # SB=3000, BB=6000 → 300 / 9000 ≈ 0.033
    assert compute_m(300, 3000, 6000) == pytest_approx_eq(0.0333, 3)


def test_zero_blinds_returns_inf():
    assert math.isinf(compute_m(300, 0, 0))


def test_negative_stack_clamped_to_zero():
    assert compute_m(-5, 1, 2) == 0.0


def pytest_approx_eq(value: float, precision: int):
    class _Matcher(float):
        def __eq__(self, other):
            return abs(other - value) < 10 ** (-precision)

    return _Matcher(value)
