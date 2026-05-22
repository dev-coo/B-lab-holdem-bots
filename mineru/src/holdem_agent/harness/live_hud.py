import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TextIO, cast

logger = logging.getLogger(__name__)


@dataclass
class LiveHud:
    """Compact live game progress summary for terminal runs."""

    bot_name: str
    active_rooms: set[int] = field(default_factory=set)
    games_started: int = 0
    games_finished: int = 0
    wins: int = 0
    total_rank: int = 0
    hands_seen: int = 0
    hands_won: int = 0
    actions: Counter[str] = field(default_factory=Counter)
    output: TextIO = field(default_factory=lambda: sys.stderr, repr=False)

    def game_started(self, msg: dict[str, object]) -> None:
        room_id = _room_id(msg)
        if room_id not in self.active_rooms:
            self.active_rooms.add(room_id)
            self.games_started += 1
        self._render(f"game_start room={room_id}")

    def hand_started(self, msg: dict[str, object]) -> None:
        self.hands_seen += 1
        room_id = _room_id(msg)
        hand_number = msg.get("hand_number", "?")
        cards = " ".join(cast(list[str], msg.get("your_cards", []))) or "?"
        stack = msg.get("your_stack", "?")
        self._render(f"hand_start room={room_id} hand={hand_number} cards={cards} stack={stack}")

    def action_sent(self, room_id: int, action: str, amount: int | None) -> None:
        self.actions[action] += 1
        amount_part = "" if amount is None else f" amount={amount}"
        self._render(f"action room={room_id} {action}{amount_part}")

    def hand_finished(self, msg: dict[str, object]) -> None:
        winners = cast(list[dict[str, object]], msg.get("winners", []))
        won = any(winner.get("name") == self.bot_name for winner in winners)
        if won:
            self.hands_won += 1
        room_id = _room_id(msg)
        pot = msg.get("pot", "?")
        result = "won" if won else "lost"
        self._render(f"hand_result room={room_id} {result} pot={pot}")

    def game_finished(self, msg: dict[str, object]) -> None:
        room_id = _room_id(msg)
        self.active_rooms.discard(room_id)
        self.games_finished += 1

        rank = self._rank_for_bot(msg)
        if rank is not None:
            self.total_rank += rank
            if rank == 1:
                self.wins += 1

        rank_part = "rank=?" if rank is None else f"rank={rank}"
        self._render(f"game_end room={room_id} {rank_part}")

    def _rank_for_bot(self, msg: dict[str, object]) -> int | None:
        rankings = cast(list[dict[str, object]], msg.get("rankings", []))
        for ranking in rankings:
            if ranking.get("name") == self.bot_name and isinstance(ranking.get("rank"), int):
                return cast(int, ranking["rank"])
        return None

    def _render(self, event: str) -> None:
        lines = self._lines(event)
        self._draw_fixed(lines)
        logger.debug("[HUD] %s", " | ".join(lines))

    def _lines(self, event: str) -> list[str]:
        losses = self.games_finished - self.wins
        win_rate = _percent(self.wins, self.games_finished)
        hand_win_rate = _percent(self.hands_won, self.hands_seen)
        avg_rank = self.total_rank / self.games_finished if self.games_finished else 0.0
        action_text = ", ".join(f"{name}:{count}" for name, count in sorted(self.actions.items()))
        if not action_text:
            action_text = "-"
        rooms = ", ".join(str(room) for room in sorted(self.active_rooms)) or "-"

        return [
            "Holdem Agent HUD",
            f"Bot: {self.bot_name}",
            f"Last: {event}",
            (
                f"Games: active={len(self.active_rooms)} started={self.games_started} "
                f"finished={self.games_finished} W-L={self.wins}-{losses} "
                f"win={win_rate} avg_rank={avg_rank:.2f}"
            ),
            f"Hands: seen={self.hands_seen} won={self.hands_won} win={hand_win_rate}",
            f"Actions: {action_text}",
            f"Active rooms: {rooms}",
        ]

    def _draw_fixed(self, lines: list[str]) -> None:
        self.output.write("\x1b[H\x1b[2J")
        self.output.write("\n".join(lines))
        self.output.write("\n")
        self.output.flush()


def _room_id(msg: dict[str, object]) -> int:
    return cast(int, msg.get("room_id", 0))


def _percent(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{numerator / denominator:.1%}"
