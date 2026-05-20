from __future__ import annotations

import pytest

from holdem.estimate.priors import (
    ShrinkageHyperparams,
    load_class_priors,
    load_population_priors,
)
from holdem.estimate.shrinkage import effective_rate, shrink, soft_class_prior
from holdem.state.player_profile import BetaCounter


HP = ShrinkageHyperparams(tau_class=8, tau_population=40)


def test_zero_personal_yields_blended_prior():
    # class prior CBET TAG (70, 30) ESS=100 → scaled (5.6, 2.4)
    # pop prior 9max CBET (71, 29) ESS=100 → scaled (28.4, 11.6)
    # total (34, 14) → rate ≈ 0.708
    personal = BetaCounter()
    class_ = BetaCounter(alpha=70, beta=30)
    pop = BetaCounter(alpha=71, beta=29)
    eff = shrink(personal, class_, pop, HP)
    assert eff.rate() == pytest.approx(0.708, abs=0.01)


def test_large_personal_dominates_priors():
    # personal (1000, 0) → 거의 완전 1.0
    personal = BetaCounter(alpha=1000, beta=0)
    class_ = BetaCounter(alpha=70, beta=30)
    pop = BetaCounter(alpha=71, beta=29)
    eff = shrink(personal, class_, pop, HP)
    # personal 1000 vs priors 48 effective → ≈ (1034, 14) → 0.987
    assert eff.rate() > 0.97


def test_small_personal_blended():
    # personal (10, 0) all success, priors rate 0.7 → posterior between 0.7 and 1.0
    personal = BetaCounter(alpha=10, beta=0)
    class_ = BetaCounter(alpha=70, beta=30)
    pop = BetaCounter(alpha=71, beta=29)
    r = effective_rate(personal, class_, pop, HP)
    assert 0.70 < r < 0.95


def test_soft_class_prior_weighted_sum():
    priors = {
        "TAG": BetaCounter(alpha=10, beta=0),
        "LAG": BetaCounter(alpha=0, beta=10),
        "NIT": BetaCounter(alpha=5, beta=5),
        "Fish": BetaCounter(alpha=5, beta=5),
    }
    weights = {"TAG": 0.5, "LAG": 0.5, "NIT": 0.0, "Fish": 0.0}
    mixed = soft_class_prior(priors, weights)
    assert mixed.alpha == pytest.approx(5.0)
    assert mixed.beta == pytest.approx(5.0)


def test_yaml_priors_loadable():
    pop = load_population_priors()
    assert 9 in pop.by_players
    assert "CBET" in pop.by_players[9]
    assert pop.shrinkage.tau_class == 8
    cp = load_class_priors()
    assert set(cp.priors) >= {"NIT", "TAG", "LAG", "Fish"}
    assert cp.centroids["TAG"]["VPIP"] > 0


def test_end_to_end_with_real_yaml():
    pop = load_population_priors()
    cp = load_class_priors()
    personal = BetaCounter(alpha=3, beta=7)   # 개인 관측 10, CBET 30%
    class_cbet = cp.priors["TAG"]["CBET"]     # 70,30
    pop_cbet = pop.for_players(9)["CBET"]     # 71,29
    r = effective_rate(personal, class_cbet, pop_cbet, pop.shrinkage)
    # personal 이 약하고 prior 가 CBET-heavy 이므로 중간값
    assert 0.40 < r < 0.75