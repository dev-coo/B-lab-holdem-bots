"""holdem-main-bot — 메인 운영 봇 (v3 BalancedStrategy).

position / M-ratio / preflop 레인지 / multiway / 보드 텍스처 / 드로우 / 상대 프로필 기반
rule 전략. 실전 검증된 주력. 다른 봇(aggressive/gto-lean/experimental)이 당분간 이
전략을 재사용하므로 `BalancedStrategy` / `StrategyConfig` 는 공개 API 로 유지.

`python -m holdem_main_bot` 으로 실행.
"""

from holdem_main_bot.strategy import BalancedStrategy, StrategyConfig

__all__ = ["BalancedStrategy", "StrategyConfig"]
