"""봇 → 서버 송신 메시지 Pydantic 모델.

BOT_REFERENCE.md §2.2, §6 참고.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from holdem_core.models.events import ActionName


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AuthBot(_Base):
    type: Literal["auth_bot"] = "auth_bot"
    api_token: str
    bot_name: str


class Pong(_Base):
    type: Literal["pong"] = "pong"


class Action(_Base):
    type: Literal["action"] = "action"
    room_id: int
    action: ActionName
    amount: int | None = None
    # 결정 근거(equity/pot_odds/reason 등). exclude=True 이므로 model_dump_json
    # 결과에서 제외되어 네트워크로 나가지 않고, .debug 로그에만 병합된다.
    meta: dict[str, Any] | None = Field(default=None, exclude=True)
