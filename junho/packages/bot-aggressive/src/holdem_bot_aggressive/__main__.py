"""CLI entry point: `uv run python -m holdem_bot_aggressive`.

**스캐폴드 단계**: 현재는 BalancedStrategy 를 그대로 쓴다. 식별자(BOT_NAME, PORT,
DEBUG_DIR 등) 만 `.env` 에서 다르게 해서 "별도 프로세스 · 별도 정체성" 으로 실행.
봇 고유 전략이 생기면 `_build_strategy` 안에서 교체.
"""

from __future__ import annotations

from pathlib import Path

from holdem_core.app import run
from holdem_core.core.config import Settings
from holdem_main_bot.strategy import BalancedStrategy, StrategyConfig

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ENV = _PACKAGE_ROOT / ".env"


def _build_strategy(settings: Settings) -> BalancedStrategy:
    # TODO: aggressive/LAG 전용 StrategyConfig 로 교체 (wider open range,
    # higher bluff freq 등). 현재는 balanced 기본값 그대로.
    profile_path = str(Path(settings.DEBUG_DIR) / "opponent_profiles.json")
    cfg = StrategyConfig(
        mc_samples=settings.MC_SAMPLES,
        equity_call_margin=settings.EQUITY_CALL_MARGIN,
        equity_value_bet_threshold=settings.EQUITY_VALUE_BET_THRESHOLD,
        equity_raise_threshold=settings.EQUITY_RAISE_THRESHOLD,
        max_bet_fraction_of_pot=settings.MAX_BET_FRACTION_OF_POT,
        postflop_call_cap_fraction=settings.POSTFLOP_CALL_CAP_FRACTION,
        profile_path=profile_path,
        debug_dir=settings.DEBUG_DIR,
    )
    return BalancedStrategy(cfg=cfg, bot_name=settings.BOT_NAME)


def main() -> None:
    run(strategy_factory=_build_strategy, default_env_file=_DEFAULT_ENV)


if __name__ == "__main__":
    main()
