"""WsClient 통합 테스트 — 로컬 mock 서버.

검증:
  - auth_bot → auth_ok 흐름.
  - auth_fail → AuthError.
  - ping → pong 즉시 응답.
  - server_shutdown → 정상 종료.
  - unknown event → handler 는 호출되지 않지만 run 은 계속.
  - action payload 전송 형식.
  - reconnect_loop 이 AuthError 에서 재시도 안 함.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import websockets

from holdem.transport import protocol as p
from holdem.transport.ws_client import (
    AuthError,
    BotConfig,
    WsClient,
    reconnect_loop,
)


@asynccontextmanager
async def _server(handler):
    async with websockets.serve(handler, "127.0.0.1", 0) as srv:
        sock = next(iter(srv.sockets))
        port = sock.getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


def _cfg(url: str) -> BotConfig:
    return BotConfig(ws_url=url, api_token="t", bot_name="bot-x")


async def test_auth_ok_and_ping_pong():
    received: list = []
    pong_seen = asyncio.Event()

    async def server(ws):
        # 1) auth_bot 수신
        auth_raw = await ws.recv()
        auth = json.loads(auth_raw)
        assert auth["type"] == "auth_bot"
        assert auth["api_token"] == "t"
        assert auth["bot_name"] == "bot-x"
        await ws.send(json.dumps({"type": "auth_ok", "user_id": 1, "bot_name": "bot-x"}))
        # 2) ping
        await ws.send(json.dumps({"type": "ping"}))
        # 3) pong 수신 대기
        pong_raw = await ws.recv()
        if json.loads(pong_raw) == {"type": "pong"}:
            pong_seen.set()
        # 4) server_shutdown → 정상 종료
        await ws.send(json.dumps({"type": "server_shutdown", "reason": "done"}))

    async def handler(event):
        received.append(event)

    async with _server(server) as url:
        await asyncio.wait_for(WsClient(_cfg(url), handler).run(), timeout=3)

    assert pong_seen.is_set()
    assert any(isinstance(e, p.ServerShutdown) for e in received)


async def test_auth_fail_raises():
    async def server(ws):
        await ws.recv()  # auth_bot
        await ws.send(json.dumps({"type": "auth_fail", "reason": "bad token"}))

    async def handler(event):
        pass

    async with _server(server) as url:
        with pytest.raises(AuthError):
            await asyncio.wait_for(WsClient(_cfg(url), handler).run(), timeout=3)


async def test_handler_receives_action_request_and_sends_action():
    seen_action = asyncio.Event()

    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_ok"}))
        await ws.send(json.dumps({
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
            "players": [{"name": "bot-x", "stack": 298, "position": "btn"}],
            "action_history": [],
            "timeout_ms": 30000,
        }))
        response = await ws.recv()
        payload = json.loads(response)
        assert payload == {"type": "action", "room_id": 1, "action": "fold"}
        seen_action.set()
        await ws.send(json.dumps({"type": "server_shutdown"}))

    client_ref: list[WsClient] = []

    async def handler(event):
        if isinstance(event, p.ActionRequest):
            await client_ref[0].send_action(p.Action(room_id=event.room_id, action="fold"))

    async with _server(server) as url:
        client = WsClient(_cfg(url), handler)
        client_ref.append(client)
        await asyncio.wait_for(client.run(), timeout=3)

    assert seen_action.is_set()


async def test_unknown_event_does_not_crash():
    """BOT_GUIDE 스키마 밖 이벤트 → 경고 후 무시."""
    received = []

    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_ok"}))
        await ws.send(json.dumps({"type": "what_is_this"}))
        await ws.send(json.dumps({"type": "ping"}))
        await ws.recv()  # pong 소비
        await ws.send(json.dumps({"type": "server_shutdown"}))

    async def handler(event):
        received.append(event)

    async with _server(server) as url:
        await asyncio.wait_for(WsClient(_cfg(url), handler).run(), timeout=3)

    assert any(isinstance(e, p.ServerShutdown) for e in received)


async def test_reconnect_loop_exits_on_auth_failure():
    """AuthError 는 재시도 없음 (운영자 개입 필요한 상태)."""
    attempts = 0

    async def server(ws):
        nonlocal attempts
        attempts += 1
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_fail", "reason": "nope"}))

    async def handler(event):
        pass

    async with _server(server) as url:
        await asyncio.wait_for(
            reconnect_loop(_cfg(url), handler, backoff_start_s=0.01, backoff_cap_s=0.01),
            timeout=3,
        )
    assert attempts == 1
