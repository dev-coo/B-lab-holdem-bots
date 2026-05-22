from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from holdem_agent.models.state import ActionRecord, BlindLevel, PlayerInfo, PlayerState


class AuthEvent(BaseModel):
    type: Literal["auth_bot"] = "auth_bot"
    api_token: str
    bot_name: str

    model_config = ConfigDict(frozen=True)


class AuthOkEvent(BaseModel):
    type: Literal["auth_ok"] = "auth_ok"
    player_type: str = "bot"
    bot_name: str
    concurrent_games: int

    model_config = ConfigDict(frozen=True)


class AuthFailEvent(BaseModel):
    type: Literal["auth_fail"] = "auth_fail"
    reason: str

    model_config = ConfigDict(frozen=True)


class GameStartEvent(BaseModel):
    type: Literal["game_start"] = "game_start"
    room_id: int
    players: list[PlayerInfo]
    starting_stack: int
    blind_structure: list[BlindLevel] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


class HandStartEvent(BaseModel):
    type: Literal["hand_start"] = "hand_start"
    room_id: int
    hand_number: int
    your_cards: list[str] = Field(default_factory=list)
    your_stack: int | None = None
    your_seat: str | None = None
    blind: tuple[int, int]
    players: list[PlayerState]

    model_config = ConfigDict(frozen=True)


class ActionRequestEvent(BaseModel):
    type: Literal["action_request"] = "action_request"
    room_id: int
    hand_number: int
    your_cards: list[str]
    community_cards: list[str]
    phase: str
    pot: int
    my_stack: int
    to_call: int
    min_raise: int
    blind: tuple[int, int]
    seat: str
    players: list[PlayerState]
    action_history: list[ActionRecord]
    timeout_ms: int = 30000

    model_config = ConfigDict(frozen=True)


class ActionPerformedEvent(BaseModel):
    type: Literal["action_performed"] = "action_performed"
    room_id: int
    player: str
    action: str
    amount: int | None = None
    pot: int
    players: list[PlayerState]
    next_player: str | None = None
    timeout_ms: int | None = None

    model_config = ConfigDict(frozen=True)


class WaitingRoomEvent(BaseModel):
    type: Literal["waiting_room"] = "waiting_room"
    room_id: int
    current_players: int
    min_players: int
    starts_in: int | None = None

    model_config = ConfigDict(frozen=True)


class PhaseChangeEvent(BaseModel):
    type: Literal["phase_change"] = "phase_change"
    room_id: int
    phase: str
    community_cards: list[str]

    model_config = ConfigDict(frozen=True)


class HandResultEvent(BaseModel):
    type: Literal["hand_result"] = "hand_result"
    room_id: int
    hand_number: int
    winners: list[dict[str, object]]
    showdown: list[dict[str, object]]
    community_cards: list[str]
    pot: int
    eliminated: list[str] = []

    model_config = ConfigDict(frozen=True)


class GameEndEvent(BaseModel):
    type: Literal["game_end"] = "game_end"
    room_id: int
    rankings: list[dict[str, object]]

    model_config = ConfigDict(frozen=True)


class PingEvent(BaseModel):
    type: Literal["ping"] = "ping"

    model_config = ConfigDict(frozen=True)


class JoinedRoomEvent(BaseModel):
    type: Literal["joined_room"] = "joined_room"
    room_id: int
    reconnected: bool = False
    players: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any] | None = None

    model_config = ConfigDict(frozen=True)


class PlayerJoinedEvent(BaseModel):
    type: Literal["player_joined"] = "player_joined"
    room_id: int
    player: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class PlayerLeftEvent(BaseModel):
    type: Literal["player_left"] = "player_left"
    room_id: int
    player: str = ""

    model_config = ConfigDict(frozen=True)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str

    model_config = ConfigDict(frozen=True)


class UnknownEventType(ValueError):
    """Raised when a server event has a type not handled by parse_event."""


def parse_event(data: dict[str, Any]) -> BaseModel:
    event_type = data.get("type")

    if event_type == "auth_bot":
        return AuthEvent(**data)
    if event_type == "auth_ok":
        return AuthOkEvent(**data)
    if event_type == "auth_fail":
        return AuthFailEvent(**data)
    if event_type == "game_start":
        return GameStartEvent(**data)
    if event_type == "hand_start":
        return HandStartEvent(**data)
    if event_type == "action_request":
        return ActionRequestEvent(**data)
    if event_type == "action_performed":
        return ActionPerformedEvent(**data)
    if event_type == "waiting_room":
        return WaitingRoomEvent(**data)
    if event_type == "phase_change":
        return PhaseChangeEvent(**data)
    if event_type == "hand_result":
        return HandResultEvent(**data)
    if event_type == "game_end":
        return GameEndEvent(**data)
    if event_type == "ping":
        return PingEvent(**data)
    if event_type == "joined_room":
        return JoinedRoomEvent(**data)
    if event_type == "player_joined":
        return PlayerJoinedEvent(**data)
    if event_type == "player_left":
        return PlayerLeftEvent(**data)
    if event_type == "error":
        return ErrorEvent(**data)

    raise UnknownEventType(f"Unknown event type: {event_type!r}")
