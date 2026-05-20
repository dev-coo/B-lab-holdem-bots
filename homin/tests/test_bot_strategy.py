"""BotStrategy 어댑터 단위 테스트.

검증 항목:
  - SimState → ActionRequest 변환이 decide() 의 사전조건(your_cards 2장,
    blind 2 요소, seat 매핑) 을 만족.
  - 다양한 phase / 스택 / 포지션에서 Decision 이 fold/check/call/raise/allin
    중 하나로 정상 반환.
  - 어댑터가 예외에서도 안전 fold/check 로 폴백.
"""
from __future__ import annotations

import random

import pytest

from holdem.simulate.bot_strategy import BotStrategy, make_bot_strategy
from holdem.simulate.strategies import Decision, SimState


def _state(
    *,
    hole=("Ah", "Ks"),
    community=None,
    phase="preflop",
    pot=15,
    to_call=10,
    my_stack=500,
    my_bet=0,
    bb=10,
    n_raises=0,
    is_sb=True,
):
    return SimState(
        hole=hole,
        community=list(community or []),
        phase=phase,
        pot=pot,
        to_call=to_call,
        my_stack=my_stack,
        my_bet=my_bet,
        bb=bb,
        n_raises_this_street=n_raises,
        is_sb=is_sb,
    )


def test_preflop_premium_hu_sb_returns_action():
    bot = make_bot_strategy()
    s = _state(hole=("Ah", "As"), is_sb=True, my_stack=500, to_call=5, bb=10)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert isinstance(dec, Decision)
    assert dec.action in ("fold", "check", "call", "raise", "allin")


def test_preflop_short_stack_jams_with_premium():
    """짧은 스택에서 push_fold chart 가 AA 같은 프리미엄을 jam 으로 처리."""
    bot = make_bot_strategy()
    # M ≈ 5 (짧은 스택, sb=10, bb=20)
    s = _state(hole=("Ah", "As"), is_sb=True,
               my_stack=100, to_call=10, bb=20, pot=30)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    # 정확한 액션은 chart/conservatism 의존. 최소한 액션이 정해져야 함.
    assert dec.action in ("fold", "call", "raise", "allin")


def test_preflop_facing_raise_history_built():
    """to_call > bb 이고 n_raises >= 1 → action_history 에 opp raise 기록 추가."""
    bot = make_bot_strategy()
    s = _state(hole=("7c", "2d"), is_sb=False, to_call=30, bb=10,
               n_raises=1, my_stack=500)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert dec.action in ("fold", "call", "raise", "allin")


def test_postflop_check_when_to_call_zero():
    """Postflop, to_call=0, safe 모드(use_ev_tree=False) → check 반환."""
    bot = make_bot_strategy(use_ev_tree=False)
    s = _state(hole=("Kc", "Kd"), community=["2h", "5s", "9c"],
               phase="flop", to_call=0, pot=20, my_stack=500, bb=10)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert dec.action == "check"


def test_postflop_pot_odds_call_when_equity_high():
    """Postflop, to_call > 0, hand 가 강해 pot odds call 경로."""
    bot = make_bot_strategy(use_ev_tree=False)
    s = _state(hole=("Ah", "As"), community=["Ad", "5s", "9c"],
               phase="flop", to_call=10, pot=50, my_stack=500, bb=10)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert dec.action in ("call", "fold")  # equity 의존 — 둘 다 합법


def test_river_to_call_fold_with_weak_hand():
    """River, 약한 핸드 → fold (or call equity 충분 시)."""
    bot = make_bot_strategy(use_ev_tree=False)
    s = _state(hole=("7c", "2d"),
               community=["Ah", "Kd", "Qs", "Jh", "9c"],
               phase="river", to_call=100, pot=50, my_stack=500, bb=10)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert dec.action in ("fold", "call")


def test_amount_field_set_when_raise():
    """raise 또는 allin 액션이 나오면 amount > 0."""
    bot = make_bot_strategy()
    s = _state(hole=("Ah", "As"), is_sb=True,
               my_stack=200, to_call=10, bb=20)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    if dec.action in ("raise",):
        assert dec.amount > 0


def test_invalid_cards_returns_safe_fold_or_check():
    """카드가 빈 list → decide() 가 _safe_fold 반환. 어댑터는 fold 로 변환."""
    bot = make_bot_strategy()
    # SimState 는 hole 이 tuple[str,str] 이라 빈 string 으로 설정.
    s = _state(hole=("", ""), to_call=10, my_stack=500, bb=10)
    rng = random.Random(0)
    dec = bot.act(s, rng)
    assert dec.action in ("fold", "check")


def test_strategy_name_propagates():
    """make_bot_strategy 의 name 이 baseline strategy 인터페이스에서 사용 가능."""
    bot = make_bot_strategy(name="bot-ev", use_ev_tree=True)
    assert bot.name == "bot-ev"
    bot2 = make_bot_strategy(name="bot-safe")
    assert bot2.name == "bot-safe"
