from __future__ import annotations

from datetime import datetime, timezone

from holdem_agent.storage.database import Database


class GameStore:
    """CRUD operations for game records."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create_game(self, room_id: int, strategy_name: str) -> int:
        cursor = self._db.execute(
            "INSERT INTO games (room_id, strategy_name, started_at) VALUES (?, ?, ?)",
            (room_id, strategy_name, datetime.now(timezone.utc).isoformat()),
        )
        self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def finish_game(
        self,
        game_id: int,
        final_rank: int,
        final_chips: int,
        total_hands: int,
    ) -> None:
        self._db.execute(
            "UPDATE games SET finished_at=?, final_rank=?, final_chips=?, total_hands=? WHERE id=?",
            (
                datetime.now(timezone.utc).isoformat(),
                final_rank,
                final_chips,
                total_hands,
                game_id,
            ),
        )
        self._db.commit()

    def record_decision(
        self,
        game_id: int,
        room_id: int,
        hand_number: int,
        action_type: str,
        amount: int | None,
        reasoning: str,
        strategy_name: str,
        phase: str,
        pot: int,
        to_call: int,
        my_stack: int,
    ) -> None:
        self._db.execute(
            """INSERT INTO decisions
               (game_id, room_id, hand_number, action_type, amount, reasoning,
                strategy_name, phase, pot, to_call, my_stack, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                game_id,
                room_id,
                hand_number,
                action_type,
                amount,
                reasoning,
                strategy_name,
                phase,
                pot,
                to_call,
                my_stack,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._db.commit()

    def record_hand_result(
        self,
        game_id: int,
        room_id: int,
        hand_number: int,
        pot: int,
        won: int,
        community_cards: str,
    ) -> None:
        self._db.execute(
            "INSERT INTO hand_results "
            "(game_id, room_id, hand_number, pot, won, community_cards, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                game_id,
                room_id,
                hand_number,
                pot,
                won,
                community_cards,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._db.commit()

    def get_game(self, game_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return dict(row) if row else None

    def get_decisions(self, game_id: int) -> list[dict]:
        rows = self._db.execute("SELECT * FROM decisions WHERE game_id=?", (game_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_game_count(self, strategy_name: str | None = None) -> int:
        if strategy_name:
            row = self._db.execute(
                "SELECT COUNT(*) FROM games WHERE strategy_name=?",
                (strategy_name,),
            ).fetchone()
        else:
            row = self._db.execute("SELECT COUNT(*) FROM games").fetchone()
        return row[0] if row else 0

    def get_avg_rank(self, strategy_name: str) -> float:
        row = self._db.execute(
            "SELECT AVG(final_rank) FROM games WHERE strategy_name=? AND final_rank IS NOT NULL",
            (strategy_name,),
        ).fetchone()
        return row[0] if row and row[0] is not None else 0.0
