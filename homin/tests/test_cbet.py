"""cbet 모듈 단위 테스트.

is_preflop_aggressor 와 cbet_response_adjustment 의 시나리오 분기:
  - phase / to_call / aggressor / n_opp 조건 미충족 → None
  - 충족 + dry/wet board, HU/3-way 별 fold rate boost 비교
"""
from __future__ import annotations

from holdem.decide.cbet import (
    cbet_response_adjustment,
    is_preflop_aggressor,
)
from holdem.estimate.bayes import DirichletResponse
from holdem.transport import protocol as p


def _req(
    *,
    my_name="bot",
    phase="flop",
    to_call=0,
    community=None,
    n_active=2,
    history=None,
):
    players = [
        p.PlayerState(name=my_name, position="btn", stack=200, bet=0, status="active"),
    ]
    for i in range(n_active - 1):
        players.append(p.PlayerState(
            name=f"opp{i}", position="bb", stack=200, bet=0, status="active",
        ))
    return p.ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=["As", "Ks"],
        community_cards=community or ["2s", "7d", "Kc"],
        phase=phase,
        pot=20, my_stack=200, to_call=to_call, min_raise=20,
        blind=[1, 2], seat="btn",
        players=players,
        action_history=history or [],
    )


def test_is_preflop_aggressor_detects_my_raise():
    h = [
        p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6),
        p.HistoryEntry(phase="preflop", player="opp0", action="call", amount=6),
    ]
    req = _req(history=h)
    assert is_preflop_aggressor(req, "bot") is True


def test_is_preflop_aggressor_false_when_opp_was_aggressor():
    h = [
        p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6),
        p.HistoryEntry(phase="preflop", player="opp0", action="raise", amount=18),
    ]
    req = _req(history=h)
    # opp 가 마지막 aggressor → bot 은 aggressor 아님.
    assert is_preflop_aggressor(req, "bot") is False


def test_cbet_returns_none_when_not_flop():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(phase="turn", history=h, community=["2s","7d","Kc","9h"])
    base = DirichletResponse()
    assert cbet_response_adjustment(req, "bot", base) is None


def test_cbet_returns_none_when_to_call_nonzero():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(to_call=10, history=h)
    base = DirichletResponse()
    assert cbet_response_adjustment(req, "bot", base) is None


def test_cbet_returns_none_when_not_aggressor():
    req = _req(history=[])  # no preflop raise
    base = DirichletResponse()
    assert cbet_response_adjustment(req, "bot", base) is None


def test_cbet_boosts_fold_on_dry_hu_board():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])  # dry board
    base = DirichletResponse()  # (1,1,1) → fold rate 33%
    boosted = cbet_response_adjustment(req, "bot", base)
    assert boosted is not None
    # HU dry → target ≈ 0.65, must be higher than baseline 0.33.
    assert boosted.mean()["fold"] > base.mean()["fold"]
    assert boosted.mean()["fold"] >= 0.55


def test_cbet_lower_boost_on_wet_3way_board():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=3, community=["9h", "8h", "7h"])  # very wet, monotone connected
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base)
    if boosted is not None:
        # wet 3-way 는 boost 가 적거나 없어야.
        assert boosted.mean()["fold"] < 0.50


def test_cbet_returns_none_when_multi_way_above_2_opps():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=4)   # 3 opponents
    base = DirichletResponse()
    assert cbet_response_adjustment(req, "bot", base) is None


def test_cbet_no_boost_when_base_already_high():
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2)
    # 이미 fold rate 70% 인 base → boost 불필요.
    base = DirichletResponse(alpha_fold=70, alpha_call=20, alpha_raise=10)
    boosted = cbet_response_adjustment(req, "bot", base)
    assert boosted is None


def test_cbet_alpha_total_preserved():
    """Boost 후 α 총합은 보존."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    base = DirichletResponse(alpha_fold=2, alpha_call=3, alpha_raise=1)
    boosted = cbet_response_adjustment(req, "bot", base)
    assert boosted is not None
    base_total = base.alpha_fold + base.alpha_call + base.alpha_raise
    boosted_total = boosted.alpha_fold + boosted.alpha_call + boosted.alpha_raise
    assert abs(base_total - boosted_total) < 1e-6


# --- P-Adapt1: profile_store 기반 villain FOLD_TO_CBET 반영 ---

def _store_with_fold_to_cbet(opp_name: str, fold_count: float, total: float):
    """opp_name 의 FOLD_TO_CBET BetaCounter 를 (alpha=fold, beta=total-fold) 로 세팅."""
    from holdem.state.profile_store import ProfileStore
    store = ProfileStore()
    prof = store.get(opp_name)
    cnt = prof.metrics["FOLD_TO_CBET"]
    cnt.alpha = fold_count
    cnt.beta = max(0.0, total - fold_count)
    return store


def test_cbet_no_change_without_profile_store():
    """profile_store=None 이면 기존 동작 (baseline 만)."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    base = DirichletResponse()
    a = cbet_response_adjustment(req, "bot", base, profile_store=None)
    b = cbet_response_adjustment(req, "bot", base)
    assert a is not None and b is not None
    assert abs(a.alpha_fold - b.alpha_fold) < 1e-9


def test_cbet_blends_high_observation_villain_rate():
    """100+ hands villain rate 도 baseline 30% 영향 보존 (P-Floor cap 0.7)."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    # opp0 의 fold-to-cbet rate = 0.40 (loose-fold), 200 hands (full-weight).
    store = _store_with_fold_to_cbet("opp0", fold_count=80, total=200)
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    assert boosted is not None
    # weight = min(0.7, 200/100) = 0.7 → target = 0.3*0.65 + 0.7*0.40 = 0.475
    assert 0.43 <= boosted.mean()["fold"] <= 0.50


def test_cbet_blends_low_observation_villain_rate():
    """소량 관측 시 baseline 무게가 매우 큼 (P-Floor full-weight 임계 100)."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    # opp0: fold rate 0.10, 10 hands.
    store = _store_with_fold_to_cbet("opp0", fold_count=1, total=10)
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    # weight = 10/100 = 0.1 → target = 0.9*0.65 + 0.1*0.10 = 0.595
    assert boosted is not None
    assert 0.55 <= boosted.mean()["fold"] <= 0.62


def test_cbet_villain_max_weight_caps_at_30pct_baseline():
    """villain hands 가 1000+ 이어도 baseline 30% 는 유지 (frozen posterior 방지)."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    # 1000 hands 의 villain (full freeze 위험) — fold rate 0.40.
    store = _store_with_fold_to_cbet("opp0", fold_count=400, total=1000)
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    assert boosted is not None
    # weight cap = 0.7 → target = 0.3*0.65 + 0.7*0.40 = 0.475 (1000 hands 어도 동일).
    assert 0.43 <= boosted.mean()["fold"] <= 0.50


def test_cbet_disabled_when_villain_sticky_with_observations():
    """모든 villain 이 sticky (rate<0.20, hands≥30) → c-bet 비활성."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    # opp0: 50 hands, fold rate 0.10 (매우 sticky).
    store = _store_with_fold_to_cbet("opp0", fold_count=5, total=50)
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    assert boosted is None


def test_cbet_not_disabled_when_sticky_villain_undersampled():
    """sticky 처럼 보여도 < 30 hands 면 sticky 판정 안 함 (baseline blend 만)."""
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=2, community=["As", "7d", "2c"])
    # opp0: 20 hands, fold rate 0.10.
    store = _store_with_fold_to_cbet("opp0", fold_count=2, total=20)
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    # 적은 관측 → blend 만 적용, c-bet 자체는 살아남.
    assert boosted is not None


def test_cbet_partial_villain_data_3way():
    """3-way 에서 한 명만 관측 데이터 있으면 그 한 명 기준 가중평균."""
    from holdem.state.profile_store import ProfileStore
    h = [p.HistoryEntry(phase="preflop", player="bot", action="raise", amount=6)]
    req = _req(history=h, n_active=3, community=["As", "7d", "2c"])
    store = ProfileStore()
    prof = store.get("opp0")
    cnt = prof.metrics["FOLD_TO_CBET"]
    cnt.alpha = 60; cnt.beta = 40   # 60/100 = 0.60 (loose-fold villain)
    # opp1 은 데이터 없음 → 합산에서 제외.
    base = DirichletResponse()
    boosted = cbet_response_adjustment(req, "bot", base, profile_store=store)
    # baseline 3-way dry = 0.45, blend weight=1 → target ≈ 0.60. base 0.33 → boost 발생.
    assert boosted is not None
    assert 0.55 <= boosted.mean()["fold"] <= 0.65
