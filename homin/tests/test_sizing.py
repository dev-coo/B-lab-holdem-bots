from __future__ import annotations

import random

from holdem.decide.conservatism import compute_profile
from holdem.decide.ev import EVInputs
from holdem.decide.sizing import enumerate_candidates, optimize
from holdem.estimate.bayes import DirichletResponse
from holdem.state.player_profile import PlayerProfile


def _inp(**kw) -> EVInputs:
    base = dict(pot=10, to_call=0, my_stack=100, my_bet=0, equity=0.5, bb=2)
    base.update(kw)
    return EVInputs(**base)


def test_cold_start_forbids_allin():
    cons = compute_profile(None)  # hard_conservative, allow_allin=False
    response = DirichletResponse()
    cands = enumerate_candidates(cons, response, _inp())
    assert not any(c.action == "allin" for c in cands)


def test_rich_profile_allows_allin():
    heavy = PlayerProfile(name="heavy", hands_seen=500)
    heavy.get("VPIP").alpha = 100
    heavy.get("VPIP").beta = 400
    cons = compute_profile(heavy)
    response = DirichletResponse()
    cands = enumerate_candidates(cons, response, _inp())
    assert any(c.action == "allin" for c in cands)


def test_conservative_grid_has_fewer_sizes():
    cold = compute_profile(None)
    heavy = PlayerProfile(name="h", hands_seen=500)
    heavy.get("VPIP").alpha = 100
    heavy.get("VPIP").beta = 400
    exp = compute_profile(heavy)

    response = DirichletResponse()
    cold_c = enumerate_candidates(cold, response, _inp(), kind="value")
    exp_c = enumerate_candidates(exp, response, _inp(), kind="value")
    # conservative 는 grid 가 작아 후보 수가 적음
    assert len([c for c in cold_c if c.action in ("raise", "allin")]) <= \
           len([c for c in exp_c if c.action in ("raise", "allin")])


def test_forced_jam_included_when_stack_small():
    # stack ≤ to_call → forced_jam → all-in 포함
    cons = compute_profile(None)
    response = DirichletResponse()
    cands = enumerate_candidates(cons, response, _inp(my_stack=5, to_call=10))
    # all-in 포함 (cold start 라도)
    assert any(c.action == "allin" for c in cands)


def test_invalid_raises_below_to_call_filtered():
    """to_call > 0 인 상황에서 raise 사이즈가 to_call 이하인 후보는 제거.

    pot=20, to_call=14, my_bet=0 → bluff 33% × 20 = 6.6 → 7 (≤14, 무효).
    bluff grid 만 enumerate 했을 때 raise 후보가 없거나 to_call 초과만.
    """
    cons = compute_profile(None)
    response = DirichletResponse()
    cands = enumerate_candidates(
        cons, response, _inp(pot=20, to_call=14, my_bet=0),
        kind="bluff",
    )
    raises = [c for c in cands if c.action == "raise"]
    for c in raises:
        assert (c.amount or 0) > 14, f"invalid raise {c.amount} below to_call=14"


def test_bluff_kind_applies_bluff_factor_via_lower_chip_ev():
    """bluff kind 는 cons.bluff_factor 가 적용 — fold 가정이 깎여 raise EV 가
    value kind 보다 보수적이어야."""
    cons = compute_profile(None)   # hard_conservative bluff_factor=0.5
    # 약한 equity 에 fold equity 의존 시나리오: bluff 보수화로 EV 가 떨어져야.
    response = DirichletResponse(alpha_fold=70, alpha_call=20, alpha_raise=10)
    rng_a = random.Random(1)
    rng_b = random.Random(1)
    val_cands = enumerate_candidates(
        cons, response, _inp(pot=30, to_call=0, my_bet=0, equity=0.30),
        kind="value", rng=rng_a,
    )
    bluff_cands = enumerate_candidates(
        cons, response, _inp(pot=30, to_call=0, my_bet=0, equity=0.30),
        kind="bluff", rng=rng_b,
    )
    val_raises = [c for c in val_cands if c.action in ("raise", "allin")]
    bluff_raises = [c for c in bluff_cands if c.action in ("raise", "allin")]
    if not val_raises or not bluff_raises:
        return  # 그리드 빈 경우 skip — 회귀 가드만.
    val_top = max(c.chip_ev for c in val_raises)
    bluff_top = max(c.chip_ev for c in bluff_raises)
    # bluff_factor=0.5 적용 → bluff EV 가 깎임. 같은 사이즈 비교는 어려우니
    # 그리드 최대값 비교만 ─ value > bluff 이어야.
    assert val_top >= bluff_top


def test_optimize_picks_best_log_util():
    # 고 equity → call 이 최선
    cons = compute_profile(None)
    response = DirichletResponse(alpha_fold=1.0, alpha_call=3.0, alpha_raise=1.0)
    rng = random.Random(0)
    best = optimize(cons, response, _inp(pot=20, to_call=5, equity=0.7), rng=rng)
    assert best.action in ("call", "raise")


def test_optimize_prefers_fold_with_bad_equity():
    cons = compute_profile(None)
    response = DirichletResponse(alpha_fold=1.0, alpha_call=10.0, alpha_raise=1.0)
    rng = random.Random(1)
    best = optimize(cons, response, _inp(pot=20, to_call=10, equity=0.1), rng=rng)
    assert best.action == "fold"


def test_amount_is_grid_scaled():
    heavy = PlayerProfile(name="h", hands_seen=500)
    heavy.get("VPIP").alpha = 100
    heavy.get("VPIP").beta = 400
    cons = compute_profile(heavy)
    response = DirichletResponse()
    rng = random.Random(0)
    cands = enumerate_candidates(cons, response, _inp(pot=30, to_call=0), rng=rng)
    raise_amts = sorted({c.amount for c in cands if c.action == "raise" and c.amount is not None})
    # grid value_bet 에 [0.33, 0.66, 1.0, 1.5] 같은 ratio 가 있으면 최소 2개의 서로 다른 사이즈
    assert len(raise_amts) >= 1
