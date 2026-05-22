import json

import pytest

from holdem_agent.client.protocol import encode_action, encode_pong, parse_message


def test_parse_message_returns_valid_payload() -> None:
    raw = json.dumps({
        "type": "auth_ok",
        "player_type": "bot",
        "bot_name": "bot-1",
        "concurrent_games": 2,
    })

    assert parse_message(raw) == {
        "type": "auth_ok",
        "player_type": "bot",
        "bot_name": "bot-1",
        "concurrent_games": 2,
    }


def test_parse_message_applies_event_defaults() -> None:
    raw = json.dumps(
        {
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
                }
            ],
            "action_history": [],
        }
    )

    assert parse_message(raw)["timeout_ms"] == 30000


def test_parse_message_accepts_hand_start_without_private_fields() -> None:
    raw = json.dumps(
        {
            "type": "hand_start",
            "room_id": 9,
            "hand_number": 3,
            "blind": [1, 2],
            "players": [
                {
                    "name": "a",
                    "stack": 0,
                    "position": "BTN",
                    "status": "eliminated",
                    "action": None,
                    "bet": 0,
                }
            ],
        }
    )

    parsed = parse_message(raw)

    assert parsed["your_cards"] == []
    assert parsed["your_stack"] is None
    assert parsed["your_seat"] is None


def test_parse_message_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_message("not json")


def test_parse_message_passes_through_unknown_event_type() -> None:
    """Forward-compat: undocumented event types must not kill the loop."""
    out = parse_message('{"type": "mystery", "room_id": 1}')
    assert out == {"type": "mystery", "room_id": 1}


def test_parse_message_handles_joined_room_with_snapshot() -> None:
    payload = {
        "type": "joined_room",
        "room_id": 1,
        "reconnected": True,
        "players": ["bot-A"],
        "snapshot": {"hand_number": 5, "phase": "flop"},
    }
    out = parse_message(json.dumps(payload))
    assert out["type"] == "joined_room"
    assert out["snapshot"] == {"hand_number": 5, "phase": "flop"}


def test_parse_message_handles_player_joined_and_left() -> None:
    out = parse_message(
        json.dumps(
            {
                "type": "player_joined",
                "room_id": 1,
                "player": {"name": "x", "type": "human", "stack": 300},
            }
        )
    )
    assert out["type"] == "player_joined"
    assert out["player"]["name"] == "x"

    out = parse_message(json.dumps({"type": "player_left", "room_id": 1, "player": "x"}))
    assert out["type"] == "player_left"
    assert out["player"] == "x"


def test_encode_action_without_amount() -> None:
    assert json.loads(encode_action(9, "fold")) == {
        "type": "action",
        "room_id": 9,
        "action": "fold",
    }


def test_encode_action_with_amount() -> None:
    assert json.loads(encode_action(9, "raise", 120)) == {
        "type": "action",
        "room_id": 9,
        "action": "raise",
        "amount": 120,
    }


def test_encode_pong() -> None:
    assert json.loads(encode_pong()) == {"type": "pong"}
