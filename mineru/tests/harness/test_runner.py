# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any
from unittest.mock import AsyncMock

from holdem_agent.client.connection import PokerConnection
from holdem_agent.harness.runner import HarnessRunner
from holdem_agent.strategy.base import Action, DecisionContext, Strategy, safe_fallback
from holdem_agent.strategy.genome import StrategyGenome


SAMPLE_GAME_START = {
    "type": "game_start",
    "room_id": 1,
    "starting_stack": 300,
    "blind_structure": [
        {"level": 1, "small": 1, "big": 2, "hands": 0},
        {"level": 2, "small": 2, "big": 4, "hands": 10},
    ],
    "players": [
        {"name": "bot-A", "type": "bot", "stack": 300},
        {"name": "bot-B", "type": "bot", "stack": 300},
    ],
}

SAMPLE_HAND_START = {
    "type": "hand_start",
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "your_stack": 298,
    "your_seat": "btn",
    "blind": [1, 2],
    "players": [
        {"name": "bot-A", "stack": 298, "position": "btn", "status": "active", "action": None, "bet": 0},
        {"name": "bot-B", "stack": 297, "position": "sb", "status": "active", "action": None, "bet": 1},
    ],
}

SAMPLE_ACTION_REQUEST = {
    "type": "action_request",
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "community_cards": ["2s", "7d", "Kc"],
    "phase": "flop",
    "pot": 12,
    "my_stack": 294,
    "to_call": 4,
    "min_raise": 8,
    "blind": [1, 2],
    "seat": "btn",
    "players": [],
    "action_history": [],
    "timeout_ms": 30000,
}

SAMPLE_GAME_END = {
    "type": "game_end",
    "room_id": 1,
    "rankings": [
        {"rank": 2, "name": "bot-A", "chips": 150},
        {"rank": 1, "name": "bot-B", "chips": 450},
    ],
}


class MockStrategy(Strategy):
    def __init__(self, action: Action | None = None, should_fail: bool = False) -> None:
        self._action = action or Action(action="call")
        self._should_fail = should_fail
        self.last_context: DecisionContext | None = None

    def decide(self, context: DecisionContext) -> Action:
        self.last_context = context
        if self._should_fail:
            raise RuntimeError("Strategy failed")
        return self._action

    @property
    def genome(self) -> StrategyGenome:
        return StrategyGenome()

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> "MockStrategy":
        return cls()

    @property
    def name(self) -> str:
        return "mock"


def _runner(strategy: Strategy | None = None) -> HarnessRunner:
    return HarnessRunner(strategy or MockStrategy())


def _mock_conn() -> AsyncMock:
    conn = AsyncMock(spec=PokerConnection)
    conn.send_action = AsyncMock()
    return conn


def test_handle_game_start(caplog: Any) -> None:
    runner = _runner()
    conn = _mock_conn()

    with caplog.at_level(logging.INFO):
        asyncio.run(runner._handle(conn, SAMPLE_GAME_START))

    game = runner._tracker.get_or_create(1)
    assert game.starting_stack == 300
    assert "Game started: room_id=1" in caplog.text


def test_handle_action_request() -> None:
    strategy = MockStrategy(action=Action(action="raise", amount=8))
    runner = _runner(strategy)
    conn = _mock_conn()

    asyncio.run(runner._handle(conn, SAMPLE_GAME_START))
    asyncio.run(runner._handle(conn, SAMPLE_HAND_START))
    asyncio.run(runner._handle(conn, SAMPLE_ACTION_REQUEST))

    assert strategy.last_context is not None
    assert strategy.last_context.phase == "flop"
    conn.send_action.assert_awaited_once_with(1, "raise", 8)


def test_handle_hand_start_without_private_fields_is_ignored(caplog: Any) -> None:
    runner = _runner()
    conn = _mock_conn()
    msg = {
        "type": "hand_start",
        "room_id": 1,
        "hand_number": 2,
        "your_cards": [],
        "your_stack": None,
        "your_seat": None,
        "blind": [1, 2],
        "players": SAMPLE_HAND_START["players"],
    }

    asyncio.run(runner._handle(conn, SAMPLE_GAME_START))

    with caplog.at_level(logging.DEBUG):
        asyncio.run(runner._handle(conn, msg))

    assert runner._tracker.get_or_create(1).hand.hand_number == 0
    assert "Skipping hand_start without private bot fields" in caplog.text


def test_handle_action_request_timeout(monkeypatch: Any) -> None:
    runner = _runner(MockStrategy(action=Action(action="raise", amount=12)))
    conn = _mock_conn()

    async def fake_wait_for(awaitable: Awaitable[Action], timeout: float) -> Action:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("holdem_agent.harness.runner.asyncio.wait_for", fake_wait_for)

    asyncio.run(runner._handle(conn, SAMPLE_GAME_START))
    asyncio.run(runner._handle(conn, SAMPLE_HAND_START))
    asyncio.run(runner._handle(conn, SAMPLE_ACTION_REQUEST))

    conn.send_action.assert_awaited_once_with(1, "fold", None)


def test_handle_action_request_error() -> None:
    runner = _runner(MockStrategy(should_fail=True))
    conn = _mock_conn()

    asyncio.run(runner._handle(conn, SAMPLE_GAME_START))
    asyncio.run(runner._handle(conn, SAMPLE_HAND_START))
    asyncio.run(runner._handle(conn, SAMPLE_ACTION_REQUEST))

    conn.send_action.assert_awaited_once_with(1, "fold", None)


def test_handle_game_end(caplog: Any) -> None:
    runner = _runner()
    runner._bot_name = "bot-A"
    conn = _mock_conn()

    asyncio.run(runner._handle(conn, SAMPLE_GAME_START))

    with caplog.at_level(logging.INFO):
        asyncio.run(runner._handle(conn, SAMPLE_GAME_END))

    assert runner._tracker.active_games == []
    assert runner._tracker._games == {}
    assert "Game ended: room_id=1 bot=bot-A rank=2" in caplog.text


def _sample_context() -> DecisionContext:
    runner = _runner()
    runner._tracker.handle_game_start(SAMPLE_GAME_START)
    runner._tracker.handle_hand_start(SAMPLE_HAND_START)
    return runner._tracker.handle_action_request(SAMPLE_ACTION_REQUEST)


def test_safe_decide_normal() -> None:
    expected = Action(action="call")
    runner = _runner(MockStrategy(action=expected))

    assert asyncio.run(runner._safe_decide(_sample_context())) == expected


def test_safe_decide_timeout(monkeypatch: Any) -> None:
    runner = _runner(MockStrategy(action=Action(action="raise", amount=10)))
    context = _sample_context()

    async def fake_wait_for(awaitable: Awaitable[Action], timeout: float) -> Action:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("holdem_agent.harness.runner.asyncio.wait_for", fake_wait_for)

    assert asyncio.run(runner._safe_decide(context)) == safe_fallback(context)


def test_safe_decide_exception() -> None:
    runner = _runner(MockStrategy(should_fail=True))
    context = _sample_context()

    assert asyncio.run(runner._safe_decide(context)) == safe_fallback(context)
