from __future__ import annotations

import dataclasses

from holdem_agent.storage.database import Database
from holdem_agent.storage.game_store import GameStore


@dataclasses.dataclass(frozen=True)
class ReplayAction:
    """A single action in a replay."""

    hand_number: int
    phase: str
    action_type: str
    amount: int | None
    reasoning: str
    pot: int
    to_call: int
    my_stack: int


@dataclasses.dataclass(frozen=True)
class ReplayHand:
    """Summary of a single hand replay."""

    hand_number: int
    result_pot: int
    result_won: int


@dataclasses.dataclass
class ReplaySummary:
    """Summary of a full game replay."""

    game_id: int
    strategy_name: str
    total_hands: int = 0
    final_rank: int | None = None
    final_chips: int | None = None
    actions: list[ReplayAction] = dataclasses.field(default_factory=list)
    hands: list[ReplayHand] = dataclasses.field(default_factory=list)

    @property
    def fold_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == "fold")

    @property
    def call_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == "call")

    @property
    def raise_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == "raise")

    @property
    def total_won(self) -> int:
        return sum(h.result_won for h in self.hands)


class GameReplayer:
    """Replay recorded games from the database."""

    def __init__(self, db: Database) -> None:
        self._store = GameStore(db)

    def replay_game(self, game_id: int) -> ReplaySummary | None:
        """Replay a full game from database records."""
        game = self._store.get_game(game_id)
        if game is None:
            return None

        summary = ReplaySummary(
            game_id=game_id,
            strategy_name=game.get("strategy_name", "unknown"),
            total_hands=game.get("total_hands", 0),
            final_rank=game.get("final_rank"),
            final_chips=game.get("final_chips"),
        )

        # Load decisions
        decisions = self._store.get_decisions(game_id)
        for d in decisions:
            summary.actions.append(
                ReplayAction(
                    hand_number=d.get("hand_number", 0),
                    phase=d.get("phase", ""),
                    action_type=d.get("action_type", ""),
                    amount=d.get("amount"),
                    reasoning=d.get("reasoning", ""),
                    pot=d.get("pot", 0),
                    to_call=d.get("to_call", 0),
                    my_stack=d.get("my_stack", 0),
                )
            )

        # Load hand results
        rows = self._store._db.execute(
            "SELECT hand_number, pot, won FROM hand_results WHERE game_id=? ORDER BY hand_number",
            (game_id,),
        ).fetchall()
        for row in rows:
            summary.hands.append(
                ReplayHand(
                    hand_number=row["hand_number"],
                    result_pot=row["pot"],
                    result_won=row["won"],
                )
            )

        return summary

    def get_action_sequence(self, game_id: int, hand_number: int) -> list[ReplayAction]:
        """Get all actions for a specific hand in a game."""
        summary = self.replay_game(game_id)
        if summary is None:
            return []
        return [a for a in summary.actions if a.hand_number == hand_number]
