import pytest
from pydantic import ValidationError

from holdem_agent.models.events import (
    ActionPerformedEvent,
    ActionRequestEvent,
    AuthEvent,
    AuthFailEvent,
    AuthOkEvent,
    ErrorEvent,
    GameEndEvent,
    GameStartEvent,
    HandResultEvent,
    HandStartEvent,
    PingEvent,
    PhaseChangeEvent,
    parse_event,
)


def test_auth_event_creation() -> None:
    payload = {
        "type": "auth_bot",
        "api_token": "abc123",
        "bot_name": "bot-1",
    }
    event = AuthEvent(**payload)

    assert event == AuthEvent.model_validate(payload)
    assert event.type == "auth_bot"
    assert event.api_token == "abc123"
    assert event.bot_name == "bot-1"


def test_auth_ok_event_creation() -> None:
    payload = {
        "type": "auth_ok",
        "player_type": "bot",
        "bot_name": "bot-1",
        "concurrent_games": 2,
    }
    event = AuthOkEvent(**payload)

    assert event.player_type == "bot"
    assert event.concurrent_games == 2


def test_auth_fail_event_creation() -> None:
    payload = {"type": "auth_fail", "reason": "invalid token"}
    event = AuthFailEvent(**payload)

    assert event.reason == "invalid token"


def test_game_start_event_creation() -> None:
    payload = {
        "type": "game_start",
        "room_id": 9,
        "players": [
            {"name": "a", "type": "bot", "stack": 1000},
            {"name": "b", "type": "human", "stack": 1000},
        ],
        "starting_stack": 1000,
        "blind_structure": [
            {"level": 1, "small": 10, "big": 20, "hands": 50}
        ],
    }
    event = GameStartEvent(**payload)

    assert event.room_id == 9
    assert event.starting_stack == 1000
    assert len(event.players) == 2
    assert event.blind_structure[0].level == 1


def test_game_start_event_allows_missing_blind_structure() -> None:
    payload = {
        "type": "game_start",
        "room_id": 9,
        "players": [
            {"name": "a", "type": "bot", "stack": 1000},
            {"name": "b", "type": "human", "stack": 1000},
        ],
        "starting_stack": 1000,
    }
    event = GameStartEvent(**payload)

    assert event.blind_structure == []


def test_hand_start_event_creation() -> None:
    payload = {
        "type": "hand_start",
        "room_id": 9,
        "hand_number": 1,
        "your_cards": ["Ah", "Ad"],
        "your_stack": 980,
        "your_seat": "BTN",
        "blind": [1, 2],
        "players": [
            {
                "name": "a",
                "stack": 980,
                "position": "BTN",
                "status": "active",
                "action": None,
                "bet": 20,
            },
            {
                "name": "b",
                "stack": 1000,
                "position": "BB",
                "status": "active",
            },
        ],
    }
    event = HandStartEvent(**payload)

    assert event.hand_number == 1
    assert event.your_cards == ["Ah", "Ad"]
    assert event.blind == (1, 2)
    assert event.your_seat == "BTN"


def test_action_request_event_creation() -> None:
    payload = {
        "type": "action_request",
        "room_id": 9,
        "hand_number": 1,
        "your_cards": ["Ah", "Ad"],
        "community_cards": ["2c", "7d", "Ts"],
        "phase": "flop",
        "pot": 40,
        "my_stack": 960,
        "to_call": 20,
        "min_raise": 40,
        "blind": [10, 20],
        "seat": "BTN",
        "players": [
            {
                "name": "a",
                "stack": 960,
                "position": "BTN",
                "status": "active",
                "action": "check",
                "bet": 20,
            }
        ],
        "action_history": [
            {
                "phase": "preflop",
                "player": "b",
                "action": "call",
                "amount": 20,
            }
        ],
    }
    event = ActionRequestEvent(**payload)

    assert event.phase == "flop"
    assert event.to_call == 20
    assert event.timeout_ms == 30000
    assert event.action_history[0].action == "call"


def test_action_performed_event_creation() -> None:
    payload = {
        "type": "action_performed",
        "room_id": 9,
        "player": "a",
        "action": "call",
        "amount": 20,
        "pot": 60,
        "players": [
            {
                "name": "a",
                "stack": 940,
                "position": "BTN",
                "status": "active",
                "action": "call",
                "bet": 20,
            }
        ],
    }
    event = ActionPerformedEvent(**payload)

    assert event.player == "a"
    assert event.amount == 20


def test_phase_change_event_creation() -> None:
    payload = {
        "type": "phase_change",
        "room_id": 9,
        "phase": "turn",
        "community_cards": ["2c", "7d", "Ts", "Qh"],
    }
    event = PhaseChangeEvent(**payload)

    assert event.phase == "turn"
    assert event.community_cards == ["2c", "7d", "Ts", "Qh"]


def test_hand_result_event_creation() -> None:
    payload = {
        "type": "hand_result",
        "room_id": 9,
        "hand_number": 1,
        "winners": [
            {
                "name": "a",
                "amount": 160,
            }
        ],
        "showdown": [
            {
                "name": "a",
                "cards": ["Ah", "Ad", "2c", "7d", "Ts"],
            }
        ],
        "community_cards": ["2c", "7d", "Ts", "Qh", "Ks"],
        "pot": 200,
        "eliminated": ["c"],
    }
    event = HandResultEvent(**payload)

    assert event.room_id == 9
    assert event.winners[0]["name"] == "a"
    assert event.eliminated == ["c"]


def test_game_end_event_creation() -> None:
    payload = {
        "type": "game_end",
        "room_id": 9,
        "rankings": [
            {"name": "a", "position": 1, "chips": 2500},
            {"name": "b", "position": 2, "chips": 2000},
        ],
    }
    event = GameEndEvent(**payload)

    assert event.rankings[1]["name"] == "b"
    assert event.rankings[1]["position"] == 2


def test_ping_event_creation() -> None:
    event = PingEvent()

    assert event.type == "ping"


def test_error_event_creation() -> None:
    event = ErrorEvent(type="error", message="boom")

    assert event.message == "boom"


def test_parse_event_dispatches_all_types() -> None:
    cases = [
        (
            AuthEvent(type="auth_bot", api_token="x", bot_name="y"),
            {"type": "auth_bot", "api_token": "x", "bot_name": "y"},
        ),
        (
            AuthOkEvent(type="auth_ok", player_type="bot", bot_name="y", concurrent_games=1),
            {
                "type": "auth_ok",
                "player_type": "bot",
                "bot_name": "y",
                "concurrent_games": 1,
            },
        ),
        (AuthFailEvent(type="auth_fail", reason="bad"), {"type": "auth_fail", "reason": "bad"}),
        (
            GameStartEvent(
                type="game_start",
                room_id=1,
                players=[{"name": "a", "type": "bot"}],
                starting_stack=1000,
                blind_structure=[{"level": 1, "small": 1, "big": 2, "hands": 10}],
            ),
            {
                "type": "game_start",
                "room_id": 1,
                "players": [{"name": "a", "type": "bot"}],
                "starting_stack": 1000,
                "blind_structure": [{"level": 1, "small": 1, "big": 2, "hands": 10}],
            },
        ),
        (
            HandStartEvent(
                type="hand_start",
                room_id=1,
                hand_number=1,
                your_cards=["Ah", "Kc"],
                your_stack=100,
                your_seat="BTN",
                blind=(1, 2),
                players=[{"name": "a", "stack": 100, "position": "BTN", "status": "active"}],
            ),
            {
                "type": "hand_start",
                "room_id": 1,
                "hand_number": 1,
                "your_cards": ["Ah", "Kc"],
                "your_stack": 100,
                "your_seat": "BTN",
                "blind": [1, 2],
                "players": [{"name": "a", "stack": 100, "position": "BTN", "status": "active"}],
            },
        ),
        (
            PhaseChangeEvent(type="phase_change", room_id=1, phase="flop", community_cards=["2c"]),
            {"type": "phase_change", "room_id": 1, "phase": "flop", "community_cards": ["2c"]},
        ),
        (
            HandResultEvent(
                type="hand_result",
                room_id=1,
                hand_number=1,
                winners=[{"name": "a"}],
                showdown=[{"name": "a"}],
                community_cards=["2c"],
                pot=10,
            ),
            {
                "type": "hand_result",
                "room_id": 1,
                "hand_number": 1,
                "winners": [{"name": "a"}],
                "showdown": [{"name": "a"}],
                "community_cards": ["2c"],
                "pot": 10,
            },
        ),
        (
            GameEndEvent(type="game_end", room_id=1, rankings=[{"name": "a"}]),
            {"type": "game_end", "room_id": 1, "rankings": [{"name": "a"}]},
        ),
        (PingEvent(), {"type": "ping"}),
        (ErrorEvent(type="error", message="oops"), {"type": "error", "message": "oops"}),
    ]

    for expected, payload in cases:
        parsed = parse_event(payload)
        assert type(parsed) is type(expected)
        assert parsed == expected


def test_parse_action_request_dispatch() -> None:
    payload = {
        "type": "action_request",
        "room_id": 3,
        "hand_number": 2,
        "your_cards": ["Ah", "Ad"],
        "community_cards": ["2c", "7d", "Ts"],
        "phase": "flop",
        "pot": 40,
        "my_stack": 960,
        "to_call": 20,
        "min_raise": 40,
        "blind": [10, 20],
        "seat": "BTN",
        "players": [
            {
                "name": "a",
                "stack": 960,
                "position": "BTN",
                "status": "active",
                "action": "check",
                "bet": 20,
            }
        ],
        "action_history": [
            {
                "phase": "preflop",
                "player": "b",
                "action": "call",
                "amount": 20,
            }
        ],
    }
    parsed = parse_event(payload)

    assert isinstance(parsed, ActionRequestEvent)
    assert parsed.to_call == 20


def test_parse_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown event type"):
        parse_event({"type": "does_not_exist"})


def test_event_frozen() -> None:
    event = ActionPerformedEvent(
        room_id=2,
        player="a",
        action="fold",
        pot=0,
        players=[{"name": "a", "stack": 1000, "position": "BTN", "status": "active"}],
    )

    with pytest.raises(ValidationError):
        event.action = "call"


def test_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        HandStartEvent(type="hand_start", room_id=1, hand_number=1, your_cards=["Ah"])

    with pytest.raises(ValidationError):
        AuthOkEvent(type="auth_ok", player_type="bot", concurrent_games=2)
