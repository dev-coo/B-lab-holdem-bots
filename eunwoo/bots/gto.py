"""GTO 봇 — 토너먼트 강화 v2.

레이어 구성
  1. 안전망       : decide()는 try/except 게이트. _decide_v2 실패시 _decide_legacy.
  2. 효과스택 인지: my_stack/bb 계산 → Lv16+/eff_bb≤5/eff_bb≤10/일반 4분기
  3. 푸쉬폴드     : preflop_strategy.decide_pushfold() 위임 (Chen 공식 기반)
  4. ICM 압박     : 잔여인원 + 스택순위 → 마진핸드 fold 전환 / 칩리더 압박
  5. 베이스 결정  : 프리플랍 GTO 차트 + 포스트플랍 equity/팟오즈 (legacy)
  6. 변형 보정   : 방마다 랜덤 5개 프리셋이 임계/사이즈 조정
  7. 익스플로잇  : 활성 상대 archetype 기반 룰 (충분 표본일 때)

OpponentTracker는 세션 내내 살아있고 모든 WS 이벤트를 흡수.
data/session_tracker.json 에 30초마다 스냅샷 저장.
대회 시작시 봇을 `--reset`으로 띄우면 누적 데이터 초기화.

튜닝 임계값은 config/runtime.json — 60분 수정창에서 한 키씩 만짐.
"""
import argparse
import asyncio
import json
import random
import sys
import traceback

from lib.bot_base import BotBase
from lib import config
from lib.equity import equity
from lib.preflop_strategy import decide_preflop, decide_pushfold
from lib import strategy_variant as sv
from lib.opponent_tracker import OpponentTracker
from lib import exploit


def _active_opponents(players, my_name):
    count = 0
    for p in players:
        if p.get("name") == my_name:
            continue
        if p.get("status", "active") in ("active", "allin"):
            count += 1
    return max(count, 1)


def _active_seats(players):
    return [p for p in players if p.get("status", "active") in ("active", "allin")]


class GtoBot(BotBase):
    PROVIDER = "greenline"

    # Lv16 시작점: BB 1500 (TOURNAMENT.md 기준). BB ≥ 1500이면 자동올인 페이즈.
    LV16_BB_THRESHOLD = 1500

    def __init__(self, reset: bool = False):
        super().__init__()
        self.tracker = OpponentTracker(reset=reset)
        wipe = " (wipe)" if reset else ""
        print(f"[{self.bot_name}] 트래커 시작{wipe} — 부트스트랩 플레이어 {len(self.tracker.players)}명")

    # ── 진입 (안전망) ──
    def decide(self, msg):
        if not config.get("fallback_to_legacy_on_error", True):
            return self._decide_v2(msg)
        try:
            return self._decide_v2(msg)
        except Exception as e:
            print(f"[{self.bot_name}] [fallback] v2 실패 → legacy: {e}")
            traceback.print_exc()
            return self._decide_legacy(msg)

    # ── v2 분기 ──
    def _decide_v2(self, msg):
        blind = msg.get("blind", [1, 2])
        bb = blind[1] if len(blind) > 1 else 2
        my_stack = msg.get("my_stack", 0)
        eff_bb = my_stack / max(bb, 1)
        phase = msg.get("phase", "preflop")
        room_id = msg.get("room_id")

        # 프리플랍 한정 푸쉬폴드/올인 분기
        if phase == "preflop":
            if bb >= self.LV16_BB_THRESHOLD or eff_bb <= 5:
                mode = "allin"
            elif eff_bb <= 10:
                mode = "pushfold"
            else:
                mode = None

            if mode is not None:
                action, amount = decide_pushfold(msg, self.bot_name, eff_bb, mode)
                print(f"[{self.bot_name}] R{room_id} pushfold={mode} eff_bb={eff_bb:.1f}: "
                      f"{action} {amount}")
                return action, amount

        # 일반 흐름 (legacy 결정 + ICM 보정)
        action, amount = self._decide_legacy(msg)

        # ICM 압박: 마진 콜을 폴드로 전환
        icm = self._icm_pressure(msg)
        icm_thresh = float(config.get("icm_pressure_threshold", 0.6))
        to_call = msg.get("to_call", 0)

        if action == "call" and to_call > 0 and icm >= icm_thresh:
            print(f"[{self.bot_name}] R{room_id} ICM={icm:.2f} ≥ {icm_thresh} → call→fold")
            return "fold", 0

        # 칩리더 압박 — 잔여인원 따라 강도 다름. 5-6명에도 약하게 발동.
        cl_factor = self._chipleader_factor(msg)
        if action == "raise" and amount > 0 and cl_factor > 0:
            base_mult = float(config.get("chipleader_aggro_mult", 1.4))
            # 1.0 + (mult-1) * factor — factor 1.0이면 base_mult, 0.3이면 살짝
            mult = 1.0 + (base_mult - 1.0) * cl_factor
            min_raise = msg.get("min_raise", 0)
            new_amount = min(int(amount * mult), my_stack)
            new_amount = max(new_amount, min_raise)
            if new_amount != amount:
                print(f"[{self.bot_name}] R{room_id} 칩리더 압박(f={cl_factor:.1f}) {amount} → {new_amount}")
            return "raise", new_amount

        return action, amount

    # ── ICM 압박 (단일 스칼라 0.0~1.0) ──
    def _icm_pressure(self, msg) -> float:
        actives = _active_seats(msg.get("players", []))
        n_active = len(actives)
        if n_active <= 1:
            return 0.0

        my_stack = next((p.get("stack", 0) for p in actives if p.get("name") == self.bot_name), 0)
        if my_stack <= 0:
            return 0.0

        # 내 스택 순위 normalized (1위=0.0, 꼴찌=1.0)
        sorted_stacks = sorted((p.get("stack", 0) for p in actives), reverse=True)
        try:
            my_rank = sorted_stacks.index(my_stack)
        except ValueError:
            my_rank = n_active - 1
        rank_norm = my_rank / max(n_active - 1, 1)

        # 잔여인원 가중 (4명 이하 = 상금권 버블)
        if n_active <= 4:
            seat_weight, bubble_bonus = 0.7, 0.3
        elif n_active <= 6:
            seat_weight, bubble_bonus = 0.4, 0.0
        else:
            seat_weight, bubble_bonus = 0.2, 0.0

        return min(rank_norm * seat_weight + bubble_bonus, 1.0)

    def _is_chipleader_in_endgame(self, msg) -> bool:
        actives = _active_seats(msg.get("players", []))
        if len(actives) > 4 or len(actives) <= 1:
            return False
        my_stack = next((p.get("stack", 0) for p in actives if p.get("name") == self.bot_name), 0)
        max_stack = max((p.get("stack", 0) for p in actives), default=0)
        return my_stack > 0 and my_stack >= max_stack

    def _chipleader_factor(self, msg) -> float:
        """칩리더 압박 강도 (0~1). 4명 이하 1.0, 5-6명 0.6, 7+명 0.3."""
        actives = _active_seats(msg.get("players", []))
        n = len(actives)
        if n <= 1:
            return 0.0
        my_stack = next((p.get("stack", 0) for p in actives if p.get("name") == self.bot_name), 0)
        max_stack = max((p.get("stack", 0) for p in actives), default=0)
        if my_stack <= 0 or my_stack < max_stack:
            return 0.0
        # 내가 칩리더 — 잔여인원에 따라 가중
        if n <= 4:
            return 1.0
        if n <= 6:
            return 0.6
        return 0.3

    # ── legacy: 기존 v1 결정 (안전망 fallback 경로) ──
    def _decide_legacy(self, msg):
        room_id = msg.get("room_id")
        variant = sv.get_for_room(room_id)
        phase = msg.get("phase", "preflop")

        # 1) 베이스 결정
        if phase == "preflop":
            base_action, base_amount = decide_preflop(
                msg, self.bot_name, provider=self.PROVIDER, variant=variant
            )
        else:
            base_action, base_amount = self._decide_postflop(msg, variant)

        # 2) 익스플로잇 보정
        if not config.get("exploit_enabled", True):
            return base_action, base_amount

        final_action, final_amount, reason = exploit.adjust(
            base_action, base_amount, msg, self.tracker, self.bot_name
        )
        if reason != "base":
            print(f"[{self.bot_name}] R{room_id} {phase} {variant.name}: "
                  f"{base_action} {base_amount} → {final_action} {final_amount} ({reason})")
        return final_action, final_amount

    # ── WS 이벤트 훅 ──
    async def _event_loop(self, ws):
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "game_start":
                rid = msg.get("room_id")
                sv.reset_room(rid)
                variant = sv.get_for_room(rid)
                msg["_variant"] = variant.name
                print(f"[{self.bot_name}] Room {rid} → 변형 {variant.name}")

            self.logger.record(msg)
            self.tracker.observe(msg)

            if msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            elif msg_type == "action_request":
                asyncio.create_task(self._handle_action(ws, msg))
            elif msg_type == "hand_result":
                self.logger.finalize_hand(msg.get("room_id"))
            elif msg_type == "game_end":
                self.logger.finalize_game(msg)
                sv.reset_room(msg.get("room_id"))
                print(f"[{self.bot_name}] Room {msg.get('room_id')} 종료")
            elif msg_type == "server_shutdown":
                print(f"[{self.bot_name}] 서버 종료 신호 수신")
                sys.exit(0)
            elif msg_type == "error":
                print(f"[{self.bot_name}] 에러: {msg.get('message')}")

    # ── 컨텍스트 헬퍼 ──
    def _was_preflop_raiser(self, history):
        return any(
            h.get("phase") == "preflop"
            and h.get("player") == self.bot_name
            and h.get("action") in ("raise", "allin")
            for h in history
        )

    def _street_no_bet_yet(self, history, phase):
        return not any(
            h.get("phase") == phase and h.get("action") in ("raise", "allin")
            for h in history
        )

    def _i_was_street_aggressor(self, history, phase):
        aggro = None
        for h in history:
            if h.get("phase") == phase and h.get("action") in ("raise", "allin"):
                aggro = h.get("player")
        return aggro == self.bot_name

    def _sizing(self, pot, pct, min_raise, my_stack):
        target = max(int(pot * pct), min_raise)
        return min(target, my_stack)

    # ── 포스트플랍 ──
    def _decide_postflop(self, msg, variant: sv.StrategyVariant):
        cards = msg.get("your_cards", [])
        community = msg.get("community_cards", [])
        phase = msg.get("phase", "flop")
        to_call = msg.get("to_call", 0)
        min_raise = msg.get("min_raise", 0)
        my_stack = msg.get("my_stack", 0)
        pot = msg.get("pot", 0)
        players = msg.get("players", [])
        history = msg.get("action_history", [])

        if len(cards) < 2 or len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        num_opp = _active_opponents(players, self.bot_name)
        eq = equity(cards, community, num_opponents=num_opp, iters=400)
        multiway = num_opp >= 2

        mw_scale = 0.5 if multiway else 1.0
        # 동적 임계: 7-way까지 도달하면 +18%p (random opp 가정 보정).
        # cap 0.20 — 너무 빡빡하면 좋은 핸드도 폴드.
        mw_tighten = min(0.20, 0.03 * (num_opp - 1)) if multiway else 0.0

        # ICM 압박 → 콜/레이즈 임계값 상향
        icm = self._icm_pressure(msg)
        icm_thresh = float(config.get("icm_pressure_threshold", 0.6))
        icm_bonus = float(config.get("icm_fold_bonus", 0.05)) if icm >= icm_thresh else 0.0

        t_nuts = variant.eq_nuts + mw_tighten + icm_bonus
        t_std = variant.eq_std + mw_tighten + icm_bonus
        t_thin = variant.eq_thin + mw_tighten + icm_bonus

        if to_call == 0:
            return self._decide_check_line(
                eq, pot, min_raise, my_stack, phase, history,
                variant, mw_scale, t_nuts, t_std, t_thin,
            )

        return self._decide_facing_bet(
            eq, pot, to_call, min_raise, my_stack, phase,
            variant, multiway, t_nuts, t_std,
        )

    def _decide_check_line(self, eq, pot, min_raise, my_stack, phase, history,
                           variant, mw_scale, t_nuts, t_std, t_thin):
        if min_raise <= 0:
            return "check", 0

        if eq >= t_nuts:
            return "raise", self._sizing(pot, variant.size_nuts, min_raise, my_stack)
        if eq >= t_std:
            return "raise", self._sizing(pot, variant.size_std, min_raise, my_stack)
        if eq >= t_thin:
            return "raise", self._sizing(pot, variant.size_thin, min_raise, my_stack)

        was_pfr = self._was_preflop_raiser(history)

        if phase == "flop" and was_pfr and self._street_no_bet_yet(history, "flop"):
            if variant.cbet_freq > 0 and random.random() < variant.cbet_freq * mw_scale:
                return "raise", self._sizing(pot, variant.size_std, min_raise, my_stack)

        if phase == "turn" and self._i_was_street_aggressor(history, "flop") \
                and self._street_no_bet_yet(history, "turn"):
            if variant.turn_barrel_freq > 0 and random.random() < variant.turn_barrel_freq * mw_scale:
                return "raise", self._sizing(pot, variant.size_std, min_raise, my_stack)

        if phase == "river" and self._street_no_bet_yet(history, "flop") \
                and self._street_no_bet_yet(history, "turn"):
            if variant.river_probe_freq > 0 and random.random() < variant.river_probe_freq * mw_scale:
                return "raise", self._sizing(pot, variant.size_thin, min_raise, my_stack)

        return "check", 0

    def _decide_facing_bet(self, eq, pot, to_call, min_raise, my_stack, phase,
                           variant, multiway, t_nuts, t_std):
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

        if eq >= t_nuts and min_raise > 0:
            return "raise", self._sizing(pot, variant.size_nuts + 0.25, min_raise, my_stack)
        if eq >= t_std and min_raise > 0:
            return "raise", self._sizing(pot, variant.size_std + 0.20, min_raise, my_stack)

        if eq > pot_odds + variant.call_edge:
            return "call", 0

        if variant.semibluff_freq > 0 and phase == "flop" and not multiway \
                and 0.40 <= eq < t_std and min_raise > 0 \
                and random.random() < variant.semibluff_freq:
            return "raise", self._sizing(pot, variant.size_std + 0.10, min_raise, my_stack)

        return "fold", 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--reset", action="store_true",
                        help="대회 시작시 누적 트래커/스냅샷 초기화")
    args, remaining = parser.parse_known_args()
    # bot_base는 sys.argv[1..3]을 직접 읽음 — --reset 빼고 나머지 그대로 둠
    sys.argv = [sys.argv[0]] + remaining
    GtoBot(reset=args.reset).run()
