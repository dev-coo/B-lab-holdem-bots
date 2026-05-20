"""WebSocket 클라이언트 — 인증, ping/pong, 이벤트 dispatch.

근거: `research/bot_guide_extracts.md` §2 (인증), §2.3 (20s ping / 40s timeout).
설계:
  - async context manager `connect()` 로 진입 → 자동 auth_bot.
  - `run()` 루프가 메시지를 pull → dispatcher 콜백 호출.
  - ping 은 즉시 pong 응답 (핸들러 외부 노출 없음).
  - `server_shutdown` / close → run() 이 정상 종료.
  - 재접속은 상위 `reconnect_loop()` 가 담당 (backoff).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from . import protocol as p

log = logging.getLogger(__name__)

EventHandler = Callable[[Any], Awaitable[None]]

AUTH_TIMEOUT_S = 10.0

# P-Stab: keepalive 안정화.
# 운영 로그에서 디폴트 (20s/20s) 의 `Keepalive ping timeout` 다수 발견. server 측은
# protocol Ping (20s 간격) 으로 별도 alive 확인을 하므로, 클라 측 ping 은 더 느슨하게.
# 30s 간격으로 보내고 60s 안에 pong 못 받으면 끊는다 — 네트워크 지터 흡수.
WS_PING_INTERVAL_S = 30.0
WS_PING_TIMEOUT_S = 60.0
WS_CLOSE_TIMEOUT_S = 10.0


class AuthError(RuntimeError):
    pass


@dataclass
class BotConfig:
    ws_url: str
    api_token: str
    bot_name: str


class WsClient:
    def __init__(self, config: BotConfig, handler: EventHandler):
        self.config = config
        self.handler = handler
        self._ws: WebSocketClientProtocol | None = None

    async def _auth(self, ws: WebSocketClientProtocol) -> p.AuthOk:
        await ws.send(json.dumps(p.AuthBot(
            api_token=self.config.api_token,
            bot_name=self.config.bot_name,
        ).model_dump()))
        raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_S)
        msg = p.parse_incoming(json.loads(raw))
        if isinstance(msg, p.AuthFail):
            raise AuthError(msg.reason or "auth_fail")
        if not isinstance(msg, p.AuthOk):
            raise AuthError(f"unexpected first message: {type(msg).__name__}")
        return msg

    async def send_action(self, action: p.Action) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        await self._ws.send(json.dumps(action.to_payload()))

    async def send_raw(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        await self._ws.send(json.dumps(payload))

    async def run(self) -> None:
        """단일 연결 세션. 정상 종료 시 반환, 오류는 raise."""
        async with websockets.connect(
            self.config.ws_url,
            ping_interval=WS_PING_INTERVAL_S,
            ping_timeout=WS_PING_TIMEOUT_S,
            close_timeout=WS_CLOSE_TIMEOUT_S,
        ) as ws:
            self._ws = ws
            auth = await self._auth(ws)
            log.info("auth_ok bot=%s concurrent=%s", auth.bot_name, auth.concurrent_games)
            try:
                await self.handler(auth)
            except Exception:
                log.exception("auth_ok handler error")
            try:
                await self._event_loop(ws)
            finally:
                self._ws = None

    async def _event_loop(self, ws: WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("invalid json: %r", raw[:200])
                continue
            try:
                msg = p.parse_incoming(payload)
            except Exception as e:
                log.warning("unparseable event: %s payload=%s", e, str(payload)[:200])
                continue

            if isinstance(msg, p.Ping):
                await ws.send(json.dumps(p.Pong().model_dump()))
                continue

            if isinstance(msg, p.ServerShutdown):
                log.info("server_shutdown: %s", msg.reason)
                await self.handler(msg)
                return

            try:
                await self.handler(msg)
            except Exception:
                log.exception("handler error for %s", type(msg).__name__)


async def reconnect_loop(
    config: BotConfig,
    handler: EventHandler,
    *,
    stop: asyncio.Event | None = None,
    backoff_start_s: float = 1.0,
    backoff_cap_s: float = 30.0,
) -> None:
    """지수 backoff 재접속 루프. server_shutdown 또는 AuthError 는 루프 종료."""
    delay = backoff_start_s
    while True:
        if stop is not None and stop.is_set():
            return
        client = WsClient(config, handler)
        try:
            await client.run()
            delay = backoff_start_s
        except AuthError as e:
            log.error("auth failed, stopping: %s", e)
            return
        except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
            log.warning("connection lost (%s), retrying in %.1fs", e, delay)
        else:
            # 정상 종료 (server_shutdown 등) → 루프 탈출
            return

        with contextlib.suppress(asyncio.TimeoutError):
            if stop is None:
                await asyncio.sleep(delay)
            else:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return
        delay = min(delay * 2, backoff_cap_s)
