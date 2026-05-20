"""HU (heads-up) chart 분기 테스트.

검증:
  - 2-player table → HU chart 진입 (jam/fold 가 일반 chart 보다 훨씬 wide)
  - 3-way 이상 → HU chart 미진입 (일반 push_fold/hybrid)
  - facing jam → hu_call chart
  - 깊은 스택(M>13) HU first-in → 일반 hybrid 경로 fallthrough
"""
from __future__ import annotations

from holdem.decide.policy import decide
from holdem.decide.push_fold_chart import default_chart
from holdem.transport import protocol as p


def _hu_req(
    *,
    my_cards,
    stack=200,
    sb=10,
    bb=20,
    to_call=10,
    min_raise=40,
    pot=30,
    history=None,
    seat="btn",
):
    """HU (2 명) ActionRequest. 기본은 SB 첫 액션 시점."""
    players = [
        p.PlayerState(name="my-bot", position=seat, stack=stack, bet=0, status="active"),
        p.PlayerState(name="opp", position="bb" if seat == "btn" else "btn",
                      stack=stack, bet=bb, status="active"),
    ]
    return p.ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=my_cards,
        community_cards=[],
        phase="preflop",
        pot=pot, my_stack=stack, to_call=to_call, min_raise=min_raise,
        blind=[sb, bb], seat=seat,
        players=players,
        action_history=history or [],
    )


def test_hu_chart_loads_buckets():
    chart = default_chart()
    assert chart.hu_jam, "hu_jam 버킷이 비어있음"
    assert chart.hu_call, "hu_call 버킷이 비어있음"


def test_hu_jam_widely_pushes_marginal_at_short_m():
    """HU SB M=4 short stack 에서 K7s 같은 marginal 핸드도 jam 범위.

    9-max chart 에서는 K7s 가 M=4 LP 의 jam 범위 — HU 도 이 정도 또는 더 wide.
    """
    # M = 200 / (10+20) ≈ 6.67 → hu_jam bucket max_M=8.0 보다 작음 → bucket 매칭.
    # 사실은 stack=80 으로 M=2.67 로 잡아 4.0 bucket 매칭.
    action = decide(_hu_req(my_cards=["Kh", "7s"], stack=80, sb=10, bb=20, to_call=10), "my-bot")
    # HU jam 범위 wide → all-in 또는 (얇으면 anti-correl) fold; KO 정도면 jam.
    assert action.action in ("allin", "raise")


def test_hu_call_with_premium_calls_jam():
    """HU BB 가 SB jam 에 대해 premium (AKo) 으로 call."""
    history = [p.HistoryEntry(phase="preflop", player="opp", action="allin", amount=200)]
    action = decide(_hu_req(
        my_cards=["Ah", "Kc"], seat="bb", stack=200, sb=10, bb=20,
        to_call=180, min_raise=400, pot=210,
        history=history,
    ), "my-bot")
    assert action.action in ("call", "allin")


def test_hu_call_fold_with_trash_facing_jam():
    """HU BB 가 SB jam 에 대해 weak (72o) 로 fold."""
    history = [p.HistoryEntry(phase="preflop", player="opp", action="allin", amount=200)]
    action = decide(_hu_req(
        my_cards=["7d", "2c"], seat="bb", stack=200, sb=10, bb=20,
        to_call=180, min_raise=400, pot=210,
        history=history,
    ), "my-bot")
    assert action.action == "fold"


def test_hu_jam_skipped_for_deep_stack():
    """HU 라도 M > 13 이면 hu_jam 미적용 → P5-3 hu_open 분기."""
    # 7-2o 는 hu_open chart 70% range 안에도 없음 → fold (to_call=10 > 0).
    action = decide(_hu_req(
        my_cards=["7d", "2c"], stack=1000, sb=10, bb=20, to_call=10, min_raise=40,
    ), "my-bot")
    assert action.action in ("fold", "check")


# --- P5-3: deep stack HU open ---

def test_hu_deep_open_with_premium_raises():
    """M > 13 deep HU + premium AA → hu_open 안 → raise (이전엔 generic chart fallthrough)."""
    # M = 1000 / 30 ≈ 33 → hu_open M > 25 bucket (60% range, AA 포함).
    action = decide(_hu_req(
        my_cards=["As", "Ad"], stack=1000, sb=10, bb=20, to_call=0, min_raise=40,
    ), "my-bot")
    assert action.action == "raise"


def test_hu_deep_open_with_suited_connector():
    """M ≈ 20 deep HU + 8-7s → hu_open 13<M≤25 bucket 70% range 안 → raise."""
    action = decide(_hu_req(
        my_cards=["8h", "7h"], stack=600, sb=10, bb=20, to_call=0, min_raise=40,
    ), "my-bot")
    assert action.action == "raise"


def test_hu_deep_open_with_trash_folds():
    """M > 25 deep HU + 7-2o (가장 약한 핸드) → hu_open 밖 → fold/check."""
    # to_call > 0 → fold.
    action = decide(_hu_req(
        my_cards=["7d", "2c"], stack=2000, sb=10, bb=20, to_call=10, min_raise=40,
    ), "my-bot")
    assert action.action == "fold"


def test_hu_deep_open_to_call_zero_check_when_off_range():
    """to_call=0 + 약한 핸드 → check (RFI 안 함)."""
    action = decide(_hu_req(
        my_cards=["7d", "2c"], stack=2000, sb=10, bb=20, to_call=0, min_raise=40,
    ), "my-bot")
    assert action.action == "check"


def test_3way_does_not_use_hu_chart():
    """3-way 이상에서는 HU chart 진입 안 함. 9-max push_fold/hybrid 의 표준 EP 좁은
    범위가 적용 — 7-2o 같은 trash 는 fold.

    M ≈ 5: 9-max push_fold EP 의 4 < M ≤ 6 bucket 은 "44+,ATs+,AQo+,KTs+,KQo".
    """
    players = [
        p.PlayerState(name="my-bot", position="utg", stack=100, bet=0, status="active"),
        p.PlayerState(name="opp1", position="btn", stack=200, bet=0, status="active"),
        p.PlayerState(name="opp2", position="bb", stack=200, bet=20, status="active"),
    ]
    req = p.ActionRequest(
        type="action_request", room_id=1, hand_number=1,
        your_cards=["7d", "2c"], community_cards=[], phase="preflop",
        pot=30, my_stack=100, to_call=10, min_raise=40,
        blind=[10, 20], seat="utg",
        players=players, action_history=[],
    )
    # M=5, EP 7-2o → 9-max chart 외 → fold.
    action = decide(req, "my-bot")
    assert action.action == "fold"
