from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest  # pyright: ignore[reportMissingImports]


AUTH_OK = {
    "type": "auth_ok",
    "player_type": "bot",
    "bot_name": "test-bot",
    "concurrent_games": 1,
}

GAME_START = {
    "type": "game_start",
    "room_id": 1,
    "players": [
        {"name": "test-bot", "type": "bot"},
        {"name": "opponent", "type": "bot"},
    ],
    "starting_stack": 300,
    "blind_structure": [
        {"level": 1, "small": 1, "big": 2, "hands": 10},
    ],
}

HAND_START = {
    "type": "hand_start",
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "your_stack": 298,
    "your_seat": "btn",
    "blind": [1, 2],
    "players": [
        {
            "name": "test-bot",
            "stack": 298,
            "position": "btn",
            "status": "active",
            "action": None,
            "bet": 0,
        },
        {
            "name": "opponent",
            "stack": 297,
            "position": "bb",
            "status": "active",
            "action": None,
            "bet": 2,
        },
    ],
}

ACTION_REQUEST_PREFLOP = {
    "type": "action_request",
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "community_cards": [],
    "phase": "preflop",
    "pot": 3,
    "my_stack": 298,
    "to_call": 2,
    "min_raise": 4,
    "blind": [1, 2],
    "seat": "btn",
    "players": [
        {
            "name": "test-bot",
            "stack": 298,
            "position": "btn",
            "status": "active",
            "action": None,
            "bet": 0,
        },
        {
            "name": "opponent",
            "stack": 297,
            "position": "bb",
            "status": "active",
            "action": None,
            "bet": 2,
        },
    ],
    "action_history": [
        {"phase": "preflop", "player": "opponent", "action": "call", "amount": 2},
    ],
    "timeout_ms": 30000,
}

PHASE_CHANGE_FLOP = {
    "type": "phase_change",
    "room_id": 1,
    "phase": "flop",
    "community_cards": ["2s", "7d", "Kc"],
}

ACTION_REQUEST_FLOP = {
    "type": "action_request",
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "community_cards": ["2s", "7d", "Kc"],
    "phase": "flop",
    "pot": 7,
    "my_stack": 296,
    "to_call": 0,
    "min_raise": 4,
    "blind": [1, 2],
    "seat": "btn",
    "players": [
        {
            "name": "test-bot",
            "stack": 296,
            "position": "btn",
            "status": "active",
            "action": None,
            "bet": 0,
        },
        {
            "name": "opponent",
            "stack": 294,
            "position": "bb",
            "status": "active",
            "action": "check",
            "bet": 0,
        },
    ],
    "action_history": [
        {"phase": "preflop", "player": "opponent", "action": "call", "amount": 2},
        {"phase": "preflop", "player": "test-bot", "action": "call", "amount": 2},
    ],
    "timeout_ms": 30000,
}

HAND_RESULT = {
    "type": "hand_result",
    "room_id": 1,
    "hand_number": 1,
    "winners": [{"name": "test-bot", "amount": 7}],
    "showdown": [
        {"name": "test-bot", "cards": ["Ah", "Kh"]},
        {"name": "opponent", "cards": ["Qd", "Js"]},
    ],
    "community_cards": ["2s", "7d", "Kc", "4h", "9d"],
    "pot": 7,
    "eliminated": [],
}

GAME_END = {
    "type": "game_end",
    "room_id": 1,
    "rankings": [
        {"rank": 1, "name": "test-bot", "chips": 600},
        {"rank": 2, "name": "opponent", "chips": 0},
    ],
}


@pytest.fixture
def harness_types() -> tuple[type[Any], type[Any], Any]:
    runner_module = pytest.importorskip("holdem_agent.harness.runner")
    strategy_module = pytest.importorskip("holdem_agent.strategy.builtins.calling_station")
    return runner_module.HarnessRunner, strategy_module.CallingStation, runner_module


@pytest.fixture
def mock_connection() -> AsyncMock:
    conn = AsyncMock()
    conn.authenticate = AsyncMock(return_value=AUTH_OK)
    conn.send_action = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


async def _fake_listen(events: list[dict[str, object]]) -> AsyncIterator[dict[str, object]]:
    for event in events:
        yield event


async def _run_runner(
    harness_types: tuple[type[Any], type[Any], Any],
    mock_connection: AsyncMock,
    events: list[dict[str, object]],
) -> Any:
    harness_runner_cls, calling_station_cls, runner_module = harness_types
    mock_connection.listen = lambda: _fake_listen(events)

    strategy = calling_station_cls()
    runner = harness_runner_cls(strategy)

    with patch.object(runner_module, "PokerConnection", return_value=mock_connection):
        await runner.run("ws://fake:5051/ws", "test-token", "test-bot")

    return runner


def test_full_game_lifecycle(
    harness_types: tuple[type[Any], type[Any], Any], mock_connection: AsyncMock
) -> None:
    runner = asyncio.run(
        _run_runner(
            harness_types,
            mock_connection,
            [
                GAME_START,
                HAND_START,
                ACTION_REQUEST_PREFLOP,
                PHASE_CHANGE_FLOP,
                ACTION_REQUEST_FLOP,
                HAND_RESULT,
                GAME_END,
            ],
        )
    )

    mock_connection.authenticate.assert_awaited_once_with("test-token", "test-bot")
    assert mock_connection.send_action.await_count == 2

    first_call = mock_connection.send_action.await_args_list[0]
    assert first_call.args[:2] == (1, "call")
    assert first_call.kwargs == {}

    second_call = mock_connection.send_action.await_args_list[1]
    assert second_call.args[:2] == (1, "check")
    assert second_call.kwargs == {}

    tracker = getattr(runner, "game_tracker", None)
    if tracker is not None:
        assert getattr(tracker, "current_room_id", 1) == 1
        assert getattr(tracker, "current_hand_number", 1) == 1


def test_bot_handles_unexpected_events(
    harness_types: tuple[type[Any], type[Any], Any], mock_connection: AsyncMock
) -> None:
    events = [
        GAME_START,
        {"type": "mystery_event", "room_id": 1, "payload": "ignored"},
        ACTION_REQUEST_PREFLOP,
        GAME_END,
    ]

    asyncio.run(_run_runner(harness_types, mock_connection, events))

    mock_connection.send_action.assert_awaited_once()
    call = mock_connection.send_action.await_args_list[0]
    assert call.args[:2] == (1, "call")


def test_bot_handles_empty_community_cards(
    harness_types: tuple[type[Any], type[Any], Any], mock_connection: AsyncMock
) -> None:
    asyncio.run(
        _run_runner(
            harness_types,
            mock_connection,
            [GAME_START, HAND_START, ACTION_REQUEST_PREFLOP, GAME_END],
        )
    )

    mock_connection.send_action.assert_awaited_once()
    call = mock_connection.send_action.await_args_list[0]
    assert call.args[:2] == (1, "call")
    if len(call.args) > 2:
        assert call.args[2] is None
