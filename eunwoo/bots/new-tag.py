# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""새 TAG 봇 — 상위 20% 레인지 + 몬테카를로 에쿼티."""
import random
from lib.bot_base import BotBase
from lib.equity import equity

RANKS = "23456789TJQKA"

TOP_20 = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    "KQs", "KJs", "KTs", "QJs", "QTs", "JTs",
    "T9s", "98s", "87s", "76s",
    "AKo", "AQo", "AJo", "KQo",
}


def hand_key(cards):
    r1, r2 = cards[0][:-1].upper(), cards[1][:-1].upper()
    s1, s2 = cards[0][-1], cards[1][-1]
    suited = "s" if s1 == s2 else "o"
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
    if r1 == r2:
        return f"{r1}{r2}"
    return f"{r1}{r2}{suited}"


class NewTagBot(BotBase):
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
        history = msg.get("action_history", [])

        if phase == "preflop":
            key = hand_key(cards) if len(cards) == 2 else ""
            if key in TOP_20:
                raise_amt = max(3 * bb, min_raise)
                return "raise", min(raise_amt, my_stack)
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if len(cards) < 2 or len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        eq = equity(cards, community, num_opponents=8, iters=200)

        was_pfr = any(
            h.get("phase") == "preflop"
            and h.get("player") == self.bot_name
            and h.get("action") == "raise"
            for h in history
        )

        # C-bet: 프리플랍 레이저 → 플랍에서 60% 확률로 기계적 베팅
        if phase == "flop" and was_pfr and to_call == 0 and min_raise > 0 and random.random() < 0.6:
            bet = max(int(pot * 0.6), min_raise, bb)
            return "raise", min(bet, my_stack)

        # 강한 패: 팟 75% 사이즈 베팅/레이즈
        if eq >= 0.7 and min_raise > 0:
            bet = max(int(pot * 0.75), min_raise)
            return "raise", min(bet, my_stack)

        # 팟 오즈 기반 콜/폴드
        if to_call == 0:
            return "check", 0
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
        if eq > pot_odds:
            return "call", 0
        return "fold", 0


if __name__ == "__main__":
    NewTagBot().run()
