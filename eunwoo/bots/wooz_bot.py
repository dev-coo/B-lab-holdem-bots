"""WoozBot — pokerbot의 ExploitativeLAG 두뇌를 우리 BotBase로 운영.

vendor/pokerbot/strategy.ExploitativeLAG (1189줄짜리 wooz 전략)을 그대로 사용.
우리 BotBase의 인증/재접속/로깅 + msg dict ↔ Pydantic ActionRequest 어댑터.

CLI:
    python bots/wooz_bot.py <SERVER> <TOKEN> <NAME>
"""
import asyncio
import json
import os
import sys

# 우리 코드보다 먼저 vendor/pokerbot 을 import path에 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor", "pokerbot")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

from lib.bot_base import BotBase  # noqa: E402

# vendored — strategy.py가 hand_eval/equity/preflop_equity 같은 simple 이름들을 import 하므로 vendor 우선
from strategy import ExploitativeLAG  # noqa: E402
from profiler import Profiler  # noqa: E402
from game_state import GameStateManager  # noqa: E402
from hot_config import HotConfig  # noqa: E402
from models import (  # noqa: E402
    ActionRequest, ActionResponse, PlayerInfo, ActionRecord,
    HandResultRequest, GameStartRequest, Winner, ShowdownPlayer,
)


def _to_action_request(msg: dict) -> ActionRequest:
    """우리 dict msg → pokerbot ActionRequest"""
    room = str(msg.get("room_id", ""))
    players = [PlayerInfo(**p) for p in msg.get("players", [])]
    history = [ActionRecord(**a) for a in msg.get("action_history", [])]
    seat = msg.get("seat", "")
    my_bet = 0
    for p in players:
        if p.position == seat:
            my_bet = p.bet
            break
    return ActionRequest(
        game_id=room,
        hand_number=msg.get("hand_number", 0),
        pocket_cards=msg.get("your_cards", []),
        community_cards=msg.get("community_cards", []),
        phase=msg.get("phase", "preflop"),
        pot=msg.get("pot", 0),
        blind=msg.get("blind", [1, 2]),
        my_stack=msg.get("my_stack", 0),
        investment=my_bet,
        to_call=msg.get("to_call", 0),
        min_raise=msg.get("min_raise", 0),
        seat=seat,
        players=players,
        action_history=history,
    )


class WoozBot(BotBase):
    """ExploitativeLAG (wooz) 두뇌 흡수 봇."""

    STRATEGY_KEY = "wooz"  # hot_config 섹션 이름

    def __init__(self):
        super().__init__()
        self.profiler = Profiler()
        self.state_manager = GameStateManager()
        # HotConfig는 vendor/pokerbot/strategy_config.json 을 보고 그쪽 cwd 가정
        # vendor dir 안에 위치해서 그대로 작동
        self.config = HotConfig(self.STRATEGY_KEY)
        self.strategy = self._build_strategy()
        print(f"[{self.bot_name}] 전략 = {type(self.strategy).__name__} (pokerbot 흡수)")

    def _build_strategy(self):
        return ExploitativeLAG(self.profiler, self.config)

    def decide(self, msg):
        try:
            req = _to_action_request(msg)
            self.state_manager.update(req)
            self.profiler.update_from_action(req)
            resp: ActionResponse = self.strategy.decide(
                req, self.state_manager.get(req.game_id)
            )
            return resp.action, (resp.amount if resp.amount is not None else 0)
        except Exception as e:
            print(f"[{self.bot_name}] decide 에러: {e}")
            import traceback
            traceback.print_exc()
            to_call = msg.get("to_call", 0)
            return ("check", 0) if to_call == 0 else ("fold", 0)

    async def _event_loop(self, ws):
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            mt = msg.get("type", "")

            self.logger.record(msg)

            # vendored game state / profiler 갱신
            if mt == "game_start":
                room = str(msg.get("room_id", ""))
                player_names = [p["name"] for p in msg.get("players", [])]
                gs_req = GameStartRequest(
                    game_id=room,
                    players=player_names,
                    starting_stack=msg.get("starting_stack", 300),
                    blind_structure=msg.get("blind_structure", []),
                )
                self.state_manager.new_game(gs_req)
                self.profiler.init_game(room, player_names)
                print(f"[{self.bot_name}] R{msg.get('room_id')} 시작 — {player_names}")

            elif mt == "hand_result":
                room = str(msg.get("room_id", ""))
                hr_req = HandResultRequest(
                    game_id=room,
                    hand_number=msg.get("hand_number", 0),
                    winners=[Winner(**w) for w in msg.get("winners", [])],
                    showdown=[ShowdownPlayer(**s) for s in msg.get("showdown", [])],
                    community_cards=msg.get("community_cards", []),
                    pot=msg.get("pot", 0),
                )
                self.state_manager.record_result(hr_req)
                game_state = self.state_manager.get(room)
                action_history = game_state.last_action_history if game_state else []
                showdown_names = [s.name for s in hr_req.showdown]
                big_blind = (
                    game_state.current_blind[1]
                    if game_state and len(game_state.current_blind) >= 2 else 2
                )
                self.profiler.update_hand_end(
                    room, action_history, showdown_names,
                    big_blind=big_blind, final_pot=hr_req.pot,
                )

            if mt == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif mt == "action_request":
                asyncio.create_task(self._handle_action(ws, msg))
            elif mt == "hand_result":
                self.logger.finalize_hand(msg.get("room_id"))
            elif mt == "game_end":
                self.logger.finalize_game(msg)
                room = str(msg.get("room_id", ""))
                self.state_manager.remove_game(room)
                self.profiler.remove_game(room)
                rankings = msg.get("rankings", [])
                self.profiler.record_game_result(
                    room,
                    next((r["rank"] for r in rankings if r.get("name") == self.bot_name), 99),
                    len(rankings),
                )
                print(f"[{self.bot_name}] R{msg.get('room_id')} 종료")
            elif mt == "server_shutdown":
                print(f"[{self.bot_name}] 서버 종료 신호")
                sys.exit(0)
            elif mt == "error":
                print(f"[{self.bot_name}] 에러: {msg.get('message')}")


if __name__ == "__main__":
    WoozBot().run()
