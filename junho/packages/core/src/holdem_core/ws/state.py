"""봇 내부 게임 상태 저장소."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from holdem_core.models.events import (
    ActionPerformed,
    ActionRequest,
    HandResult,
    HandStart,
    JoinedRoom,
    PhaseChange,
)


@dataclass
class GameState:
    room_id: int
    hand_number: int | None = None
    phase: str | None = None
    your_cards: list[str] = field(default_factory=list)
    community_cards: list[str] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    my_seat: str | None = None
    my_stack: int | None = None


@dataclass
class ActionLog:
    ts: float
    room_id: int
    phase: str | None
    your_cards: list[str]
    to_call: int
    action: str
    amount: int | None


def _players_to_dicts(players: list[Any]) -> list[dict[str, Any]]:
    return [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in players]


class StateStore:
    def __init__(self, buffer_size: int = 50) -> None:
        self.rooms: dict[int, GameState] = {}
        self.recent_actions: deque[ActionLog] = deque(maxlen=buffer_size)
        self.connected: bool = False
        self.authenticated: bool = False

    def _room(self, room_id: int) -> GameState:
        room = self.rooms.get(room_id)
        if room is None:
            room = GameState(room_id=room_id)
            self.rooms[room_id] = room
        return room

    def on_joined_room(self, evt: JoinedRoom) -> None:
        self._room(evt.room_id)

    def on_hand_start(self, evt: HandStart) -> None:
        room = self._room(evt.room_id)
        room.hand_number = evt.hand_number
        room.phase = "preflop"
        room.your_cards = list(evt.your_cards)
        room.community_cards = []
        room.players = _players_to_dicts(evt.players)
        room.action_history = []
        room.my_seat = evt.your_seat
        room.my_stack = evt.your_stack

    def on_action_request(self, evt: ActionRequest) -> None:
        room = self._room(evt.room_id)
        room.hand_number = evt.hand_number
        room.phase = evt.phase
        room.your_cards = list(evt.your_cards)
        room.community_cards = list(evt.community_cards)
        room.players = _players_to_dicts(evt.players)
        room.action_history = [item.model_dump() for item in evt.action_history]
        room.my_seat = evt.seat
        room.my_stack = evt.my_stack

    def on_phase_change(self, evt: PhaseChange) -> None:
        room = self._room(evt.room_id)
        room.phase = evt.phase
        room.community_cards = list(evt.community_cards)

    def on_action_performed(self, evt: ActionPerformed) -> None:
        room = self._room(evt.room_id)
        room.players = _players_to_dicts(evt.players)
        room.action_history.append(
            {
                "phase": room.phase,
                "player": evt.player,
                "action": evt.action,
                "amount": evt.amount,
            }
        )

    def on_hand_result(self, evt: HandResult) -> None:
        room = self._room(evt.room_id)
        room.community_cards = list(evt.community_cards)
        room.phase = None
        room.your_cards = []

    def record_action(self, log: ActionLog) -> None:
        self.recent_actions.append(log)

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "authenticated": self.authenticated,
            "rooms": {
                str(rid): {
                    "room_id": room.room_id,
                    "hand_number": room.hand_number,
                    "phase": room.phase,
                    "your_cards": list(room.your_cards),
                    "community_cards": list(room.community_cards),
                    "players": list(room.players),
                    "action_history": list(room.action_history),
                    "my_seat": room.my_seat,
                    "my_stack": room.my_stack,
                }
                for rid, room in self.rooms.items()
            },
            "recent_actions": [
                {
                    "ts": log.ts,
                    "room_id": log.room_id,
                    "phase": log.phase,
                    "your_cards": list(log.your_cards),
                    "to_call": log.to_call,
                    "action": log.action,
                    "amount": log.amount,
                }
                for log in self.recent_actions
            ],
        }
