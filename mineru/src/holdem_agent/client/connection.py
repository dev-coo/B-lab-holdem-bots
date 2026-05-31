import json
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from websockets.asyncio.client import connect as ws_connect

from holdem_agent.client.auth import create_auth_message, is_auth_fail, is_auth_ok
from holdem_agent.client.protocol import encode_pong, parse_message

logger = logging.getLogger(__name__)


class _WebSocketLike(Protocol):
    async def recv(self, decode: bool | None = None) -> str: ...

    async def send(self, message: str) -> None: ...

    async def close(self) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


class _WebSocketConnectContext(Protocol):
    async def __aenter__(self) -> _WebSocketLike: ...

    async def __aexit__(self, *exc: object) -> None: ...


class PokerConnection:
    """Async WebSocket connection to poker server."""

    def __init__(self, server_url: str):
        self._url = server_url
        self._ws: _WebSocketLike | None = None
        self._connect_cm: _WebSocketConnectContext | None = None

    async def __aenter__(self) -> "PokerConnection":
        """Connect to server."""
        connect_cm = ws_connect(self._url)
        self._connect_cm = connect_cm
        self._ws = await connect_cm.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Close connection."""
        if self._connect_cm is not None:
            await self._connect_cm.__aexit__(*exc)
        elif self._ws is not None:
            await self._ws.close()
        self._ws = None
        self._connect_cm = None

    async def authenticate(self, token: str, bot_name: str) -> dict[str, object]:
        """Send auth message and wait for response. Returns auth_ok dict.

        Server may interleave a heartbeat ping while we wait for the auth
        response; reply with pong and keep reading until auth_ok / auth_fail.
        """
        websocket = self._require_ws()
        auth_msg = create_auth_message(token, bot_name)
        await self._send(json.dumps(auth_msg))
        while True:
            response = parse_message(await websocket.recv(decode=True))
            if response.get("type") == "ping":
                await self._send(encode_pong())
                continue
            if is_auth_fail(response):
                raise ConnectionError(f"Auth failed: {response.get('reason', 'unknown')}")
            if not is_auth_ok(response):
                raise ConnectionError(f"Unexpected response: {response.get('type')}")
            return response

    async def listen(self) -> AsyncIterator[dict[str, object]]:
        """Yield parsed messages from server. Handles ping/pong internally.

        Malformed frames are logged and skipped so a single bad payload does
        not tear down the connection.
        """
        websocket = self._require_ws()
        async for raw in websocket:
            text = raw if isinstance(raw, str) else raw.decode()
            try:
                msg = parse_message(text)
            except ValueError as exc:
                logger.warning("Skipping malformed frame: %s", exc)
                continue
            if msg.get("type") == "ping":
                await self._send(encode_pong())
                continue
            if msg.get("type") == "server_shutdown":
                logger.info("Server shutdown received")
                return
            yield msg

    async def send_action(self, room_id: int, action: str, amount: int | None = None) -> None:
        """Send action to server."""
        from holdem_agent.client.protocol import encode_action

        await self._send(encode_action(room_id, action, amount))

    async def _send(self, message: str) -> None:
        """Send raw string to websocket."""
        websocket = self._require_ws()
        await websocket.send(message)

    def _require_ws(self) -> _WebSocketLike:
        if self._ws is None:
            raise ConnectionError("WebSocket is not connected")
        return self._ws
