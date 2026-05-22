import json
import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

from holdem_agent.client.connection import PokerConnection


class MockWebSocket:
    def __init__(self, messages: list[str | bytes] | None = None):
        self.recv = AsyncMock(side_effect=list(messages or []))
        self.send = AsyncMock()
        self.close = AsyncMock()
        self._messages = iter(messages or [])

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class MockConnect:
    def __init__(self, websocket: MockWebSocket):
        self.websocket = websocket
        self.enter = AsyncMock(return_value=websocket)
        self.exit = AsyncMock(return_value=None)

    async def __aenter__(self) -> MockWebSocket:
        return await self.enter()

    async def __aexit__(self, *exc: object) -> None:
        await self.exit(*exc)


def test_connection_init() -> None:
    connection = PokerConnection("ws://example.test/socket")

    assert connection._url == "ws://example.test/socket"
    assert connection._ws is None


def test_context_manager_connects_and_closes() -> None:
    websocket = MockWebSocket()
    connect_cm = MockConnect(websocket)

    async def run() -> None:
        with patch("holdem_agent.client.connection.ws_connect", return_value=connect_cm):
            async with PokerConnection("ws://example.test/socket") as connection:
                assert connection._ws is websocket

    asyncio.run(run())

    connect_cm.enter.assert_awaited_once()
    connect_cm.exit.assert_awaited_once()


def test_authenticate_success() -> None:
    websocket = MockWebSocket(
        messages=[
            json.dumps(
                {
                    "type": "auth_ok",
                    "player_type": "bot",
                    "bot_name": "bot-1",
                    "concurrent_games": 2,
                }
            )
        ]
    )
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    response = asyncio.run(connection.authenticate("token-123", "bot-1"))

    websocket.send.assert_awaited_once_with(
        json.dumps({"type": "auth_bot", "api_token": "token-123", "bot_name": "bot-1"})
    )
    assert response["type"] == "auth_ok"


def test_authenticate_failure() -> None:
    websocket = MockWebSocket(messages=[json.dumps({"type": "auth_fail", "reason": "bad token"})])
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    try:
        asyncio.run(connection.authenticate("token-123", "bot-1"))
    except ConnectionError as exc:
        assert str(exc) == "Auth failed: bad token"
    else:
        raise AssertionError("ConnectionError not raised")


def test_authenticate_rejects_unexpected_response() -> None:
    websocket = MockWebSocket(messages=[json.dumps({"type": "error", "message": "x"})])
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    try:
        asyncio.run(connection.authenticate("token-123", "bot-1"))
    except ConnectionError as exc:
        assert str(exc) == "Unexpected response: error"
    else:
        raise AssertionError("ConnectionError not raised")


def test_authenticate_replies_to_ping_then_completes() -> None:
    websocket = MockWebSocket(
        messages=[
            json.dumps({"type": "ping"}),
            json.dumps(
                {
                    "type": "auth_ok",
                    "player_type": "bot",
                    "bot_name": "bot-1",
                    "concurrent_games": 1,
                }
            ),
        ]
    )
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    response = asyncio.run(connection.authenticate("token-123", "bot-1"))

    sends = [call.args[0] for call in websocket.send.await_args_list]
    assert sends[0] == json.dumps(
        {"type": "auth_bot", "api_token": "token-123", "bot_name": "bot-1"}
    )
    assert sends[1] == json.dumps({"type": "pong"})
    assert response["type"] == "auth_ok"


def test_listen_replies_to_ping_and_yields_events() -> None:
    websocket = MockWebSocket(
        messages=[
            json.dumps({"type": "ping"}),
            json.dumps(
                {
                    "type": "auth_ok",
                    "player_type": "bot",
                    "bot_name": "bot-1",
                    "concurrent_games": 2,
                }
            ),
        ]
    )
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    async def collect() -> list[dict[str, object]]:
        return [message async for message in connection.listen()]

    events = asyncio.run(collect())

    websocket.send.assert_awaited_once_with(json.dumps({"type": "pong"}))
    assert events == [
        {
            "type": "auth_ok",
            "player_type": "bot",
            "bot_name": "bot-1",
            "concurrent_games": 2,
        }
    ]


def test_listen_stops_on_server_shutdown() -> None:
    websocket = MockWebSocket(messages=[json.dumps({"type": "server_shutdown"})])
    connection = PokerConnection("ws://example.test/socket")
    connection._ws = websocket

    async def collect() -> list[dict[str, object]]:
        return [message async for message in connection.listen()]

    events = asyncio.run(collect())

    assert events == []
    websocket.send.assert_not_awaited()
