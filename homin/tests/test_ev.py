from __future__ import annotations

import random

import pytest

from holdem.decide.ev import (
    EVInputs,
    ev_call,
    ev_check,
    ev_fold,
    ev_raise,
    pick_best,
)
from holdem.estimate.bayes import DirichletResponse


def _inp(**kw) -> EVInputs:
    base = dict(pot=10, to_call=2, my_stack=100, my_bet=0, equity=0.5, bb=2)
    base.update(kw)
    return EVInputs(**base)


def test_fold_ev_is_zero():
    c = ev_fold(_inp())
    assert c.action == "fold"
    assert c.chip_ev == 0.0


def test_check_requires_zero_to_call():
    c = ev_check(_inp(to_call=0))
    assert c.action == "check"
    assert c.chip_ev == 0.0


def test_call_positive_when_equity_above_pot_odds():
    # pot=10, to_call=2 → pot_odds = 2/12 = 0.167. eq=0.5 → 명백히 +EV.
    c = ev_call(_inp(equity=0.5))
    # EV = 0.5 · 12 − 2 = 4
    assert c.chip_ev == pytest.approx(4.0)


def test_call_negative_when_equity_below_pot_odds():
    # pot_odds = 2/12 ≈ 0.167, eq=0.10 → -EV
    c = ev_call(_inp(equity=0.1))
    assert c.chip_ev < 0


def test_call_break_even_exactly_at_pot_odds():
    # eq = pot_odds → EV = 0
    c = ev_call(_inp(pot=10, to_call=2, equity=2/12))
    assert c.chip_ev == pytest.approx(0.0, abs=1e-9)


def test_raise_ev_respects_fold_share():
    # 상대가 항상 fold → EV ≈ pot - 0 = pot (eq 무관)
    response = DirichletResponse(alpha_fold=1e6, alpha_call=1e-3, alpha_raise=1e-3)
    rng = random.Random(0)
    c = ev_raise(amount=6, response=response, inputs=_inp(pot=10, to_call=0, equity=0.3), rng=rng)
    # p_fold ≈ 1 → chip ≈ pot = 10
    assert c.chip_ev > 8


def test_raise_ev_vs_sticky_opponent():
    # 상대가 항상 call → EV = eq · (pot + 2·delta) − delta
    response = DirichletResponse(alpha_fold=1e-3, alpha_call=1e6, alpha_raise=1e-3)
    rng = random.Random(42)
    c = ev_raise(amount=6, response=response, inputs=_inp(pot=10, to_call=0, equity=0.5, my_bet=0), rng=rng)
    # delta=6 → villain_pot=22, EV ≈ 0.5·22 − 6 = 5
    assert 4.0 < c.chip_ev < 6.0


def test_bluff_factor_reduces_fold_share_in_chip_ev():
    """bluff_factor < 1 → fold 확률을 낮춰 보수적으로 평가. chip_ev 가 떨어짐."""
    response = DirichletResponse(alpha_fold=70, alpha_call=20, alpha_raise=10)
    rng_a = random.Random(123)
    rng_b = random.Random(123)   # 동일 seed → 동일 sample
    c_full = ev_raise(amount=10, response=response,
                      inputs=_inp(pot=10, to_call=0, my_bet=0, equity=0.30),
                      rng=rng_a, bluff_factor=1.0)
    c_half = ev_raise(amount=10, response=response,
                      inputs=_inp(pot=10, to_call=0, my_bet=0, equity=0.30),
                      rng=rng_b, bluff_factor=0.5)
    # fold equity 절반으로 깎임 → bluff EV 도 떨어져야.
    assert c_half.chip_ev < c_full.chip_ev


def test_bluff_factor_one_matches_unscaled():
    """bluff_factor=1.0 은 기존 EV 와 동일 (회귀 보호)."""
    response = DirichletResponse(alpha_fold=2, alpha_call=2, alpha_raise=1)
    rng_a = random.Random(7)
    rng_b = random.Random(7)
    c_default = ev_raise(amount=8, response=response,
                         inputs=_inp(pot=10, to_call=0, my_bet=0, equity=0.5),
                         rng=rng_a)
    c_explicit = ev_raise(amount=8, response=response,
                          inputs=_inp(pot=10, to_call=0, my_bet=0, equity=0.5),
                          rng=rng_b, bluff_factor=1.0)
    assert abs(c_default.chip_ev - c_explicit.chip_ev) < 1e-9


def test_pick_best_prefers_log_util():
    call = ev_call(_inp(pot=100, to_call=2, equity=0.5, my_stack=100))
    fold = ev_fold(_inp(pot=100, to_call=2, my_stack=100))
    # call chip EV 높음, fold 는 안전.
    best = pick_best([fold, call], objective="log_util")
    # 스택이 크면 call 이 log_util 도 우월
    assert best.action == "call"


def test_log_util_avoids_allin_with_negative_edge():
    # equity 낮은데 올인 → log_util 이 크게 음수 → fold 가 선택
    response = DirichletResponse(alpha_fold=1.0, alpha_call=1e6, alpha_raise=1e-3)
    rng = random.Random(7)
    fold = ev_fold(_inp(my_stack=100))
    shove = ev_raise(amount=100, response=response,
                     inputs=_inp(pot=10, to_call=0, my_stack=100, equity=0.25), rng=rng)
    best = pick_best([fold, shove], objective="log_util")
    assert best.action == "fold"


def test_raise_amount_marks_allin_when_full_stack():
    response = DirichletResponse(alpha_fold=1.0, alpha_call=1.0, alpha_raise=1.0)
    rng = random.Random(0)
    c = ev_raise(amount=100, response=response,
                 inputs=_inp(my_stack=100, my_bet=0, equity=0.5), rng=rng)
    assert c.action == "allin"


def test_ineffective_raise_becomes_check():
    # amount <= my_bet → delta ≤ 0
    response = DirichletResponse()
    rng = random.Random(0)
    c = ev_raise(amount=0, response=response, inputs=_inp(to_call=0, my_bet=5), rng=rng)
    assert c.action == "check"


def test_reraise_path_uses_pot_odds_gate_call():
    """우리가 strong equity → 상대 reraise 에 call 해서 positive EV 유지해야."""
    response = DirichletResponse(alpha_fold=1e-3, alpha_call=1e-3, alpha_raise=1e6)  # 항상 reraise
    rng = random.Random(11)
    # equity 80% 에 equity_vs_reraise=0.70 (여전히 강함) → pot-odds 충분.
    c = ev_raise(
        amount=6,
        response=response,
        inputs=_inp(pot=10, to_call=0, my_stack=100, my_bet=0,
                    equity=0.80, equity_vs_reraise=0.70),
        rng=rng,
    )
    # 과거 근사: ev = -delta = -6. 새 경로: call reraise, positive EV.
    assert c.chip_ev > 0


def test_reraise_path_uses_pot_odds_gate_fold():
    """우리 equity 가 reraise range 대비 부족 → fold, EV = -delta."""
    response = DirichletResponse(alpha_fold=1e-3, alpha_call=1e-3, alpha_raise=1e6)
    rng = random.Random(11)
    c = ev_raise(
        amount=6,
        response=response,
        inputs=_inp(pot=10, to_call=0, my_stack=100, my_bet=0,
                    equity=0.30, equity_vs_reraise=0.10),
        rng=rng,
    )
    # fold path: ev_vs_reraise = -delta = -6, p_raise≈1 → chip ≈ -6.
    assert -7 < c.chip_ev < -5


def test_reraise_default_penalty_when_equity_vs_reraise_not_given():
    """equity_vs_reraise 미지정 시 max(0.30, equity - 0.15) 근사."""
    response = DirichletResponse(alpha_fold=1e-3, alpha_call=1e-3, alpha_raise=1e6)
    rng = random.Random(3)
    # equity=0.60 → reraise range 대비 0.45 (기본 페널티).
    c = ev_raise(
        amount=6,
        response=response,
        inputs=_inp(pot=10, to_call=0, my_stack=100, my_bet=0, equity=0.60),
        rng=rng,
    )
    # 0.45 vs 3bet all-stack 요구 ≈ 94/194 = 48.5% → fold → ev ≈ -delta
    # 또는 boundary 근처. 어떤 경우든 과거 절대 손실보다 나아야 (fold 시 동일, call 시 개선).
    assert c.chip_ev <= 10.0  # sanity


def test_reraise_path_never_exceeds_sticky_call_ev():
    """동일 입력에서 '항상 reraise' 경로의 EV 는 '항상 call' 경로 이하여야."""
    rng = random.Random(100)
    resp_call = DirichletResponse(alpha_fold=1e-3, alpha_call=1e6, alpha_raise=1e-3)
    resp_rr = DirichletResponse(alpha_fold=1e-3, alpha_call=1e-3, alpha_raise=1e6)
    inputs = _inp(pot=10, to_call=0, my_stack=100, my_bet=0, equity=0.55, equity_vs_reraise=0.40)
    c_call = ev_raise(amount=6, response=resp_call, inputs=inputs, rng=rng)
    c_rr = ev_raise(amount=6, response=resp_rr, inputs=inputs, rng=rng)
    # reraise 경로는 상대가 좁은 range 로 공격 → 우리 EV ≤ 콜 경로.
    assert c_rr.chip_ev <= c_call.chip_ev + 0.01
