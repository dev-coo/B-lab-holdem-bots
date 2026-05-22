from __future__ import annotations

import json
import logging

from holdem_agent.storage.database import Database
from holdem_agent.storage.game_store import GameStore

logger = logging.getLogger(__name__)


class GameRecorder:
    """Records all game events to the database via GameStore."""

    def __init__(self, db: Database, strategy_name: str = "unknown") -> None:
        self._store = GameStore(db)
        self._strategy_name = strategy_name
        self._current_games: dict[int, int] = {}  # room_id → game_id

    def record_game_start(self, msg: dict) -> None:
        """Record game_start event."""
        room_id = msg["room_id"]
        game_id = self._store.create_game(room_id, self._strategy_name)
        self._current_games[room_id] = game_id
        logger.debug("Recorded game start: room_id=%d game_id=%d", room_id, game_id)

    def record_action_request(self, msg: dict) -> None:
        """Record the bot's action request (what the bot saw)."""
        room_id = msg["room_id"]
        game_id = self._current_games.get(room_id)
        if game_id is None:
            return
        # Just log the request — the decision is recorded separately

    def record_decision(
        self,
        room_id: int,
        hand_number: int,
        action_type: str,
        amount: int | None,
        reasoning: str,
        phase: str,
        pot: int,
        to_call: int,
        my_stack: int,
    ) -> None:
        """Record the bot's decision."""
        game_id = self._current_games.get(room_id)
        if game_id is None:
            return
        self._store.record_decision(
            game_id=game_id,
            room_id=room_id,
            hand_number=hand_number,
            action_type=action_type,
            amount=amount,
            reasoning=reasoning,
            strategy_name=self._strategy_name,
            phase=phase,
            pot=pot,
            to_call=to_call,
            my_stack=my_stack,
        )

    def record_hand_result(self, msg: dict) -> None:
        """Record hand_result event."""
        room_id = msg["room_id"]
        game_id = self._current_games.get(room_id)
        if game_id is None:
            return
        won = 0
        for w in msg.get("winners", []):
            # Check if our bot won
            won = w.get("amount", 0)
            break
        community_cards = json.dumps(msg.get("community_cards", []))
        self._store.record_hand_result(
            game_id=game_id,
            room_id=room_id,
            hand_number=msg.get("hand_number", 0),
            pot=msg.get("pot", 0),
            won=won,
            community_cards=community_cards,
        )

    def record_game_end(self, msg: dict) -> None:
        """Record game_end event."""
        room_id = msg["room_id"]
        game_id = self._current_games.get(room_id)
        if game_id is None:
            return
        rankings = msg.get("rankings", [])
        final_rank = 0
        final_chips = 0
        if rankings:
            final_rank = rankings[0].get("rank", 0)
            final_chips = rankings[0].get("chips", 0)
        total_hands = 0  # Could count from decisions
        self._store.finish_game(game_id, final_rank, final_chips, total_hands)
        del self._current_games[room_id]
        logger.debug("Recorded game end: room_id=%d rank=%d", room_id, final_rank)

    def get_game_id(self, room_id: int) -> int | None:
        return self._current_games.get(room_id)
