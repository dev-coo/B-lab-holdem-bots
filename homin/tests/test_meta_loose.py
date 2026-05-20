"""P-Adapt2: loose-passive 메타 적응형 PFR 테스트.

`_table_is_loose_meta` 의 분기와 _decide_midlow_and_deep 의 RFI 확대 동작.
"""
from __future__ import annotations

from holdem.decide.policy import (
    DecideDeps,
    _table_is_loose_meta,
    build_default_deps,
    decide,
)
from holdem.state.profile_store import ProfileStore
from holdem.transport import protocol as p


def _req(*, my_name="bot", n_active=6, my_cards=("7s", "5s"), seat="btn"):
    players = [
        p.PlayerState(name=my_name, position="btn", stack=2000, bet=0, status="active"),
    ]
    for i in range(n_active - 1):
        players.append(p.PlayerState(
            name=f"opp{i}", position="utg" if i == 0 else "co", stack=2000, bet=0, status="active",
        ))
    return p.ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=list(my_cards),
        community_cards=[],
        phase="preflop",
        pot=3, my_stack=2000, to_call=2, min_raise=4,
        blind=[1, 2], seat=seat,
        players=players, action_history=[],
    )


def _store_with_vpip(name: str, vpip_rate: float, hands: float) -> ProfileStore:
    store = ProfileStore()
    prof = store.get(name)
    cnt = prof.get("VPIP")
    cnt.alpha = vpip_rate * hands
    cnt.beta = (1 - vpip_rate) * hands
    return store


def test_meta_loose_false_without_store():
    deps = build_default_deps()
    deps.profile_store = None
    req = _req()
    assert _table_is_loose_meta(req, deps, "bot") is False


def test_meta_loose_false_when_undersampled():
    """30 hands 미만은 표본 부족 → false 디폴트."""
    deps = build_default_deps()
    deps.profile_store = _store_with_vpip("opp0", 0.55, hands=10)
    req = _req()
    assert _table_is_loose_meta(req, deps, "bot") is False


def test_meta_loose_true_when_villains_loose_and_observed():
    """관측 충분 + 평균 VPIP ≥ 0.40 → True."""
    deps = build_default_deps()
    deps.profile_store = _store_with_vpip("opp0", 0.55, hands=100)
    req = _req()
    assert _table_is_loose_meta(req, deps, "bot") is True


def test_meta_loose_false_when_villains_tight():
    deps = build_default_deps()
    deps.profile_store = _store_with_vpip("opp0", 0.20, hands=100)
    req = _req()
    assert _table_is_loose_meta(req, deps, "bot") is False


def test_decide_uses_loose_meta_chart_for_btn_53s():
    """LP (btn) 에서 5s3s → 6-max baseline 미포함 / 6-max loose-meta 에는 포함.

    v5-A 이후: 6-max chart 는 5-max 보다 tight. 6-max LP baseline 은 75s+/65s/54s 까지,
    loose meta 는 53s+ 포함 → 53s 가 분기 검증에 적합."""
    deps = build_default_deps()
    deps.profile_store = None
    req_default = _req(my_cards=("5s", "3s"), seat="btn")
    decision_default = decide(req_default, "bot", deps)
    assert decision_default.action in ("fold", "check")

    deps_loose = build_default_deps()
    deps_loose.profile_store = _store_with_vpip("opp0", 0.55, hands=100)
    req_loose = _req(my_cards=("5s", "3s"), seat="btn")
    decision_loose = decide(req_loose, "bot", deps_loose)
    assert decision_loose.action == "raise"
