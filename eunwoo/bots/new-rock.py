# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""Rock 봇 — 극타이트 소극. top 5% 핸드만.

프리플랍: AA/KK/QQ/JJ/TT/AKs/AKo/AQs 만 플레이, 3bb 오픈.
포스트플랍: eq 0.75+ 밸류 베팅, 0.5 이하면 접음. 블러프 0.
"""
from lib.bot_base import BotBase
from lib.equity import equity


RANKS = "23456789TJQKA"
TOP_5 = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}


def _hand_key(cards):
    r1, r2 = cards[0][0].upper(), cards[1][0].upper()
    s1, s2 = cards[0][-1], cards[1][-1]
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
    if r1 == r2:
        return f"{r1}{r2}"
    return f"{r1}{r2}{'s' if s1 == s2 else 'o'}"


def _active_opps(players, name):
    n = sum(1 for p in players if p.get("name") != name and p.get("status", "active") in ("active", "allin"))
    return max(n, 1)


class RockBot(BotBase):
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
        players = msg.get("players", [])

        if len(cards) != 2:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if phase == "preflop":
            key = _hand_key(cards)
            if key in TOP_5:
                target = max(3 * bb, min_raise)
                return "raise", min(target, my_stack)
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        eq = equity(cards, community, num_opponents=_active_opps(players, self.bot_name), iters=300)

        if eq >= 0.75 and min_raise > 0:
            target = max(int(pot * 0.6), min_raise)
            return "raise", min(target, my_stack)
        if to_call == 0:
            return "check", 0
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
        if eq > pot_odds + 0.05:
            return "call", 0
        return "fold", 0


if __name__ == "__main__":
    RockBot().run()
