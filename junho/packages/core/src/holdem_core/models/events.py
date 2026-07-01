"""서버 → 봇 수신 이벤트 Pydantic 모델.

BOT_REFERENCE.md §2, §5 참고. Pydantic v2 discriminated union 사용.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

CardStr = Annotated[str, Field(pattern=r"^[2-9TJQKA][shdc]$")]
Phase = Literal["preflop", "flop", "turn", "river"]
Position = Literal["btn", "sb", "bb", "utg", "utg1", "mp", "mp1", "hj", "co"]
ActionName = Literal["fold", "check", "call", "raise", "allin"]
PlayerStatus = Literal["active", "folded", "allin", "eliminated"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PlayerState(_Base):
    name: str
    stack: int
    position: str
    status: PlayerStatus
    action: str | None = None
    bet: int = 0


class ActionHistoryItem(_Base):
    phase: Phase
    player: str
    action: str
    amount: int


class AuthOk(_Base):
    type: Literal["auth_ok"]
    user_id: int | None = None
    bot_name: str
    bot_tokens: int | None = None
    concurrent_games: int


class AuthFail(_Base):
    type: Literal["auth_fail"]
    reason: str


class Ping(_Base):
    type: Literal["ping"]


class ServerShutdown(_Base):
    type: Literal["server_shutdown"]
    reason: str | None = None


class GameStart(_Base):
    type: Literal["game_start"]
    room_id: int
    players: list[dict[str, Any]]
    starting_stack: int
    blind_structure: list[dict[str, Any]] = []


class HandStart(_Base):
    type: Literal["hand_start"]
    room_id: int
    hand_number: int
    # v5.4: 미배정(spectator) broadcast 도 silent fail 없이 받기 위해 Optional.
    # 정상 seated hand 면 서버가 다 채워서 보낸다. 셋 중 하나라도 None 이면
    # ws/client._dispatch 에서 ERROR 로그 + skip — 봇이 아직 deploy 안 됐다는 신호.
    your_cards: list[CardStr] = []
    your_stack: int = 0
    your_seat: str | None = None
    blind: list[int]
    players: list[PlayerState]


class ActionRequest(_Base):
    type: Literal["action_request"]
    room_id: int
    hand_number: int
    your_cards: list[CardStr]
    community_cards: list[CardStr]
    phase: Phase
    pot: int
    my_stack: int
    to_call: int
    min_raise: int
    blind: list[int]
    seat: str
    players: list[PlayerState]
    action_history: list[ActionHistoryItem]
    timeout_ms: int


class ActionPerformed(_Base):
    type: Literal["action_performed"]
    room_id: int
    player: str
    action: str
    amount: int
    pot: int
    players: list[PlayerState]


class PhaseChange(_Base):
    type: Literal["phase_change"]
    room_id: int
    phase: Phase
    community_cards: list[CardStr]


class HandResult(_Base):
    type: Literal["hand_result"]
    room_id: int
    hand_number: int
    winners: list[dict[str, Any]]
    showdown: list[dict[str, Any]]
    community_cards: list[CardStr]
    pot: int
    eliminated: list[str]


class PlayerJoined(_Base):
    type: Literal["player_joined"]
    room_id: int
    player: dict[str, Any]


class PlayerLeft(_Base):
    type: Literal["player_left"]
    room_id: int
    player: str


class GameEnd(_Base):
    type: Literal["game_end"]
    room_id: int
    rankings: list[dict[str, Any]]


class JoinedRoom(_Base):
    type: Literal["joined_room"]
    room_id: int
    reconnected: bool | None = None
    players: list[str] | None = None
    snapshot: dict[str, Any] | None = None


class Error(_Base):
    type: Literal["error"]
    message: str


class WaitingRoom(_Base):
    type: Literal["waiting_room"]
    room_id: int | None = None
    max_players: int | None = None
    min_players: int | None = None
    players: list[Any] = []


Incoming = Annotated[
    AuthOk
    | AuthFail
    | Ping
    | ServerShutdown
    | GameStart
    | HandStart
    | ActionRequest
    | ActionPerformed
    | PhaseChange
    | HandResult
    | PlayerJoined
    | PlayerLeft
    | GameEnd
    | JoinedRoom
    | Error
    | WaitingRoom,
    Field(discriminator="type"),
]

IncomingAdapter: TypeAdapter[Incoming] = TypeAdapter(Incoming)
