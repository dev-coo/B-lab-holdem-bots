import json
import logging

from holdem_agent.models.events import UnknownEventType, parse_event

logger = logging.getLogger(__name__)


def parse_message(raw: str) -> dict[str, object]:
    """Parse raw JSON string to dict. Raises ValueError on invalid JSON.

    Unknown event types are passed through as the raw dict with a warning,
    so a single undocumented server event never kills the connection.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON message") from exc

    if not isinstance(payload, dict):
        raise ValueError("Message payload must be a JSON object")

    if payload.get("type") == "server_shutdown":
        return payload

    try:
        return parse_event(payload).model_dump()
    except UnknownEventType:
        logger.warning("Passing through unknown event type: %s", payload.get("type"))
        return payload


def encode_action(room_id: int, action: str, amount: int | None = None) -> str:
    """Encode bot action to JSON string for sending to server."""
    payload: dict[str, object] = {
        "type": "action",
        "room_id": room_id,
        "action": action,
    }
    if amount is not None:
        payload["amount"] = amount
    return json.dumps(payload)


def encode_pong() -> str:
    """Return pong JSON string."""
    return json.dumps({"type": "pong"})
