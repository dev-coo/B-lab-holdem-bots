"""Equity — treys MC 정확도 + 성능."""
from __future__ import annotations

import time

import pytest

from holdem.estimate.equity import (
    equity,
    equity_from_cards,
    equity_vs_range,
    preflop_equity_vs_random,
)


# --- preflop 기준 equity (문헌값 ±0.03 허용) ---

def test_AA_vs_random():
    eq = preflop_equity_vs_random("AA", n_opp=1, samples=3000)
    assert eq == pytest.approx(0.85, abs=0.03)


def test_72o_vs_random():
    eq = preflop_equity_vs_random("72o", n_opp=1, samples=3000)
    assert eq == pytest.approx(0.35, abs=0.04)


def test_AKs_vs_random():
    eq = preflop_equity_vs_random("AKs", n_opp=1, samples=3000)
    assert eq == pytest.approx(0.67, abs=0.03)


def test_22_vs_random():
    eq = preflop_equity_vs_random("22", n_opp=1, samples=3000)
    assert eq == pytest.approx(0.50, abs=0.04)


def test_3way_reduces_premium_equity():
    eq1 = preflop_equity_vs_random("AA", n_opp=1, samples=2000)
    eq3 = preflop_equity_vs_random("AA", n_opp=3, samples=2000)
    assert eq3 < eq1 - 0.1   # AA 3way: ~0.64


# --- 보드 기반 equity ---

def test_flop_made_hand_high_equity():
    # AKs on K-high flop — top pair top kicker
    eq = equity(["As", "Ks"], ["2h", "7d", "Kc"], n_opp=1, samples=2000)
    assert eq > 0.80


def test_flop_air_low_equity():
    # 72o on A-high flop — 완전 air 는 아니지만 (페어 백도어) 프리미엄 range 에 약함
    eq = equity(["7d", "2c"], ["As", "Kh", "Qd"], n_opp=1, samples=2000)
    assert eq < 0.30


def test_n_opp_zero_returns_one():
    assert equity(["As", "Ks"], [], n_opp=0, samples=10) == 1.0


def test_duplicate_cards_raises():
    with pytest.raises(ValueError):
        equity(["As", "As"], [], n_opp=1, samples=10)


def test_samples_zero_returns_half():
    assert equity(["As", "Ks"], [], n_opp=1, samples=0) == 0.5


# --- canonical 재진입 (LUT 캐시) ---

def test_preflop_lut_cache_is_deterministic():
    a = preflop_equity_vs_random("AKs", n_opp=1, samples=2000)
    b = preflop_equity_vs_random("AKs", n_opp=1, samples=2000)
    assert a == b    # 동일 seed + 캐시


def test_equity_from_cards_preflop_uses_lut():
    a = equity_from_cards("As", "Ks", n_opp=1, samples=2000)
    b = equity_from_cards("Ah", "Kh", n_opp=1, samples=2000)
    # 다른 구체 카드지만 동일 canonical AKs → 동일 값 (LUT)
    assert a == b


# --- range ---

def test_vs_premium_range_AKs_loses():
    # AKs vs {QQ+, AKs}: 지배되어 동률 근처
    eq = equity_vs_range(["As", "Ks"], None, "QQ+,AKs", n_opp=1, samples=1500)
    assert eq < 0.40


def test_vs_air_range_premium_wins():
    # AA vs random-wide range
    eq = equity_vs_range(["As", "Ac"], None, "any", n_opp=1, samples=1500)
    assert eq > 0.80


def test_empty_range_returns_half():
    # 빈 spec → 알 수 없음
    assert equity_vs_range(["As", "Ks"], None, "", n_opp=1, samples=100) == 0.5


# --- 성능 ---

def test_postflop_mc_under_80ms():
    # river MC 1000 samples 이 80ms 이내
    t0 = time.perf_counter()
    equity(["As", "Ks"], ["2h", "7d", "Kc", "4s", "9h"], n_opp=1, samples=1000)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 80, f"river MC too slow: {elapsed_ms:.1f}ms"


def test_turn_mc_under_80ms():
    t0 = time.perf_counter()
    equity(["As", "Ks"], ["2h", "7d", "Kc", "4s"], n_opp=1, samples=1000)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 80, f"turn MC too slow: {elapsed_ms:.1f}ms"


def test_multi_opp_scales():
    # 3-way MC 은 약간 느리지만 여전히 100ms 이내
    t0 = time.perf_counter()
    equity(["As", "Ac"], ["2h", "7d", "Kc"], n_opp=3, samples=800)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100
