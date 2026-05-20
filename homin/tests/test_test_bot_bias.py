"""P-Bias: test bot (`__test_*`) 메타 추론 가중치 down-weight 테스트.

profile DB 의 누적 핸드 86% 가 자체 학습 봇 (`__test_tag_5` 등) → 사용 시점에
weight 0.3 으로 낮춰 실 플레이어 메타에 더 치우치게 한다.
"""
from __future__ import annotations

from holdem.decide.cbet import _villain_fold_to_cbet_weighted
from holdem.decide.policy import _table_is_loose_meta, build_default_deps
from holdem.state.profile_store import (
    ProfileStore,
    is_test_bot,
    name_weight,
)
from holdem.transport import protocol as p


def test_is_test_bot_recognizes_prefix():
    assert is_test_bot("__test_tag_5") is True
    assert is_test_bot("__test_lag_5") is True
    assert is_test_bot("realplayer") is False
    assert is_test_bot("") is False
    assert is_test_bot(None) is False


def test_name_weight_test_bot_lower():
    assert name_weight("realplayer") == 1.0
    assert name_weight("__test_tag_5") < 1.0
    assert name_weight(None) == 1.0


def _set_vpip(store: ProfileStore, name: str, rate: float, hands: float):
    cnt = store.get(name).get("VPIP")
    cnt.alpha = rate * hands
    cnt.beta = (1 - rate) * hands


def _set_fold_to_cbet(store: ProfileStore, name: str, rate: float, hands: float):
    cnt = store.get(name).metrics["FOLD_TO_CBET"]
    cnt.alpha = rate * hands
    cnt.beta = (1 - rate) * hands


def _make_req(active_names: list[str], my_name: str = "bot"):
    players = [p.PlayerState(name=my_name, position="btn", stack=200, bet=0, status="active")]
    for nm in active_names:
        players.append(p.PlayerState(name=nm, position="bb", stack=200, bet=0, status="active"))
    return p.ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=["As", "Ks"],
        community_cards=["2s", "7d", "Kc"],
        phase="flop",
        pot=20, my_stack=200, to_call=0, min_raise=20,
        blind=[1, 2], seat="btn",
        players=players,
        action_history=[
            p.HistoryEntry(phase="preflop", player=my_name, action="raise", amount=6),
        ],
    )


def test_table_loose_meta_downweights_test_bot():
    """real (tight, VPIP 0.20) + test_bot (loose, VPIP 0.80) → real 우세."""
    deps = build_default_deps()
    store = ProfileStore()
    _set_vpip(store, "realplayer", 0.20, hands=100)
    _set_vpip(store, "__test_lag_5", 0.80, hands=100)
    deps.profile_store = store
    req = _make_req(["realplayer", "__test_lag_5"])

    # weight 동일 시 평균 = 0.50 → True. weight down 시 ≈ (0.20*100 + 0.80*30) / 130 ≈ 0.34 → False.
    assert _table_is_loose_meta(req, deps, "bot") is False


def test_table_loose_meta_realplayer_alone_loose():
    """real player 만 loose → True (test bot 영향 없이)."""
    deps = build_default_deps()
    store = ProfileStore()
    _set_vpip(store, "realplayer", 0.55, hands=100)
    deps.profile_store = store
    req = _make_req(["realplayer"])
    assert _table_is_loose_meta(req, deps, "bot") is True


def test_cbet_villain_fold_to_cbet_downweights_test_bot():
    """real (fold rate 0.10) + test_bot (fold rate 0.80) → 평균이 real 쪽으로 기움."""
    store = ProfileStore()
    _set_fold_to_cbet(store, "realplayer", 0.10, hands=100)
    _set_fold_to_cbet(store, "__test_push_5", 0.80, hands=100)
    req = _make_req(["realplayer", "__test_push_5"])

    result = _villain_fold_to_cbet_weighted(req, "bot", store)
    assert result is not None
    avg, total_w, all_sticky = result
    # equal-weight 평균 = 0.45. down-weighted: (0.10*100 + 0.80*30) / 130 ≈ 0.26.
    assert 0.20 <= avg <= 0.32


def test_cbet_test_bot_only_villain_uses_full_data():
    """test bot 만 있으면 다른 정보 없으니 그 데이터를 사용 (가중치 비율 그대로)."""
    store = ProfileStore()
    _set_fold_to_cbet(store, "__test_tag_5", 0.50, hands=200)
    req = _make_req(["__test_tag_5"])

    result = _villain_fold_to_cbet_weighted(req, "bot", store)
    assert result is not None
    avg, total_w, _ = result
    assert abs(avg - 0.50) < 0.01
    # total_w 는 down-weight 적용 (200 * 0.3 = 60).
    assert abs(total_w - 60.0) < 0.01
