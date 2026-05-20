"""API 요청/응답 모델 — BOT_REFERENCE.md 기반"""

from __future__ import annotations
from pydantic import BaseModel


# ── /action ──

class PlayerInfo(BaseModel):
    name: str
    stack: int
    position: str
    status: str          # active / folded / allin / eliminated
    action: str | None = None
    bet: int = 0


class ActionRecord(BaseModel):
    phase: str
    player: str
    action: str
    amount: int = 0


class ActionRequest(BaseModel):
    game_id: str
    hand_number: int
    pocket_cards: list[str]       # ["Th", "Jh"]
    community_cards: list[str]    # [] ~ 5장
    phase: str                    # preflop / flop / turn / river
    pot: int
    blind: list[int]              # [small, big]
    my_stack: int
    investment: int
    to_call: int
    min_raise: int
    seat: str
    players: list[PlayerInfo]
    action_history: list[ActionRecord] = []


class ActionResponse(BaseModel):
    action: str                   # fold / check / call / raise / allin
    amount: int | None = None     # raise 시 필수


# ── /hand_result ──

class Winner(BaseModel):
    name: str
    amount: int


class ShowdownPlayer(BaseModel):
    name: str
    cards: list[str]


class HandResultRequest(BaseModel):
    game_id: str
    hand_number: int
    winners: list[Winner]
    showdown: list[ShowdownPlayer] = []
    community_cards: list[str] = []
    pot: int = 0


# ── /game_start ──

class BlindLevel(BaseModel):
    level: int
    small: int
    big: int
    hands: int


class GameStartRequest(BaseModel):
    game_id: str
    players: list[str]
    starting_stack: int = 300
    blind_structure: list[BlindLevel] = []
    rake_enabled: bool = False


# ── /game_over ──

class Ranking(BaseModel):
    rank: int
    name: str
    chips: int


class GameOverRequest(BaseModel):
    game_id: str
    rankings: list[Ranking]
