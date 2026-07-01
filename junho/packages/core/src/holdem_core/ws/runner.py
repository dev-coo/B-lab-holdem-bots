"""BotRunner: 재접속 백오프를 포함한 WS 클라이언트 수명주기 관리."""

from __future__ import annotations

import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed

from pathlib import Path

from holdem_core.core.config import Settings
from holdem_core.core.logging import get_logger
from holdem_core.debug.dump import DebugDumper
from holdem_core.debug.summary import SummaryWriter
from holdem_core.strategy.base import Strategy
from holdem_core.ws.client import AuthFailed, ServerShutdown, run_once
from holdem_core.ws.state import StateStore

logger = get_logger(__name__)


class BotRunner:
    def __init__(self, settings: Settings, strategy: Strategy) -> None:
        self.settings = settings
        self.strategy = strategy
        self.state = StateStore(buffer_size=settings.ACTION_LOG_BUFFER)
        self.dumper = DebugDumper(settings.DEBUG_EVENTS, settings.DEBUG_DIR)
        self.summary_writer: SummaryWriter | None
        if settings.DEBUG_EVENTS:
            self.summary_writer = SummaryWriter(
                base_dir=Path(settings.DEBUG_DIR),
                bot_name=settings.BOT_NAME,
                store=self.dumper.store,
            )
        else:
            self.summary_writer = None
        self._stop: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_forever(), name="bot-runner")

    async def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            self._close_debug()
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=timeout)
        self._task = None
        self._close_debug()

    def _close_debug(self) -> None:
        # SummaryWriter 가 dumper.store 를 공유 사용하므로 dumper 만 close 한다.
        try:
            self.dumper.close()
        except Exception:  # noqa: BLE001
            logger.exception("dumper_close_failed")

    async def _run_forever(self) -> None:
        backoff = self.settings.RECONNECT_INITIAL_BACKOFF_S
        while not self._stop.is_set():
            try:
                await run_once(
                    self.settings.SERVER_WS_URL,
                    self.settings.BOT_API_TOKEN,
                    self.settings.BOT_NAME,
                    self.strategy,
                    self.state,
                    dumper=self.dumper,
                    summary_writer=self.summary_writer,
                )
                backoff = self.settings.RECONNECT_INITIAL_BACKOFF_S
            except ServerShutdown:
                logger.info("server_shutdown_stop")
                return
            except AuthFailed as e:
                logger.error("auth_failed", extra={"reason": str(e)})
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    raise
                backoff = self.settings.RECONNECT_INITIAL_BACKOFF_S
            except (ConnectionClosed, OSError, TimeoutError) as e:
                logger.warning(
                    "connection_error",
                    extra={"error": repr(e), "backoff_s": backoff},
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, self.settings.RECONNECT_MAX_BACKOFF_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("unexpected_error")
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                backoff = min(backoff * 2, self.settings.RECONNECT_MAX_BACKOFF_S)
