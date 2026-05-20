"""HybridBot — Phase A (중랩이/GtoBot) + Phase B (Wooz/ExploitativeLAG) switcher.

active 인원 ≤ 3 또는 누군가 effective_bb ≤ 6이면 Phase B (Wooz brain).
그 외엔 Phase A (Gto brain).

두 brain의 state는 모든 WS 이벤트에서 동시에 갱신된다 — 휴면 brain이
phase 전환 시점에 "장님" 상태가 되지 않도록.

CLI:
    python bots/hybrid_bot.py <SERVER> <TOKEN> <NAME> [--reset]
"""
import argparse
import asyncio
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor", "pokerbot")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

from lib.bot_base import BotBase  # noqa: E402
from lib import strategy_variant as sv  # noqa: E402
from lib.opponent_tracker import OpponentTracker  # noqa: E402

from bots.gto import GtoBot  # noqa: E402
from bots.wooz_bot import WoozBot, _to_action_request  # noqa: E402

# vendored
from profiler import Profiler  # noqa: E402
from game_state import GameStateManager  # noqa: E402
from hot_config import HotConfig  # noqa: E402
from models import (  # noqa: E402
    GameStartRequest, HandResultRequest, Winner, ShowdownPlayer,
)


# ── Module helpers ──

def count_active_players(msg: dict) -> int:
    """살아있는 플레이어 수 — status active/allin AND stack > 0."""
    return sum(
        1 for p in msg.get("players", [])
        if p.get("status", "active") in ("active", "allin")
        and p.get("stack", 0) > 0
    )


def should_use_phase_b(msg: dict, seat_threshold: int = 3, shorty_bb: float = 6.0) -> bool:
    """Phase B (HU/3-handed brain) 트리거 조건.

    True if active <= seat_threshold OR min(eff_bb of actives) <= shorty_bb.
    4-handed에 한 명이 5bb 숏스택이면 테이블 다이내믹스가 HU에 가까움 → Phase B.
    """
    actives = [
        p for p in msg.get("players", [])
        if p.get("status", "active") in ("active", "allin")
        and p.get("stack", 0) > 0
    ]
    if len(actives) <= seat_threshold:
        return True
    blind = msg.get("blind", [1, 2])
    bb = blind[1] if len(blind) > 1 else 2
    if bb <= 0:
        return False
    min_eff_bb = min(p.get("stack", 0) / bb for p in actives)
    return min_eff_bb <= shorty_bb


# ── Logger no-op (embedded brains'd otherwise write triplicate logs) ──

class _NullLogger:
    def record(self, *a, **k): pass
    def record_my_action(self, *a, **k): pass
    def finalize_hand(self, *a, **k): pass
    def finalize_game(self, *a, **k): pass


# ── Embedded brains (skip BotBase.__init__ to avoid sys.argv collision) ──

class _EmbeddedGtoBot(GtoBot):
    """GtoBot 인스턴스 — BotBase.__init__ 건너뜀, parent의 bot_name 상속."""

    def __init__(self, parent: "HybridBot", reset: bool = False):
        # BotBase.__init__ + GtoBot.__init__의 super().__init__()를 모두 건너뛴다.
        # BotBase가 채웠을 필드를 직접 채움.
        self.server = ""
        self.api_token = ""
        self.bot_name = parent.bot_name
        self.logger = _NullLogger()
        # GtoBot 고유 brain state — bot_name이 이미 설정된 후 OpponentTracker 생성.
        self.tracker = OpponentTracker(reset=reset)


class _EmbeddedWoozBot(WoozBot):
    """WoozBot 인스턴스 — BotBase.__init__ 건너뜀, vendored brain state만 init."""

    def __init__(self, parent: "HybridBot"):
        # BotBase.__init__ skip
        self.server = ""
        self.api_token = ""
        self.bot_name = parent.bot_name
        self.logger = _NullLogger()
        # WoozBot brain state (mirror wooz_bot.py:67-78)
        self.profiler = Profiler()
        self.state_manager = GameStateManager()
        self.config = HotConfig(self.STRATEGY_KEY)
        self.strategy = self._build_strategy()


# ── HybridBot ──

class HybridBot(BotBase):
    """Phase A/B switcher. Phase A: GtoBot (4+ players, deep). Phase B: WoozBot (≤3 OR shorty)."""

    PHASE_B_SEAT_THRESHOLD = 3
    PHASE_B_SHORTY_BB = 6.0

    def __init__(self, reset: bool = False):
        super().__init__()  # BotBase: reads sys.argv → server/token/bot_name/logger
        self._gto = _EmbeddedGtoBot(parent=self, reset=reset)
        self._wooz = _EmbeddedWoozBot(parent=self)
        self._last_phase: str | None = None
        # Verify bot_name propagation (R-6)
        assert self._gto.bot_name == self.bot_name, "gto bot_name 전파 실패"
        assert self._wooz.bot_name == self.bot_name, "wooz bot_name 전파 실패"
        print(
            f"[{self.bot_name}] HybridBot 시작 — "
            f"phaseA=GtoBot, phaseB=WoozBot, "
            f"threshold=seats<={self.PHASE_B_SEAT_THRESHOLD} OR eff_bb<={self.PHASE_B_SHORTY_BB}"
        )

    # ── Routing ──

    def decide(self, msg):
        try:
            use_b = should_use_phase_b(
                msg, self.PHASE_B_SEAT_THRESHOLD, self.PHASE_B_SHORTY_BB
            )
            if use_b:
                self._last_phase = "B"
                return self._wooz.decide(msg)
            self._last_phase = "A"
            return self._gto.decide(msg)
        except Exception as e:
            print(f"[{self.bot_name}] hybrid decide 실패 → safe fold/check: {e}")
            traceback.print_exc()
            to_call = msg.get("to_call", 0)
            return ("check", 0) if to_call == 0 else ("fold", 0)

    # ── Passive observers ──

    def _wooz_observe_action_only(self, msg):
        """Phase A 동안 wooz state만 갱신 (decide 안 부름).

        WoozBot.decide의 state mutation만 미러 — strategy.decide는 호출 X.
        Phase A에서 이걸 안 부르면 Phase B 진입 시 wooz가 4+ 핸드의 행동을
        보지 못한 상태가 된다.
        """
        try:
            req = _to_action_request(msg)
            self._wooz.state_manager.update(req)
            self._wooz.profiler.update_from_action(req)
        except Exception as e:
            print(f"[{self.bot_name}] wooz_observe_action_only 실패: {e}")

    # ── Sync helper (shared between live _event_loop and arena harness) ──

    def apply_state(self, msg: dict) -> str | None:
        """모든 WS msg에 대해 두 brain의 state 갱신 + diagnostic 출력.

        Returns: action_request의 경우 "A"|"B" (active phase), 그 외 None.
        action_request에서 결정된 phase는 후속 decide() 호출과 일치해야 한다.

        Live _event_loop와 arena_multi가 공유하는 단일 코드 경로 — 두 환경에서
        state lifecycle이 동일하다는 보장을 강제.
        """
        mt = msg.get("type", "")
        room = str(msg.get("room_id", ""))

        phase_for_event: str | None = None
        if mt == "action_request":
            phase_for_event = "B" if should_use_phase_b(
                msg, self.PHASE_B_SEAT_THRESHOLD, self.PHASE_B_SHORTY_BB
            ) else "A"

        # ── State updates: 두 brain 모두 갱신 ──
        if mt == "game_start":
            sv.reset_room(room)
            variant = sv.get_for_room(room)
            msg["_variant"] = variant.name
            self._gto.tracker.observe(msg)
            player_names = [p["name"] for p in msg.get("players", [])]
            gs_req = GameStartRequest(
                game_id=room,
                players=player_names,
                starting_stack=msg.get("starting_stack", 300),
                blind_structure=msg.get("blind_structure", []),
            )
            self._wooz.state_manager.new_game(gs_req)
            self._wooz.profiler.init_game(room, player_names)
            print(
                f"[{self.bot_name}] R{room} 시작 variant={variant.name} "
                f"players={player_names}"
            )

        elif mt == "action_request":
            self._gto.tracker.observe(msg)
            if phase_for_event == "A":
                self._wooz_observe_action_only(msg)

        elif mt == "hand_result":
            self._gto.tracker.observe(msg)
            try:
                hr_req = HandResultRequest(
                    game_id=room,
                    hand_number=msg.get("hand_number", 0),
                    winners=[Winner(**w) for w in msg.get("winners", [])],
                    showdown=[ShowdownPlayer(**s) for s in msg.get("showdown", [])],
                    community_cards=msg.get("community_cards", []),
                    pot=msg.get("pot", 0),
                )
                self._wooz.state_manager.record_result(hr_req)
                game_state = self._wooz.state_manager.get(room)
                action_history = game_state.last_action_history if game_state else []
                showdown_names = [s.name for s in hr_req.showdown]
                big_blind = (
                    game_state.current_blind[1]
                    if game_state and len(game_state.current_blind) >= 2 else 2
                )
                self._wooz.profiler.update_hand_end(
                    room, action_history, showdown_names,
                    big_blind=big_blind, final_pot=hr_req.pot,
                )
            except Exception as e:
                print(f"[{self.bot_name}] wooz hand_result update 실패: {e}")

        elif mt == "game_end":
            self._gto.tracker.observe(msg)
            try:
                rankings = msg.get("rankings", [])
                my_rank = next(
                    (r["rank"] for r in rankings if r.get("name") == self.bot_name),
                    99,
                )
                self._wooz.profiler.record_game_result(room, my_rank, len(rankings))
                self._wooz.state_manager.remove_game(room)
                self._wooz.profiler.remove_game(room)
            except Exception as e:
                print(f"[{self.bot_name}] wooz game_end update 실패: {e}")

        elif mt not in ("ping",):
            self._gto.tracker.observe(msg)

        # ── Hybrid logger (parent only) ──
        self.logger.record(msg)

        # ── R-1 diagnostic ──
        if mt != "ping":
            gto_n = len(self._gto.tracker.players)
            wooz_n = len(self._wooz.profiler._stats)
            consistent = abs(gto_n - wooz_n) <= 2
            active_brain = phase_for_event if phase_for_event else (self._last_phase or "-")
            print(
                f"[{self.bot_name}] event={mt} active_brain={active_brain} "
                f"hand_count gto={gto_n} wooz={wooz_n} "
                f"dual_state_consistent={consistent}"
            )

        return phase_for_event

    # ── Async event loop (live WS) ──

    async def _event_loop(self, ws):
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            mt = msg.get("type", "")
            room = str(msg.get("room_id", ""))

            self.apply_state(msg)

            # ── Dispatch (mirror BotBase._event_loop + gto/wooz 추가 처리) ──
            if mt == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif mt == "action_request":
                asyncio.create_task(self._handle_action(ws, msg))
            elif mt == "hand_result":
                self.logger.finalize_hand(room)
            elif mt == "game_end":
                self.logger.finalize_game(msg)
                sv.reset_room(room)
                print(f"[{self.bot_name}] R{room} 종료")
            elif mt == "server_shutdown":
                print(f"[{self.bot_name}] 서버 종료 신호 수신")
                sys.exit(0)
            elif mt == "error":
                print(f"[{self.bot_name}] 에러: {msg.get('message')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--reset", action="store_true",
                        help="대회 시작시 누적 트래커 초기화")
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + remaining
    HybridBot(reset=args.reset).run()
