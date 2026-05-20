"""MacuilBot — pokerbot의 Macuil(EV-max enumeration) 두뇌."""
import bots.wooz_bot  # noqa: F401  — sys.path에 vendor 추가
from bots.wooz_bot import WoozBot
from macuil import Macuil


class MacuilBot(WoozBot):
    STRATEGY_KEY = "macuil"

    def _build_strategy(self):
        return Macuil(self.profiler, self.config)


if __name__ == "__main__":
    MacuilBot().run()
