"""멀티웨이 보수 joint fold (plan H.8) — policy._aggregate_response 검증."""
from __future__ import annotations

import pytest

from holdem.decide.policy import _aggregate_response, build_default_deps
from holdem.estimate.bayes import DirichletResponse
from holdem.state.profile_store import ProfileStore
from holdem.state.response_store import ResponseStore
from holdem.transport import protocol as p


def _req(players: list[tuple[str, str]], seat: str = "me", phase: str = "flop") -> p.ActionRequest:
    """players: list of (name, status)."""
    return p.ActionRequest(
        type="action_request",
        room_id=1,
        hand_number=1,
        phase=phase,
        pot=100,
        to_call=20,
        min_raise=40,
        my_stack=200,
        community_cards=[],
        your_cards=["As", "Kd"],
        blind=[1, 2],
        seat=seat,
        players=[
            p.PlayerState(name=nm, position=nm, status=st, stack=200, bet=0)
            for nm, st in players
        ],
    )


def _deps_with_responses(table: dict[tuple[str, str], DirichletResponse]):
    deps = build_default_deps()
    store = ProfileStore()
    store.responses = ResponseStore(table=dict(table))
    deps.profile_store = store
    return deps


def test_hu_2way_returns_simple_aggregate():
    """2-way: joint fold 로직 비활성, 단순 Dirichlet α 합산."""
    req = _req([("me", "active"), ("opp1", "active")])
    table = {
        ("opp1", "flop"): DirichletResponse(alpha_fold=5, alpha_call=3, alpha_raise=1),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    # opp1 의 raw Dirichlet 가 그대로.
    assert resp.alpha_fold == pytest.approx(5.0, rel=0.01)
    assert resp.alpha_call == pytest.approx(3.0, rel=0.01)
    assert resp.alpha_raise == pytest.approx(1.0, rel=0.01)


def test_3way_uses_conservative_joint_fold():
    """3-way: p_fold = min(f_i)^2 (n_opp=2 exponent)."""
    req = _req([("me", "active"), ("opp1", "active"), ("opp2", "active")])
    # opp1: mostly-fold, opp2: mostly-call
    table = {
        ("opp1", "flop"): DirichletResponse(alpha_fold=80, alpha_call=10, alpha_raise=10),
        ("opp2", "flop"): DirichletResponse(alpha_fold=20, alpha_call=70, alpha_raise=10),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    mean = resp.mean()
    # min(0.8, 0.2) = 0.2. n_opp=2. joint = 0.04.
    # 독립 곱 (0.8·0.2=0.16) 보다 훨씬 작다 (더 보수).
    assert mean["fold"] == pytest.approx(0.04, abs=0.005)
    # aggregated mean fold = (80+20)/(total) ≈ 0.5 → 우리 보수 joint 0.04 훨씬 낮음.
    assert mean["fold"] < 0.1


def test_4way_exponent_escalates():
    """4-way: p_fold = min(f)^3, 3-way 보다 훨씬 작아야."""
    req = _req([
        ("me", "active"), ("a", "active"), ("b", "active"), ("c", "active"),
    ])
    # 모두 fold 0.5 경향.
    table = {
        ("a", "flop"): DirichletResponse(alpha_fold=50, alpha_call=25, alpha_raise=25),
        ("b", "flop"): DirichletResponse(alpha_fold=50, alpha_call=25, alpha_raise=25),
        ("c", "flop"): DirichletResponse(alpha_fold=50, alpha_call=25, alpha_raise=25),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    mean = resp.mean()
    # min=0.5, n_opp=3, joint=0.125.
    assert mean["fold"] == pytest.approx(0.125, abs=0.01)


def test_folded_opponents_excluded():
    """folded/eliminated 상태의 상대는 계산에서 제외."""
    req = _req([
        ("me", "active"), ("opp1", "active"),
        ("opp2", "folded"), ("opp3", "eliminated"),
    ])
    table = {
        ("opp1", "flop"): DirichletResponse(alpha_fold=5, alpha_call=3, alpha_raise=1),
        ("opp2", "flop"): DirichletResponse(alpha_fold=100, alpha_call=1, alpha_raise=1),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    # opp2, opp3 제외 — 2-way 로 처리, opp1 의 값만 반영.
    assert resp.alpha_fold == pytest.approx(5.0, rel=0.01)
    assert resp.alpha_call == pytest.approx(3.0, rel=0.01)


def test_no_store_returns_uniform():
    req = _req([("me", "active"), ("opp1", "active")])
    deps = build_default_deps()
    deps.profile_store = None
    resp = _aggregate_response(req, deps)
    # 기본 (1,1,1).
    assert resp.alpha_fold == 1.0
    assert resp.alpha_call == 1.0
    assert resp.alpha_raise == 1.0


def test_solo_active_no_opponents():
    req = _req([("me", "active")])
    deps = _deps_with_responses({})
    resp = _aggregate_response(req, deps)
    # 상대 없음 → 기본 response.
    assert resp.alpha_fold == 1.0


def test_3way_mass_conservation():
    """joint-fold 재분배 후 P 합 = 1."""
    req = _req([("me", "active"), ("a", "active"), ("b", "active")])
    table = {
        ("a", "flop"): DirichletResponse(alpha_fold=30, alpha_call=40, alpha_raise=30),
        ("b", "flop"): DirichletResponse(alpha_fold=50, alpha_call=30, alpha_raise=20),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    mean = resp.mean()
    assert mean["fold"] + mean["call"] + mean["raise"] == pytest.approx(1.0, abs=1e-6)


def test_3way_call_raise_ratio_from_aggregate():
    """call/raise 비율은 aggregate mean 을 유지 (fold 만 보수적)."""
    req = _req([("me", "active"), ("a", "active"), ("b", "active")])
    # opp a/b 모두 동일 — call/raise 비율 2:1.
    table = {
        ("a", "flop"): DirichletResponse(alpha_fold=10, alpha_call=60, alpha_raise=30),
        ("b", "flop"): DirichletResponse(alpha_fold=10, alpha_call=60, alpha_raise=30),
    }
    deps = _deps_with_responses(table)
    resp = _aggregate_response(req, deps)
    mean = resp.mean()
    # call:raise 비율 (fold 제외 후) 유지: 2:1
    non_fold = mean["call"] + mean["raise"]
    assert non_fold > 0
    assert mean["call"] / non_fold == pytest.approx(0.666, abs=0.01)
    assert mean["raise"] / non_fold == pytest.approx(0.333, abs=0.01)
