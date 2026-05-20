from __future__ import annotations

import math

import pytest

from holdem.estimate.info_gain import (
    IGConfig,
    action_ig_bonus,
    apply_ig_to_candidates,
    ig_schedule,
)


def test_schedule_maxes_at_zero_obs():
    cfg = IGConfig()
    assert ig_schedule(0, cfg) == cfg.gamma_0


def test_schedule_decays_exponentially():
    cfg = IGConfig(gamma_0=0.02, tau=300)
    s0 = ig_schedule(0, cfg)
    s300 = ig_schedule(300, cfg)
    s600 = ig_schedule(600, cfg)
    assert s300 == pytest.approx(s0 * math.exp(-1))
    assert s600 == pytest.approx(s0 * math.exp(-2))


def test_schedule_disabled_returns_zero():
    assert ig_schedule(0, IGConfig(enable=False)) == 0.0


def test_fold_gets_zero_bonus():
    assert action_ig_bonus("fold", 10) == 0.0


def test_call_exceeds_raise_due_to_showdown_bonus():
    c = action_ig_bonus("call", 10)
    r = action_ig_bonus("raise", 10)
    assert c > r > 0


def test_bonus_capped():
    cfg = IGConfig(gamma_0=10.0, tau=1000, cap_per_action=0.05)
    # gamma_0 엄청 크지만 cap 적용.
    assert action_ig_bonus("call", 0, cfg) == 0.05


def test_bonus_decays_with_data():
    early = action_ig_bonus("call", 0)
    late = action_ig_bonus("call", 1000)
    assert early > late


def test_apply_to_candidates_preserves_keys():
    ev = {"fold": 0.0, "call": 0.1, "raise": 0.2}
    out = apply_ig_to_candidates(ev, n_total_obs=0)
    assert set(out) == {"fold", "call", "raise"}
    # fold 는 그대로, call/raise 는 증가
    assert out["fold"] == 0.0
    assert out["call"] > 0.1
    assert out["raise"] > 0.2


def test_apply_preserves_ordering_when_no_flip():
    ev = {"fold": 0.0, "call": 0.5, "raise": 1.0}
    out = apply_ig_to_candidates(ev, n_total_obs=0)
    # raise 가 여전히 최선
    best = max(out.items(), key=lambda kv: kv[1])[0]
    assert best == "raise"
