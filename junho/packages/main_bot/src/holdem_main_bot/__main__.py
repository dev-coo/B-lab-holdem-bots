"""CLI entry point: `uv run python -m holdem_main_bot [--debug] [--host] [--port]`.

봇 패키지는 자기 `.env` 를 디폴트로 로드한다. 루트 `.env` 는 무시.
`--env-file` CLI 플래그나 `HOLDEM_ENV_FILE` 환경변수로 덮어쓸 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from holdem_core.app import run
from holdem_core.core.config import Settings

from holdem_main_bot.strategy import BalancedStrategy, StrategyConfig

# 이 봇 패키지 root (pyproject.toml 이 있는 디렉토리) 의 .env 를 기본으로 사용.
# src/holdem_main_bot/__main__.py → ../../ 가 package root.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ENV = _PACKAGE_ROOT / ".env"


def _build_strategy(settings: Settings) -> BalancedStrategy:
    # profile_path 는 봇별 DEBUG_DIR 에 붙여서 SummaryWriter 가 쓰는 위치와 일치.
    # 기본값 `.debug/opponent_profiles.json` 은 DEBUG_DIR=.debug 인 balanced 에서만
    # 맞고, 다른 봇들이 subdir 쓰면 경로 불일치 생김.
    profile_path = str(Path(settings.DEBUG_DIR) / "opponent_profiles.json")
    bluff_prior_path = str(Path(settings.DEBUG_DIR) / "bluff_prior.json")
    cfg = StrategyConfig(
        mc_samples=settings.MC_SAMPLES,
        equity_call_margin=settings.EQUITY_CALL_MARGIN,
        equity_value_bet_threshold=settings.EQUITY_VALUE_BET_THRESHOLD,
        equity_raise_threshold=settings.EQUITY_RAISE_THRESHOLD,
        max_bet_fraction_of_pot=settings.MAX_BET_FRACTION_OF_POT,
        postflop_call_cap_fraction=settings.POSTFLOP_CALL_CAP_FRACTION,
        profile_path=profile_path,
        bluff_prior_path=bluff_prior_path,
        debug_dir=settings.DEBUG_DIR,
    )
    return BalancedStrategy(cfg=cfg, bot_name=settings.BOT_NAME)


def main() -> None:
    run(
        strategy_factory=_build_strategy,
        default_env_file=_DEFAULT_ENV,
    )


if __name__ == "__main__":
    main()
