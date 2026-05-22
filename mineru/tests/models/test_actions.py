import json

from holdem_agent.models.actions import BotAction, action_to_json, safe_fallback_action  # pyright: ignore[reportMissingImports]


def test_bot_action_fold() -> None:
    action = BotAction(action="fold", room_id=3)

    assert action.action == "fold"
    assert action.room_id == 3
    assert action.amount is None
    assert action.reasoning == ""


def test_bot_action_raise() -> None:
    action = BotAction(action="raise", room_id=3, amount=50)

    assert action.action == "raise"
    assert action.room_id == 3
    assert action.amount == 50


def test_safe_fallback_check() -> None:
    action = safe_fallback_action(to_call=0, room_id=7)

    assert action.action == "check"
    assert action.room_id == 7
    assert action.amount is None


def test_safe_fallback_fold() -> None:
    action = safe_fallback_action(to_call=5, room_id=7)

    assert action.action == "fold"
    assert action.room_id == 7
    assert action.amount is None


def test_action_to_json_fold() -> None:
    payload = action_to_json(BotAction(action="fold", room_id=12))
    data = json.loads(payload)

    assert data["type"] == "action"
    assert data["room_id"] == 12
    assert data["action"] == "fold"
    assert "amount" not in data


def test_action_to_json_raise() -> None:
    payload = action_to_json(BotAction(action="raise", room_id=12, amount=100))
    data = json.loads(payload)

    assert data["type"] == "action"
    assert data["room_id"] == 12
    assert data["action"] == "raise"
    assert data["amount"] == 100
