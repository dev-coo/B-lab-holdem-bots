# 테스트용 봇 — 모집단 시뮬용 (대회 출전 안 함)
"""Wild Maniac 봇 — VPIP 55%, 무작위 공격. 진짜 미친 놈.

프리플랍: 55% 확률로 참가, 그중 40%는 3벳 or 올인.
포스트플랍: 무조건 60% 확률로 레이즈, 40% 체크/콜. 패 강도 무시.
변동성 극대화 — 높은 1등률 or 조기 탈락.
"""
import random

from lib.bot_base import BotBase


class WildManiacBot(BotBase):
    def decide(self, msg):
        phase = msg.get("phase", "preflop")
        to_call = msg.get("to_call", 0)
        min_raise = msg.get("min_raise", 0)
        my_stack = msg.get("my_stack", 0)
        pot = msg.get("pot", 0)
        blind = msg.get("blind", [1, 2])
        bb = blind[1] if len(blind) > 1 else 2

        if phase == "preflop":
            # 55% 참가
            if random.random() > 0.55:
                return ("check", 0) if to_call == 0 else ("fold", 0)
            # 참가 결정 — 40% 확률로 올인급, 나머지 표준 레이즈
            roll = random.random()
            if roll < 0.15 and my_stack > 0:
                return "allin", 0
            if roll < 0.55 and min_raise > 0:
                target = max(3 * bb, min_raise)
                # 가끔 큰 오버벳
                if random.random() < 0.3:
                    target = max(target * 2, min_raise)
                return "raise", min(target, my_stack)
            return ("check", 0) if to_call == 0 else ("call", 0)

        # 포스트플랍: 60% 레이즈, 30% 콜, 10% 폴드
        roll = random.random()
        if roll < 0.60 and min_raise > 0:
            # 사이즈도 무작위 (팟 50% ~ 팟 150%)
            pct = random.choice([0.5, 0.75, 1.0, 1.5])
            target = max(int(pot * pct), min_raise, bb)
            if random.random() < 0.1:
                return "allin", 0
            return "raise", min(target, my_stack)
        if roll < 0.90:
            return ("check", 0) if to_call == 0 else ("call", 0)
        return ("check", 0) if to_call == 0 else ("fold", 0)


if __name__ == "__main__":
    WildManiacBot().run()
