from __future__ import annotations

from holdem.estimate.opponent_lookup import opponent_rate, posterior_rate
from holdem.state.player_profile import PlayerProfile
from holdem.state.profile_store import ProfileStore


def test_none_profile_uses_class_uniform_and_pop():
    # profile 이 None 이면 class 는 각 0.25 가중, pop 은 9-max 기준.
    summary = posterior_rate(profile=None, metric="CBET", n_players=9)
    assert 0.0 < summary.rate < 1.0
    assert summary.n_personal == 0.0
    assert sum(summary.class_weights.values()) == 1.0
    # uniform 이므로 각 0.25
    for w in summary.class_weights.values():
        assert abs(w - 0.25) < 1e-9


def test_large_personal_dominates():
    # profile 이 20 핸드+ 강한 TAG 패턴 → CBET 관측 많으면 personal 지배
    profile = PlayerProfile(name="tag", hands_seen=50)
    profile.get("VPIP").alpha = 22 * 50 * 0.01
    profile.get("VPIP").beta = 78 * 50 * 0.01
    profile.aggression.aggressive = 25
    profile.aggression.passive = 10
    # CBET 20/20 — 개인 관측 강함
    profile.get("CBET").alpha = 20
    profile.get("CBET").beta = 0
    s = posterior_rate(profile, metric="CBET", n_players=9)
    # personal 100% 성공 → rate 는 prior(~0.70) 와 개인(1.0) 의 shrinkage blend.
    # τ_class=8 + τ_pop=40 + personal 20 → ESS 68, personal 비중 ≈29%.
    assert s.rate > 0.75


def test_opponent_rate_with_store():
    store = ProfileStore()
    p = store.get("villain")
    p.hands_seen = 30
    # VPIP 20/30
    p.get("VPIP").alpha = 6
    p.get("VPIP").beta = 24
    p.aggression.aggressive = 15
    p.aggression.passive = 5
    rate = opponent_rate(store, "villain", metric="VPIP", n_players=9)
    # 20% VPIP 부근 (priors 영향으로 약간 조정).
    assert 0.15 < rate < 0.30


def test_missing_store_returns_class_uniform():
    # store=None → 기본 default 가 아닌 population+class uniform blend
    rate = opponent_rate(None, "unknown", metric="CBET", n_players=9)
    assert 0.0 < rate < 1.0


def test_summary_is_data_rich_flag():
    p = PlayerProfile(name="heavy")
    p.get("CBET").alpha = 20
    p.get("CBET").beta = 20
    s = posterior_rate(p, metric="CBET", n_players=9)
    assert s.n_personal == 40.0
    assert s.is_data_rich
