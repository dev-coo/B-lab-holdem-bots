"""E2E smoke — 로컬 ws mock 서버 + cli.run 한 핸드 완주."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import websockets

from holdem.cli import run
from holdem.persist.event_log import EventLogger
from holdem.transport.ws_client import BotConfig


@asynccontextmanager
async def _server(handler):
    async with websockets.serve(handler, "127.0.0.1", 0) as srv:
        sock = next(iter(srv.sockets))
        port = sock.getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


async def test_one_hand_completes_and_logs(tmp_path: Path):
    got_action = asyncio.Event()

    async def srv(ws):
        # 1) auth_bot
        auth = json.loads(await ws.recv())
        assert auth["type"] == "auth_bot"
        await ws.send(json.dumps({"type": "auth_ok", "bot_name": "my-bot"}))

        # 2) hand_start — M=3.3 (short stack push/fold)
        await ws.send(json.dumps({
            "type": "hand_start",
            "room_id": 1, "hand_number": 1,
            "your_cards": ["Ah", "Ad"],
            "your_stack": 10, "your_seat": "btn",
            "blind": [1, 2],
            "players": [
                {"name": "my-bot", "stack": 10, "position": "btn", "status": "active", "bet": 0},
                {"name": "bot-B", "stack": 20, "position": "bb", "status": "active", "bet": 2},
            ],
        }))

        # 3) action_request — preflop, to_call=0
        await ws.send(json.dumps({
            "type": "action_request",
            "room_id": 1, "hand_number": 1,
            "your_cards": ["Ah", "Ad"],
            "community_cards": [],
            "phase": "preflop", "pot": 3, "my_stack": 10,
            "to_call": 2, "min_raise": 4,
            "blind": [1, 2], "seat": "btn",
            "players": [
                {"name": "my-bot", "stack": 10, "position": "btn", "bet": 0},
                {"name": "bot-B", "stack": 20, "position": "bb", "bet": 2},
            ],
            "action_history": [],
            "timeout_ms": 30000,
        }))

        # 4) 봇 응답 수신
        resp_raw = await ws.recv()
        resp = json.loads(resp_raw)
        assert resp["type"] == "action"
        assert resp["action"] == "allin"   # AA at M=3.3 in push_fold → allin
        got_action.set()

        # 5) hand_result + server_shutdown
        await ws.send(json.dumps({
            "type": "hand_result", "room_id": 1, "hand_number": 1,
            "winners": [{"name": "my-bot", "amount": 20}],
            "showdown": [{"name": "my-bot", "cards": ["Ah", "Ad"]}],
            "community_cards": ["2s", "7d", "Kc", "4h", "9d"],
            "pot": 20, "eliminated": [],
        }))
        await ws.send(json.dumps({"type": "server_shutdown", "reason": "test done"}))

    async with _server(srv) as url:
        config = BotConfig(ws_url=url, api_token="t", bot_name="my-bot")
        await asyncio.wait_for(
            run(config, log_dir=tmp_path, once=True),
            timeout=5,
        )

    assert got_action.is_set()
    # 로그 파일 하나 이상 생성됐는지 (auth_ok → room0, 게임 이벤트 → room1)
    files = list(tmp_path.glob("*.jsonl"))
    assert files, f"no log files in {tmp_path}"
    all_types: list[str] = []
    for f in files:
        for line in f.read_text().splitlines():
            all_types.append(json.loads(line)["type"])
    assert "auth_ok" in all_types
    assert "action_request" in all_types
    assert "action" in all_types
    assert "hand_result" in all_types


async def test_event_logger_multi_room(tmp_path: Path):
    with EventLogger(base_dir=tmp_path) as logger:
        from holdem.transport import protocol as p

        logger.log_in(p.AuthOk(type="auth_ok", bot_name="x"))
        logger.log_in(p.PhaseChange(
            type="phase_change", room_id=1, phase="flop",
            community_cards=["Ah", "2d", "3c"],
        ))
        logger.log_in(p.PhaseChange(
            type="phase_change", room_id=2, phase="turn",
            community_cards=["Ah", "2d", "3c", "4h"],
        ))
        logger.log_out(p.Action(room_id=1, action="fold"))

    files = sorted(tmp_path.glob("*.jsonl"))
    rooms = {f.stem.split("_room")[-1] for f in files}
    assert "0" in rooms      # auth_ok 는 room_id=0
    assert "1" in rooms
    assert "2" in rooms
