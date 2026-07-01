"""holdem-bot-aggressive — LAG 성향 봇 스캐폴드.

**현재는 BalancedStrategy 재사용 스텁**. 자기 전략 작성 시:
  1. 이 디렉토리에 `strategy.py` 추가 (`Strategy` Protocol 구현)
  2. `__main__.py` 에서 `_build_strategy` 를 자기 봇 strategy 로 교체
  3. `preflop_ranges.py` 등 레인지 파일도 같은 디렉토리에
"""
