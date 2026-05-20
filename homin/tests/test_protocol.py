"""transport.protocol 모델 round-trip 테스트.

BOT_GUIDE §5 예시 payload 를 직접 사용하여 서버 ↔ 봇 직렬화가 누락/손실 없이
동작함을 보증. 규칙이 바뀌면 이 파일이 먼저 실패해야 한다.
"""
from __future__ import annotations

import pytest

from holdem.transport import protocol as p


def test_auth_ok():
    msg = p.parse_incoming({
        "type": "auth_ok",
        "user_id": 2,
        "bot_name": "my-bot",
        "bot_tokens": 50,
        "concurrent_games": 1,
    })
    assert isinstance(msg, p.AuthOk)
    assert msg.bot_name == "my-bot"


def test_auth_fail():
    msg = p.parse_incoming({"type": "auth_fail", "reason": "봇 인증 실패"})
    assert isinstance(msg, p.AuthFail)
    assert "실패" in msg.reason


def test_ping():
    assert isinstance(p.parse_incoming({"type": "ping"}), p.Ping)


def test_server_shutdown():
    msg = p.parse_incoming({"type": "server_shutdown", "reason": "done"})
    assert isinstance(msg, p.ServerShutdown)


def test_game_start():
    msg = p.parse_incoming({
        "type": "game_start",
        "room_id": 1,
        "players": [{"name": "bot-A", "type": "bot"}],
        "starting_stack": 300,
        "blind_structure": [
            {"level": 1, "small": 1, "big": 2, "hands": 10},
            {"level": 2, "small": 2, "big": 4, "hands": 10},
        ],
    })
    assert isinstance(msg, p.GameStart)
    assert msg.room_id == 1
    assert msg.blind_structure[0].big == 2


def test_hand_start():
    msg = p.parse_incoming({
        "type": "hand_start",
        "room_id": 1,
        "hand_number": 1,
        "your_cards": ["Ah", "Kh"],
        "your_stack": 298,
        "your_seat": "btn",
        "blind": [1, 2],
        "players": [
            {"name": "bot-A", "stack": 298, "position": "btn", "status": "active", "action": None, "bet": 0},
            {"name": "bot-B", "stack": 297, "position": "sb", "status": "active", "action": None, "bet": 1},
        ],
    })
    assert isinstance(msg, p.HandStart)
    assert msg.your_seat == "btn"
    assert msg.players[1].bet == 1


def test_action_request():
    msg = p.parse_incoming({
        "type": "action_request",
        "room_id": 1,
        "hand_number": 1,
        "your_cards": ["Ah", "Kh"],
        "community_cards": ["2s", "7d", "Kc"],
        "phase": "flop",
        "pot": 12,
        "my_stack": 294,
        "to_call": 4,
        "min_raise": 8,
        "blind": [1, 2],
        "seat": "btn",
        "players": [
            {"name": "bot-A", "stack": 294, "position": "btn", "status": "active", "bet": 0},
        ],
        "action_history": [
            {"phase": "preflop", "player": "bot-B", "action": "call", "amount": 2},
            {"phase": "flop", "player": "bot-B", "action": "raise", "amount": 4},
        ],
        "timeout_ms": 30000,
    })
    assert isinstance(msg, p.ActionRequest)
    assert msg.phase == "flop"
    assert msg.to_call == 4
    assert msg.min_raise == 8
    assert len(msg.action_history) == 2
    assert msg.action_history[1].action == "raise"


def test_action_performed():
    msg = p.parse_incoming({
        "type": "action_performed",
        "room_id": 1,
        "player": "bot-B",
        "action": "raise",
        "amount": 6,
        "pot": 9,
        "players": [],
    })
    assert isinstance(msg, p.ActionPerformed)
    assert msg.action == "raise"


def test_phase_change():
    msg = p.parse_incoming({
        "type": "phase_change",
        "room_id": 1,
        "phase": "flop",
        "community_cards": ["2s", "7d", "Kc"],
    })
    assert isinstance(msg, p.PhaseChange)
    assert len(msg.community_cards) == 3


def test_hand_result():
    msg = p.parse_incoming({
        "type": "hand_result",
        "room_id": 1,
        "hand_number": 5,
        "winners": [{"name": "bot-A", "amount": 52}],
        "showdown": [
            {"name": "bot-A", "cards": ["Ah", "Kh"]},
            {"name": "bot-B", "cards": ["Qd", "Qs"]},
        ],
        "community_cards": ["2s", "7d", "Kc", "4h", "9d"],
        "pot": 52,
        "eliminated": ["bot-C"],
    })
    assert isinstance(msg, p.HandResult)
    assert msg.winners[0].amount == 52
    assert msg.eliminated == ["bot-C"]


def test_game_end():
    msg = p.parse_incoming({
        "type": "game_end",
        "room_id": 1,
        "rankings": [
            {"rank": 1, "name": "bot-A", "chips": 1200},
            {"rank": 2, "name": "bot-B", "chips": 0},
        ],
    })
    assert isinstance(msg, p.GameEnd)
    assert msg.rankings[0].rank == 1


def test_joined_room_reconnect_snapshot():
    msg = p.parse_incoming({
        "type": "joined_room",
        "room_id": 1,
        "reconnected": True,
        "players": ["bot-A", "bot-B"],
        "snapshot": {
            "hand_number": 5,
            "phase": "flop",
            "community_cards": ["2s", "7d", "Kc"],
            "pot": 120,
            "blind": [5, 10],
            "players": [
                {"name": "bot-A", "stack": 280, "position": "btn", "status": "active", "bet": 0},
                {"name": "bot-B", "stack": 320, "position": "bb", "status": "active", "action": "call", "bet": 10},
            ],
            "action_history": [
                {"phase": "preflop", "player": "bot-B", "action": "call", "amount": 10},
            ],
            "your_cards": ["Ah", "Kh"],
        },
    })
    assert isinstance(msg, p.JoinedRoom)
    assert msg.reconnected is True
    assert msg.snapshot is not None
    assert msg.snapshot.phase == "flop"
    assert msg.snapshot.your_cards == ["Ah", "Kh"]


def test_joined_room_no_snapshot():
    msg = p.parse_incoming({
        "type": "joined_room",
        "room_id": 2,
        "reconnected": False,
        "players": ["bot-A"],
    })
    assert isinstance(msg, p.JoinedRoom)
    assert msg.snapshot is None


def test_unknown_type_raises():
    with pytest.raises(Exception):
        p.parse_incoming({"type": "unknown_event"})


def test_extra_fields_ignored():
    msg = p.parse_incoming({
        "type": "ping",
        "extra_field_that_server_added": 42,
    })
    assert isinstance(msg, p.Ping)


# --- outgoing ---


def test_pong_payload():
    assert p.Pong().model_dump() == {"type": "pong"}


def test_auth_bot_payload():
    msg = p.AuthBot(api_token="t", bot_name="b")
    assert msg.model_dump() == {"type": "auth_bot", "api_token": "t", "bot_name": "b"}


def test_action_fold_omits_amount():
    action = p.Action(room_id=1, action="fold")
    assert action.to_payload() == {"type": "action", "room_id": 1, "action": "fold"}


def test_action_raise_includes_amount():
    action = p.Action(room_id=1, action="raise", amount=12)
    assert action.to_payload() == {
        "type": "action", "room_id": 1, "action": "raise", "amount": 12,
    }


def test_action_call_omits_amount_even_if_set():
    """§6.1: call 은 amount 불필요 (서버 자동 계산)."""
    action = p.Action(room_id=1, action="call", amount=5)
    assert "amount" not in action.to_payload()


def test_action_allin_omits_amount():
    action = p.Action(room_id=1, action="allin")
    assert action.to_payload() == {"type": "action", "room_id": 1, "action": "allin"}


def test_season_rotated_parses():
    """P-Proto: season_rotated 이벤트가 unparseable 로 떨어지지 않고 정상 분기."""
    msg = p.parse_incoming({"type": "season_rotated", "season_name": "0501-04"})
    assert isinstance(msg, p.SeasonRotated)
    assert msg.season_name == "0501-04"


def test_season_rotated_optional_name():
    msg = p.parse_incoming({"type": "season_rotated"})
    assert isinstance(msg, p.SeasonRotated)
    assert msg.season_name is None
