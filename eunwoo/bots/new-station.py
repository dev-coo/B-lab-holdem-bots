# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""새 Station 봇 — Calling Station 스타일. 프리플랍 VPIP 45%, 포스트플랍 15%+ 무조건 콜."""
import random
from lib.bot_base import BotBase
from lib.equity import equity


class NewStationBot(BotBase):
    def decide(self, msg):
        cards = msg.get("your_cards", [])
        community = msg.get("community_cards", [])
        phase = msg.get("phase", "preflop")
        to_call = msg.get("to_call", 0)
        min_raise = msg.get("min_raise", 0)
        my_stack = msg.get("my_stack", 0)
        pot = msg.get("pot", 0)

        if phase == "preflop":
            # VPIP 45%
            if random.random() < 0.45:
                return ("check", 0) if to_call == 0 else ("call", 0)
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if len(cards) < 2 or len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        eq = equity(cards, community, num_opponents=8, iters=200)

        # 너트급(90%+) → 팟 50% 레이즈
        if eq >= 0.9 and min_raise > 0:
            bet = max(int(pot * 0.5), min_raise)
            return "raise", min(bet, my_stack)

        # 15%+ → 베팅 사이즈 무시 무조건 콜/체크
        if eq >= 0.15:
            return ("check", 0) if to_call == 0 else ("call", 0)

        return ("check", 0) if to_call == 0 else ("fold", 0)


if __name__ == "__main__":
    NewStationBot().run()
