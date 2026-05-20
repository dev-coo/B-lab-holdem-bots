"""Server ↔ bot JSON message schema.

근거: `research/bot_guide_extracts.md` §2, §5, §6, §9 — BOT_GUIDE 원문 동기.
구현 원칙:
  - 서버가 전송하는 필드만 정의. 없는 필드는 검증 실패하지 않도록 ``extra="ignore"``.
  - Union 으로 incoming 메시지 구분 → pydantic discriminator ``type``.
  - outgoing 은 별도 모델.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Phase = Literal["preflop", "flop", "turn", "river"]
ActionType = Literal["fold", "check", "call", "raise", "allin"]
PlayerStatus = Literal["active", "folded", "allin", "eliminated"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PlayerState(_Base):
    name: str
    stack: int
    position: str | None = None
    status: PlayerStatus = "active"
    action: str | None = None
    bet: int = 0


class HistoryEntry(_Base):
    phase: Phase
    player: str
    action: str
    amount: int = 0


class BlindLevel(_Base):
    level: int
    small: int
    big: int
    hands: int | None = None


# --- incoming: server → bot ---

class AuthOk(_Base):
    type: Literal["auth_ok"]
    user_id: int | None = None
    bot_name: str | None = None
    bot_tokens: int | None = None
    concurrent_games: int | None = None


class AuthFail(_Base):
    type: Literal["auth_fail"]
    reason: str = ""


class Ping(_Base):
    type: Literal["ping"]


class ServerShutdown(_Base):
    type: Literal["server_shutdown"]
    reason: str = ""


class ErrorEvent(_Base):
    type: Literal["error"]
    message: str = ""


class GameStart(_Base):
    type: Literal["game_start"]
    room_id: int
    players: list[dict[str, Any]] = Field(default_factory=list)
    starting_stack: int = 300
    blind_structure: list[BlindLevel] = Field(default_factory=list)


class WaitingRoom(_Base):
    """배정된 방의 대기 상태. min_players 채워지면 곧 게임 시작."""
    type: Literal["waiting_room"]
    room_id: int
    current_players: int = 0
    min_players: int = 0
    starts_in: int | None = None  # 초 단위


class HandStart(_Base):
    type: Literal["hand_start"]
    room_id: int
    hand_number: int
    your_cards: list[str] = Field(default_factory=list)   # 탈락/관전 시 빈 배열
    your_stack: int = 0
    your_seat: str = ""
    blind: list[int]  # [sb, bb]
    players: list[PlayerState]


class ActionRequest(_Base):
    type: Literal["action_request"]
    room_id: int
    hand_number: int
    your_cards: list[str]
    community_cards: list[str] = Field(default_factory=list)
    phase: Phase
    pot: int
    my_stack: int
    to_call: int
    min_raise: int
    blind: list[int]
    seat: str
    players: list[PlayerState]
    action_history: list[HistoryEntry] = Field(default_factory=list)
    timeout_ms: int = 30_000


class ActionPerformed(_Base):
    type: Literal["action_performed"]
    room_id: int
    player: str
    action: ActionType
    amount: int = 0
    pot: int = 0
    players: list[PlayerState] = Field(default_factory=list)


class PhaseChange(_Base):
    type: Literal["phase_change"]
    room_id: int
    phase: Phase
    community_cards: list[str]


class Winner(_Base):
    name: str
    amount: int


class Showdown(_Base):
    name: str
    cards: list[str]


class HandResult(_Base):
    type: Literal["hand_result"]
    room_id: int
    hand_number: int
    winners: list[Winner]
    showdown: list[Showdown] = Field(default_factory=list)
    community_cards: list[str] = Field(default_factory=list)
    pot: int = 0
    eliminated: list[str] = Field(default_factory=list)


class PlayerJoinedPayload(_Base):
    name: str
    type: str = "bot"
    stack: int = 0


class PlayerJoined(_Base):
    type: Literal["player_joined"]
    room_id: int
    player: PlayerJoinedPayload


class PlayerLeft(_Base):
    type: Literal["player_left"]
    room_id: int
    player: str


class Ranking(_Base):
    rank: int
    name: str
    chips: int


class GameEnd(_Base):
    type: Literal["game_end"]
    room_id: int
    rankings: list[Ranking] = Field(default_factory=list)


class JoinedSnapshot(_Base):
    hand_number: int | None = None
    phase: Phase | None = None
    community_cards: list[str] = Field(default_factory=list)
    pot: int = 0
    blind: list[int] = Field(default_factory=list)
    players: list[PlayerState] = Field(default_factory=list)
    action_history: list[HistoryEntry] = Field(default_factory=list)
    your_cards: list[str] = Field(default_factory=list)


class JoinedRoom(_Base):
    type: Literal["joined_room"]
    room_id: int
    reconnected: bool = False
    players: list[str] = Field(default_factory=list)
    snapshot: JoinedSnapshot | None = None


class SeasonRotated(_Base):
    """시즌 전환 알림 — 봇 동작에 직접 영향 없음, 가시성용."""
    type: Literal["season_rotated"]
    season_name: str | None = None


IncomingEvent = Annotated[
    AuthOk
    | AuthFail
    | Ping
    | ServerShutdown
    | ErrorEvent
    | GameStart
    | WaitingRoom
    | HandStart
    | ActionRequest
    | ActionPerformed
    | PhaseChange
    | HandResult
    | PlayerJoined
    | PlayerLeft
    | GameEnd
    | JoinedRoom
    | SeasonRotated,
    Field(discriminator="type"),
]

_INCOMING_ADAPTER = TypeAdapter(IncomingEvent)


def parse_incoming(payload: dict[str, Any]):
    """서버 payload → 구체 이벤트 모델. 타입 미등록 시 ValueError."""
    return _INCOMING_ADAPTER.validate_python(payload)


# --- outgoing: bot → server ---

class AuthBot(_Base):
    type: Literal["auth_bot"] = "auth_bot"
    api_token: str
    bot_name: str


class Pong(_Base):
    type: Literal["pong"] = "pong"


class Action(_Base):
    """bot → server action response.

    BOT_GUIDE §6:
      - fold / check / call / allin: amount 불필요 (None)
      - raise: amount 필수 (이번 라운드 총 베팅액)
    """
    type: Literal["action"] = "action"
    room_id: int
    action: ActionType
    amount: int | None = None

    def to_payload(self) -> dict[str, Any]:
        data = {"type": self.type, "room_id": self.room_id, "action": self.action}
        if self.action == "raise" and self.amount is not None:
            data["amount"] = self.amount
        return data
