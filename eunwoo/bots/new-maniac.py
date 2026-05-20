# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""새 Maniac 봇 — LAG 스타일. 공격적 베팅/레이즈 + 리버 블러프."""
import random
from lib.bot_base import BotBase
from lib.equity import equity


class NewManiacBot(BotBase):
    def decide(self, msg):
        cards = msg.get("your_cards", [])
        community = msg.get("community_cards", [])
        phase = msg.get("phase", "preflop")
        to_call = msg.get("to_call", 0)
        min_raise = msg.get("min_raise", 0)
        my_stack = msg.get("my_stack", 0)
        pot = msg.get("pot", 0)
        blind = msg.get("blind", [1, 2])
        bb = blind[1] if len(blind) > 1 else 2

        if phase == "preflop":
            # 누가 이미 레이즈한 상황이면 15% 3벳
            if to_call > bb and min_raise > 0 and random.random() < 0.15:
                raise_amt = max(min_raise * 2, min_raise)
                return "raise", min(raise_amt, my_stack)
            # 30% 확률로 3BB 레이즈
            if min_raise > 0 and random.random() < 0.30:
                raise_amt = max(3 * bb, min_raise)
                return "raise", min(raise_amt, my_stack)
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if len(cards) < 2 or len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        eq = equity(cards, community, num_opponents=8, iters=200)

        # 리버 + equity < 20% → 50% 확률 팟 150% 오버벳 블러프
        if phase == "river" and eq < 0.2 and min_raise > 0 and random.random() < 0.5:
            bet = max(int(pot * 1.5), min_raise)
            return "raise", min(bet, my_stack)

        # 상대 체크 (to_call == 0) → 80% 확률 팟 사이즈 C-bet/블러프
        if to_call == 0:
            if min_raise > 0 and random.random() < 0.8:
                bet = max(pot, min_raise, bb)
                return "raise", min(bet, my_stack)
            return "check", 0

        # 베팅 대응: 팟 오즈 기반
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
        if eq > pot_odds:
            return "call", 0
        return "fold", 0


if __name__ == "__main__":
    NewManiacBot().run()
