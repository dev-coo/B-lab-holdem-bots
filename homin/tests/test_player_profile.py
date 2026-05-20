from __future__ import annotations

import pytest

from holdem.state.player_profile import (
    AggressionCounter,
    BetaCounter,
    PlayerProfile,
)


def test_beta_counter_init_returns_default():
    bc = BetaCounter()
    assert bc.n_obs == 0
    assert bc.rate(default=0.3) == 0.3


def test_beta_counter_observe():
    bc = BetaCounter()
    for _ in range(3):
        bc.observe(True)
    for _ in range(2):
        bc.observe(False)
    assert bc.alpha == 3
    assert bc.beta == 2
    assert bc.rate() == pytest.approx(0.6)


def test_beta_counter_decay():
    bc = BetaCounter(alpha=10, beta=10)
    bc.decay(0.5)
    assert bc.alpha == 5
    assert bc.beta == 5
    assert bc.rate() == 0.5   # 비율 유지


def test_beta_counter_scaled_preserves_rate():
    bc = BetaCounter(alpha=70, beta=30)   # rate 0.7, n=100
    s = bc.scaled(target_ess=8)
    assert s.alpha == pytest.approx(5.6)
    assert s.beta == pytest.approx(2.4)
    assert s.rate() == pytest.approx(0.7)


def test_beta_counter_scaled_zero_obs():
    bc = BetaCounter()
    s = bc.scaled(target_ess=8)
    assert s.n_obs == 0


def test_aggression_counter_zero():
    ac = AggressionCounter()
    assert ac.factor(default=1.5) == 1.5
    ac.observe_aggressive()
    assert ac.factor() >= 1.0   # 공격만 있을 때


def test_aggression_counter_ratio():
    ac = AggressionCounter()
    for _ in range(6):
        ac.observe_aggressive()
    for _ in range(2):
        ac.observe_passive()
    # passive ≥ 1 이므로 고전 AF = 6/2 = 3.0 유지
    assert ac.factor() == 3.0


def test_aggression_counter_caps_when_passive_zero():
    """passive=0 에서 aggressive 가 커도 상한(10) 로 클립."""
    ac = AggressionCounter()
    for _ in range(200):
        ac.observe_aggressive()
    af = ac.factor()
    assert 1.0 <= af <= 10.0
    # Laplace: (200+1)/(0+1) = 201 → cap = 10
    assert af == 10.0


def test_aggression_counter_laplace_when_passive_fractional():
    """passive 가 decay 로 1 미만이 되면 Laplace 보정."""
    ac = AggressionCounter(aggressive=20.0, passive=0.5)
    # Laplace: (20+1)/(0.5+1) = 14.0 → cap 10
    assert ac.factor() == 10.0


def test_player_profile_default_metrics():
    pp = PlayerProfile(name="bot-B")
    assert pp.vpip() == 0.0
    assert pp.pfr() == 0.0
    assert pp.af() == 1.0   # default when n=0


def test_player_profile_observes_metric():
    pp = PlayerProfile(name="bot-B")
    pp.get("VPIP").observe(True)
    pp.get("VPIP").observe(True)
    pp.get("VPIP").observe(False)
    assert pp.vpip() == pytest.approx(2 / 3)
