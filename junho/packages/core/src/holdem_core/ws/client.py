"""단일 WebSocket 세션 처리 (run_once)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

import websockets
from pydantic import ValidationError

from holdem_core.core.logging import get_logger
from holdem_core.debug.dump import DebugDumper
from holdem_core.debug.summary import SummaryWriter
from holdem_core.models.actions import Action, AuthBot, Pong
from holdem_core.models.events import (
    ActionPerformed,
    ActionRequest,
    AuthFail,
    AuthOk,
    GameEnd,
    GameStart,
    HandResult,
    HandStart,
    IncomingAdapter,
    JoinedRoom,
    PhaseChange,
    Ping,
    WaitingRoom,
)
from holdem_core.models.events import (
    Error as ErrorEvt,
)
from holdem_core.models.events import (
    PlayerJoined as PlayerJoinedEvt,
)
from holdem_core.models.events import (
    PlayerLeft as PlayerLeftEvt,
)
from holdem_core.models.events import (
    ServerShutdown as ServerShutdownEvt,
)
from holdem_core.strategy.base import Strategy
from holdem_core.ws.state import ActionLog, StateStore

logger = get_logger(__name__)


class ServerShutdown(Exception):
    """서버가 server_shutdown 을 보냈음."""


class AuthFailed(Exception):
    """인증 실패."""


class _WSProto(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


class _ConnectCM(Protocol):
    async def __aenter__(self) -> _WSProto: ...
    async def __aexit__(self, *exc_info: object) -> None: ...


class ConnectFn(Protocol):
    def __call__(self, url: str, **kwargs: Any) -> _ConnectCM: ...


def _default_connect(url: str, **kwargs: Any) -> _ConnectCM:
    kwargs.setdefault("ping_interval", None)
    return websockets.connect(url, **kwargs)  # type: ignore[return-value]


async def run_once(
    url: str,
    api_token: str,
    bot_name: str,
    strategy: Strategy,
    state: StateStore,
    *,
    connect: ConnectFn = _default_connect,
    dumper: DebugDumper | None = None,
    summary_writer: SummaryWriter | None = None,
) -> None:
    """WS 에 접속하여 인증 → 루프 처리. 하나의 접속이 끊어지면 return."""
    async with connect(url) as ws:
        if dumper is not None:
            dumper.begin_run(bot_name)
        try:
            auth_payload = AuthBot(api_token=api_token, bot_name=bot_name).model_dump_json()
            if dumper is not None:
                dumper.outbound(auth_payload, "auth", None)
            await ws.send(auth_payload)
            first = await ws.recv()
            first_evt = _parse(first)
            if dumper is not None:
                dumper.inbound(first, first_evt)
            if isinstance(first_evt, AuthOk):
                state.authenticated = True
                state.connected = True
                logger.info(
                    "auth_ok",
                    extra={"bot_name": first_evt.bot_name, "user_id": first_evt.user_id},
                )
            elif isinstance(first_evt, AuthFail):
                raise AuthFailed(first_evt.reason)
            else:
                raise AuthFailed(f"unexpected first message: {type(first_evt).__name__}")

            async for raw in ws:
                evt = _parse(raw)
                if dumper is not None:
                    dumper.inbound(raw, evt)
                if evt is None:
                    continue
                await _dispatch(
                    ws,
                    evt,
                    strategy,
                    state,
                    dumper=dumper,
                    summary_writer=summary_writer,
                )
        finally:
            state.connected = False
            state.authenticated = False
            if summary_writer is not None:
                try:
                    summary_writer.flush_pending()
                except Exception:  # noqa: BLE001
                    logger.exception("summary_flush_on_close_failed")


def _parse(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("invalid_json", extra={"error": str(e)})
        return None
    try:
        return IncomingAdapter.validate_python(data)
    except ValidationError as e:
        # v5.4: silent WARN 로 인해 4723건 hand_start broadcast 가 통째로 사라졌던
        # 사고 방지 — 모델에 없는 필드/타입은 ERROR 로그 + raw 일부 동봉.
        logger.error(
            "invalid_event",
            extra={
                "error": str(e),
                "type": data.get("type") if isinstance(data, dict) else None,
                "raw_keys": list(data.keys()) if isinstance(data, dict) else None,
            },
        )
        return None


async def _dispatch(
    ws: _WSProto,
    evt: Any,
    strategy: Strategy,
    state: StateStore,
    *,
    dumper: DebugDumper | None = None,
    summary_writer: SummaryWriter | None = None,
) -> None:
    if isinstance(evt, Ping):
        pong_payload = Pong().model_dump_json()
        if dumper is not None:
            dumper.outbound(pong_payload, "pong", None)
        await ws.send(pong_payload)
        return
    if isinstance(evt, ServerShutdownEvt):
        logger.info("server_shutdown_received", extra={"reason": evt.reason})
        raise ServerShutdown(evt.reason or "server_shutdown")
    if isinstance(evt, HandStart):
        # v5.4: your_seat is None ⇒ 봇이 seat 안 된 룸의 broadcast (deploy 안 됨).
        # 5월 1일 사고: 4723건 broadcast 를 silent ValidationError 로 버리던 걸
        # 명시적으로 ERROR 로그하고 dispatch 안 함. opponent_profiles/bluff_prior 는
        # 정상 seated hand 일 때만 갱신.
        if evt.your_seat is None or not evt.your_cards:
            logger.error(
                "spectator_hand_start_received_bot_not_seated",
                extra={
                    "room_id": evt.room_id,
                    "hand_number": evt.hand_number,
                    "hint": "봇이 deploy 되지 않았거나 다른 방의 broadcast. "
                    "대시보드에서 deploy 또는 DASHBOARD_URL/BOT_ID 설정으로 auto-deploy.",
                },
            )
            return
        state.on_hand_start(evt)
        if summary_writer is not None and dumper is not None:
            summary_writer.note_run(evt.room_id, dumper.run_id)
        return
    if isinstance(evt, ActionRequest):
        state.on_action_request(evt)
        try:
            action = strategy.decide(evt)
        except Exception:
            logger.exception("strategy_error")
            action = Action(room_id=evt.room_id, action="fold")
        action_payload = action.model_dump_json(exclude_none=True)
        # 네트워크 payload 에는 meta 가 절대 포함되어선 안 됨 (Action.meta 는 exclude=True).
        # 런타임 가드로 회귀 방지.
        if '"meta"' in action_payload:
            logger.error("meta_leaked_to_network", extra={"payload": action_payload})
            raise RuntimeError("Action.meta leaked into network payload")
        if dumper is not None:
            dumper.outbound(action_payload, "action", action.room_id, meta=action.meta)
        await ws.send(action_payload)
        state.record_action(
            ActionLog(
                ts=time.time(),
                room_id=evt.room_id,
                phase=evt.phase,
                your_cards=list(evt.your_cards),
                to_call=evt.to_call,
                action=action.action,
                amount=action.amount,
            )
        )
        return
    if isinstance(evt, PhaseChange):
        state.on_phase_change(evt)
        return
    if isinstance(evt, ActionPerformed):
        state.on_action_performed(evt)
        return
    if isinstance(evt, HandResult):
        # 상태 갱신 전에 history 스냅샷 (on_hand_result 가 비울 수 있으므로 선보존).
        pre_room = state.rooms.get(evt.room_id)
        pre_history = list(pre_room.action_history) if pre_room else []
        pre_seat = pre_room.my_seat if pre_room else None
        state.on_hand_result(evt)
        # 옵셔널 hook: strategy 가 posterior 를 업데이트할 수 있도록.
        hand_result_fn = getattr(strategy, "on_hand_result", None)
        if callable(hand_result_fn):
            try:
                hand_result_fn(evt, pre_history, pre_seat)
            except Exception:  # noqa: BLE001
                logger.exception("strategy_on_hand_result_failed")
        return
    if isinstance(evt, JoinedRoom):
        state.on_joined_room(evt)
        return
    if isinstance(evt, GameEnd):
        if summary_writer is not None and dumper is not None and dumper.run_id:
            try:
                summary_writer.write(evt.room_id, dumper.run_id, list(evt.rankings))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "summary_write_failed",
                    extra={"room_id": evt.room_id, "run_id": dumper.run_id},
                )
        # v2: strategy 가 opponent_profiles.json 을 재로드 할 수 있으면 호출.
        reload_fn = getattr(strategy, "reload_profiles", None)
        if callable(reload_fn):
            try:
                reload_fn()
            except Exception:  # noqa: BLE001
                logger.exception("strategy_reload_profiles_failed")
        return
    _no_op_types = (
        GameStart,
        PlayerJoinedEvt,
        PlayerLeftEvt,
        ErrorEvt,
        AuthOk,
        AuthFail,
        WaitingRoom,
    )
    if isinstance(evt, _no_op_types):
        logger.debug("unhandled_event", extra={"type": evt.type})
        return
    logger.debug("unknown_event", extra={"type": getattr(evt, "type", None)})
