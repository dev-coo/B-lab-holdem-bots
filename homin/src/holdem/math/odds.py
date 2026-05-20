"""Layer 0 — parameter-free 포커 수학.

근거: plan Section H.1.a, H.4.
모든 함수는 상대 모델 없이 순수 수학적 최저 기준.

정의 (BOT_GUIDE §5.3):
  - pot        : 현재 팟 (to_call 이 이미 포함된 상태면 `pot_before_call` 파라미터로 구분)
  - to_call    : 콜하려면 내야 할 금액
  - bet        : 상대 또는 본인의 이번 스트리트 베팅 금액
"""
from __future__ import annotations


def pot_odds(to_call: int | float, pot_after_bet: int | float) -> float:
    """브레이크이븐 에퀴티 = to_call / (pot + to_call).

    콜 후 pot = pot_after_bet + to_call 이 아니라, `pot_after_bet` 이
    이미 상대 bet 을 포함한 금액이면, 콜 후 총 pot = pot_after_bet + to_call.
    break-even = to_call / (pot_after_bet + to_call).
    """
    denom = pot_after_bet + to_call
    if denom <= 0:
        return 1.0
    return to_call / denom


def required_equity_to_call(to_call: int | float, pot_after_bet: int | float) -> float:
    """pot_odds 의 다른 이름. 명시성 때문에 별도 함수."""
    return pot_odds(to_call, pot_after_bet)


def mdf(pot_before_bet: int | float, bet: int | float) -> float:
    """Minimum Defense Frequency = pot / (pot + bet).

    이 비율 이하로 폴드하면 상대의 어떤 블러핑 빈도에도 exploitable.
    값의 의미: "내 range 중 이 비율만큼은 방어(콜/레이즈)해야 한다."
    """
    denom = pot_before_bet + bet
    if denom <= 0:
        return 0.0
    return pot_before_bet / denom


def alpha(pot_before_bet: int | float, bet: int | float) -> float:
    """Alpha (블러핑 break-even fold 빈도) = bet / (pot + bet).

    *Mathematics of Poker* (Chen-Ankenman) 정의.
    상대가 이 비율 이상 폴드하면 0-equity bluff 도 +EV.

    주의: 어떤 자료는 `bet / (pot + 2·bet)` 를 alpha 라 표기하는데, 그건
    **상대의 required equity to call** 이다. 서로 다른 양.
    """
    denom = pot_before_bet + bet
    if denom <= 0:
        return 0.0
    return bet / denom


def break_even_equity_for_drawing(to_call: int | float, pot_after_bet: int | float,
                                  implied_odds_multiplier: float = 1.0) -> float:
    """드로우 결정에서의 break-even.

    implied_odds_multiplier > 1 이면 implied odds 를 고려하여 임계가 낮아짐.
    (future street 에서 추가 이득을 기대하는 경우)
    """
    raw = pot_odds(to_call, pot_after_bet)
    return max(0.0, raw / implied_odds_multiplier)


def required_fold_equity_for_bluff(pot_before_bet: int | float, bet: int | float,
                                   bluff_equity: float = 0.0) -> float:
    """0-equity 이상의 블러핑도 고려한 최소 필요 fold 빈도.

    bluff_equity = 콜 받은 후 showdown 승률 기대값.
    공식: f* = (bet - bluff_equity · (pot + 2bet)) / (pot + bet - bluff_equity · (pot + 2bet))
    간략: bluff_equity=0 → alpha.
    """
    pot = pot_before_bet
    numer = bet - bluff_equity * (pot + 2 * bet)
    if numer <= 0:
        # 상대가 전혀 폴드 안 해도 +EV (equity 만으로 충분)
        return 0.0
    denom = (pot + bet) - bluff_equity * (pot + 2 * bet)
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, numer / denom))
