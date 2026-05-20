"""HugoBot — pokerbot의 AdaptiveTAG 두뇌를 우리 BotBase로 운영.

wooz_bot.py와 동일 어댑터, 전략만 AdaptiveTAG로 교체.
"""
import bots.wooz_bot  # noqa: F401  — sys.path에 vendor 추가하는 사이드이펙트만 필요
from bots.wooz_bot import WoozBot
from strategy import AdaptiveTAG  # vendor 우선 sys.path 덕분에 import 가능


class HugoBot(WoozBot):
    STRATEGY_KEY = "hugo"

    def _build_strategy(self):
        return AdaptiveTAG(self.profiler, self.config)


if __name__ == "__main__":
    HugoBot().run()
