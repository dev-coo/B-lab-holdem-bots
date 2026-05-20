# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""Passive Caller 봇 — 림프 위주, 체크콜 선호. 인간 패시브 시뮬.

프리플랍: VPIP 35%, 강한 패(top 10%)만 레이즈, 나머진 림프/콜.
포스트플랍: eq 0.7+ 만 레이즈, 나머진 체크콜 (팟오즈 관대).
AF 1.5 내외 — Hugo/Wooz 유형.
"""
from lib.bot_base import BotBase
from lib.equity import equity


RANKS = "23456789TJQKA"
RAISE_RANGE = {
    "AA", "KK", "QQ", "JJ", "TT",
    "AKs", "AQs", "AJs", "AKo", "AQo",
    "KQs", "KJs",
}
PLAYABLE_RANGE = {  # 콜/림프 범위 (레이즈 핸드 포함)
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    "KQs", "KJs", "KTs", "K9s", "K8s",
    "QJs", "QTs", "Q9s",
    "JTs", "J9s",
    "T9s", "98s", "87s", "76s", "65s",
    "AKo", "AQo", "AJo", "ATo", "A9o",
    "KQo", "KJo", "QJo", "JTo",
}


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


class PassiveCallerBot(BotBase):
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
            # 프리미엄만 레이즈 (림프 없는 스팟)
            if key in RAISE_RANGE and to_call <= bb:
                target = max(3 * bb, min_raise)
                return "raise", min(target, my_stack)
            # 플레이어블이면 림프/콜 (팟 대비 저렴하면)
            if key in PLAYABLE_RANGE:
                if to_call <= bb * 3:
                    return ("check", 0) if to_call == 0 else ("call", 0)
                # 너무 비싸면 접음
                if key in RAISE_RANGE:  # 프리미엄은 콜
                    return "call", 0
                return "fold", 0
            return ("check", 0) if to_call == 0 else ("fold", 0)

        if len(community) < 3:
            return ("check", 0) if to_call == 0 else ("fold", 0)

        eq = equity(cards, community, num_opponents=_active_opps(players, self.bot_name), iters=300)

        # 아주 강할 때만 레이즈 (씬밸류 없음)
        if eq >= 0.75 and min_raise > 0:
            target = max(int(pot * 0.5), min_raise)
            return "raise", min(target, my_stack)

        # 체크 들어오면 체크
        if to_call == 0:
            return "check", 0

        # 콜 관대: 팟오즈보다 -5%p 까지 콜 (loose caller)
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
        if eq > pot_odds - 0.05:
            return "call", 0
        return "fold", 0


if __name__ == "__main__":
    PassiveCallerBot().run()
