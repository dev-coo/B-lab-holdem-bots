import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from holdem_agent.client.connection import PokerConnection
from holdem_agent.engine.game import GameTracker
from holdem_agent.harness.live_hud import LiveHud
from holdem_agent.strategy.base import Action, DecisionContext, Strategy, safe_fallback

logger = logging.getLogger(__name__)


class HarnessRunner:
    """Runs a strategy against a poker server."""

    def __init__(
        self,
        strategy: Strategy,
        hud: LiveHud | None = None,
        *,
        max_games: int | None = None,
        record_path: str | Path | None = None,
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        self._strategy = strategy
        self._tracker = GameTracker()
        self._hud = hud
        self._bot_name = ""
        self._max_games = max_games
        self._games_finished = 0
        self._record_path = Path(record_path) if record_path is not None else None
        self._reconnect_initial_delay = reconnect_initial_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._stop_requested = False

    async def run(self, server_url: str, token: str, bot_name: str) -> None:
        """Main event loop. Connect, authenticate, reconnect on drops, and play."""
        self._bot_name = bot_name
        self._stop_requested = False
        reconnect_delay = self._reconnect_initial_delay

        while not self._stop_requested:
            try:
                async with PokerConnection(server_url) as conn:
                    await conn.authenticate(token, bot_name)
                    logger.info("Authenticated as %s", bot_name)
                    reconnect_delay = self._reconnect_initial_delay

                    async for msg in conn.listen():
                        should_continue = await self._handle(conn, msg)
                        if not should_continue:
                            logger.info(
                                "Max games reached: bot=%s finished=%d limit=%d",
                                bot_name,
                                self._games_finished,
                                self._max_games or 0,
                            )
                            self._stop_requested = True
                            break
                    else:
                        return
            except ConnectionError as exc:
                if _is_auth_error(exc):
                    raise
                if self._stop_requested:
                    return
                reconnect_delay = await self._sleep_before_reconnect(
                    bot_name,
                    exc,
                    reconnect_delay,
                )
            except Exception as exc:
                if self._stop_requested:
                    return
                reconnect_delay = await self._sleep_before_reconnect(
                    bot_name,
                    exc,
                    reconnect_delay,
                )

    async def _sleep_before_reconnect(
        self,
        bot_name: str,
        exc: Exception,
        reconnect_delay: float,
    ) -> float:
        logger.warning(
            "Connection lost for bot=%s: %s. Reconnecting in %.1fs",
            bot_name,
            exc,
            reconnect_delay,
        )
        await asyncio.sleep(reconnect_delay)
        return min(reconnect_delay * 2, self._reconnect_max_delay)

    async def _handle(self, conn: PokerConnection, msg: dict[str, object]) -> bool:
        """Route server events to appropriate handlers.

        All message handling is wrapped in per-event try/except so a
        single malformed server payload never kills the main loop.
        """
        self._record("event", msg)
        msg_type = str(msg.get("type", ""))

        if msg_type == "game_start":
            self._tracker.handle_game_start(msg)
            room_id = cast(int, msg.get("room_id", 0))
            logger.info("Game started: room_id=%d", room_id)
            if self._hud is not None:
                self._hud.game_started(msg)
            return True

        if msg_type == "hand_start":
            if not _has_private_hand_start_fields(msg):
                logger.debug(
                    "Skipping hand_start without private bot fields: room_id=%s hand=%s",
                    msg.get("room_id"),
                    msg.get("hand_number"),
                )
                return True
            self._tracker.handle_hand_start(msg)
            if self._hud is not None:
                self._hud.hand_started(msg)
            return True

        if msg_type == "action_request":
            context = self._tracker.handle_action_request(msg)
            action = await self._safe_decide(context)
            room_id = cast(int, msg["room_id"])
            await conn.send_action(room_id, action.action, action.amount)
            self._record(
                "action_sent",
                {
                    "room_id": room_id,
                    "action": action.action,
                    "amount": action.amount,
                    "reasoning": action.reasoning,
                    "strategy_name": action.strategy_name or self._strategy.name,
                },
            )
            logger.debug("Action: %s amount=%s room=%d", action.action, action.amount, room_id)
            if self._hud is not None:
                self._hud.action_sent(room_id, action.action, action.amount)
            return True

        if msg_type == "phase_change":
            self._tracker.handle_phase_change(msg)
            return True

        if msg_type == "action_performed":
            return True

        if msg_type == "hand_result":
            self._tracker.handle_hand_result(msg)
            if self._hud is not None:
                self._hud.hand_finished(msg)
            return True

        if msg_type == "game_end":
            self._tracker.handle_game_end(msg)
            room_id = cast(int, msg.get("room_id", 0))
            rank = self._rank_for_bot(msg)
            logger.info("Game ended: room_id=%d bot=%s rank=%s", room_id, self._bot_name, rank)
            if self._hud is not None:
                self._hud.game_finished(msg)
            self._games_finished += 1
            self._tracker.remove_game(room_id)
            return self._max_games is None or self._games_finished < self._max_games

        if msg_type == "waiting_room":
            logger.info(
                "Waiting room: room_id=%s players=%s/%s starts_in=%s",
                msg.get("room_id"),
                msg.get("current_players"),
                msg.get("min_players"),
                msg.get("starts_in"),
            )
            return True

        if msg_type == "error":
            logger.error("Server error: %s", msg.get("message", ""))
            return True

        if msg_type in {"player_joined", "player_left"}:
            return True

        return True

    def _record(self, kind: str, payload: dict[str, object]) -> None:
        if self._record_path is None:
            return
        self._record_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "bot_name": self._bot_name,
            "strategy_name": self._strategy.name,
            "payload": payload,
        }
        with self._record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def _rank_for_bot(self, msg: dict[str, object]) -> int | None:
        rankings = cast(list[dict[str, object]], msg.get("rankings", []))
        for ranking in rankings:
            if ranking.get("name") == self._bot_name and isinstance(ranking.get("rank"), int):
                return cast(int, ranking["rank"])
        return None

    async def _safe_decide(self, context: DecisionContext) -> Action:
        """Execute strategy with 28s soft response timeout.

        Note: asyncio.wait_for cancels the *await* but the underlying
        thread (via to_thread) may continue running.  This is acceptable
        because the thread holds no shared mutable state — it just
        computes a return value that gets discarded.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._strategy.decide, context),
                timeout=28.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Strategy timeout — using safe fallback")
            return safe_fallback(context)
        except Exception:
            logger.exception("Strategy error — using safe fallback")
            return safe_fallback(context)


def _has_private_hand_start_fields(msg: dict[str, object]) -> bool:
    return (
        isinstance(msg.get("your_cards"), list)
        and isinstance(msg.get("your_stack"), int)
        and isinstance(msg.get("your_seat"), str)
    )


def _is_auth_error(exc: ConnectionError) -> bool:
    message = str(exc)
    return message.startswith("Auth failed:") or message.startswith("Unexpected response:")
