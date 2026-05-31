from pydantic import BaseModel, ConfigDict


class PlayerState(BaseModel):
    name: str
    stack: int
    position: str
    status: str
    action: str | None = None
    bet: int = 0

    model_config = ConfigDict(frozen=True)


class ActionRecord(BaseModel):
    phase: str
    player: str
    action: str
    amount: int

    model_config = ConfigDict(frozen=True)


class BlindLevel(BaseModel):
    level: int
    small: int
    big: int
    hands: int

    model_config = ConfigDict(frozen=True)


class PlayerInfo(BaseModel):
    name: str
    type: str
    stack: int | None = None

    model_config = ConfigDict(frozen=True)
