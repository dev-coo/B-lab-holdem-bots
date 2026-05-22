import json
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]


class BotAction(BaseModel):
    action: str
    room_id: int
    amount: int | None = None
    reasoning: str = ""


def safe_fallback_action(to_call: int, room_id: int) -> BotAction:
    selected_action = "check" if to_call == 0 else "fold"
    return BotAction(action=selected_action, room_id=room_id)


def action_to_json(action: BotAction) -> str:
    payload = {
        "type": "action",
        "room_id": action.room_id,
        "action": action.action,
    }
    if action.amount is not None:
        payload["amount"] = action.amount
    return json.dumps(payload)
