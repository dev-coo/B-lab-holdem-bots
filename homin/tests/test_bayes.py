from __future__ import annotations

import random

import pytest

from holdem.estimate.bayes import DirichletResponse, thompson_action_rates


def test_mean_uniform_on_default():
    r = DirichletResponse()
    m = r.mean()
    for v in m.values():
        assert v == pytest.approx(1 / 3)
    assert sum(m.values()) == pytest.approx(1.0)


def test_observe_updates_alpha():
    r = DirichletResponse()
    for _ in range(5):
        r.observe("fold")
    assert r.alpha_fold == pytest.approx(6.0)   # 1 + 5
    # mean 도 fold 쪽으로 쏠림
    assert r.mean()["fold"] > 0.5


def test_sample_sums_to_one():
    r = DirichletResponse(alpha_fold=3, alpha_call=2, alpha_raise=1)
    rng = random.Random(42)
    for _ in range(100):
        s = r.sample(rng=rng)
        assert sum(s.values()) == pytest.approx(1.0, abs=1e-9)


def test_sample_distribution_matches_mean_with_many_samples():
    r = DirichletResponse(alpha_fold=8, alpha_call=4, alpha_raise=2)
    rng = random.Random(123)
    samples = [r.sample(rng=rng) for _ in range(500)]
    avg = {a: sum(s[a] for s in samples) / len(samples) for a in ("fold", "call", "raise")}
    expected = r.mean()
    for k in avg:
        assert abs(avg[k] - expected[k]) < 0.05


def test_allin_maps_to_raise():
    r = DirichletResponse()
    r.observe("allin")
    assert r.alpha_raise == pytest.approx(2.0)
    assert r.alpha_fold == pytest.approx(1.0)


def test_decay_preserves_ratio():
    r = DirichletResponse(alpha_fold=10, alpha_call=5, alpha_raise=5)
    ratio_before = r.mean()
    r.decay(0.5)
    ratio_after = r.mean()
    for k in ("fold", "call", "raise"):
        assert ratio_before[k] == pytest.approx(ratio_after[k])


def test_n_obs_computed_from_alpha():
    r = DirichletResponse()
    assert r.n_obs == 0.0
    for _ in range(10):
        r.observe("call")
    assert r.n_obs == pytest.approx(10.0)


def test_thompson_wrapper_returns_sample():
    r = DirichletResponse(alpha_fold=5, alpha_call=3, alpha_raise=1)
    rng = random.Random(7)
    rates = thompson_action_rates(r, rng=rng)
    assert set(rates) == {"fold", "call", "raise"}
    assert sum(rates.values()) == pytest.approx(1.0)


def test_merge_sums_alphas():
    a = DirichletResponse(alpha_fold=5, alpha_call=3, alpha_raise=2)
    b = DirichletResponse(alpha_fold=1, alpha_call=2, alpha_raise=7)
    a.merge(b)
    assert a.alpha_fold == 6
    assert a.alpha_call == 5
    assert a.alpha_raise == 9


def test_merge_with_weight():
    a = DirichletResponse(alpha_fold=2, alpha_call=2, alpha_raise=2)
    b = DirichletResponse(alpha_fold=10, alpha_call=10, alpha_raise=10)
    a.merge(b, weight=0.5)
    assert a.alpha_fold == 7   # 2 + 10*0.5
