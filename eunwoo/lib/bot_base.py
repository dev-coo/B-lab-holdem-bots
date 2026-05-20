"""봇 공통 프레임워크. 상속해서 decide()만 구현."""
import asyncio
import functools
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
from lib.logger import GameLogger

# stdout 버퍼링 제거 — 멀티시간 런에서 실시간 로그 확인용
print = functools.partial(print, flush=True)


class BotBase:
    def __init__(self):
        self.server = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:5051/ws"
        self.api_token = sys.argv[2] if len(sys.argv) > 2 else ""
        self.bot_name = sys.argv[3] if len(sys.argv) > 3 else "bot"
        self.logger = GameLogger(bot_name=self.bot_name)

    def decide(self, msg: dict) -> tuple[str, int]:
        """action_request → (action, amount). 서브클래스에서 구현."""
        raise NotImplementedError

    def run(self):
        asyncio.run(self._loop())

    async def _loop(self):
        while True:
            try:
                async with websockets.connect(self.server) as ws:
                    if not await self._authenticate(ws):
                        return
                    print(f"[{self.bot_name}] 인증 성공")
                    await self._event_loop(ws)
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                print(f"[{self.bot_name}] 연결 끊김, 3초 후 재접속: {e}")
                await asyncio.sleep(3)
            except Exception as e:
                # 예상 못 한 예외는 스택을 남기고 재접속. 프로세스가 죽지 않도록.
                print(f"[{self.bot_name}] 예외 발생, 5초 후 재접속: {e}")
                traceback.print_exc()
                await asyncio.sleep(5)

    async def _authenticate(self, ws) -> bool:
        await ws.send(json.dumps({
            "type": "auth_bot",
            "api_token": self.api_token,
            "bot_name": self.bot_name,
        }))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print(f"[{self.bot_name}] 인증 실패: {auth}")
            return False
        return True

    async def _event_loop(self, ws):
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            self.logger.record(msg)

            if msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif msg_type == "action_request":
                asyncio.create_task(self._handle_action(ws, msg))
            elif msg_type == "hand_result":
                self.logger.finalize_hand(msg.get("room_id"))
            elif msg_type == "game_end":
                self.logger.finalize_game(msg)
                print(f"[{self.bot_name}] Room {msg.get('room_id')} 종료")
            elif msg_type == "server_shutdown":
                print(f"[{self.bot_name}] 서버 종료 신호 수신")
                sys.exit(0)
            elif msg_type == "error":
                print(f"[{self.bot_name}] 에러: {msg.get('message')}")

    async def _handle_action(self, ws, msg):
        try:
            action, amount = await asyncio.to_thread(self.decide, msg)
            self.logger.record_my_action(msg, action, amount)
            await ws.send(json.dumps({
                "type": "action",
                "room_id": msg["room_id"],
                "action": action,
                "amount": amount,
            }))
        except Exception as e:
            print(f"[{self.bot_name}] 액션 처리 실패: {e}")
