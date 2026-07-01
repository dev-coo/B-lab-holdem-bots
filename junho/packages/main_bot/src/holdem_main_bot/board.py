"""보드 텍스처 분석 + 동적 베팅 사이징.

BoardTexture:
- flush_draw: 3-flush 존재 (누군가 draw 가능).
- flush_made: 4-flush+ 존재 (누군가 이미 flush 가능성).
- straight_draw: open-ended / gutshot 가능성 (연속/게이프 카드).
- straight_made: 5장 connector (3+ card) 이미 스트레이트 가능.
- paired: 보드에 짝.
- monotone: 같은 슈트 3장+.
- wetness: 0(dry) ~ 3(very wet).

size_bet(phase, equity, texture, pot, min_raise, my_stack, cfg):
- dry + 강패(equity>=raise_thr) → cfg.bet_frac_dry_strong * pot
- wet + 강패              → cfg.bet_frac_wet_strong * pot
- dry + value(equity>=value_thr) → cfg.bet_frac_dry_value * pot
- wet + value            → cfg.bet_frac_wet_value * pot
- river 는 cfg.river_value_mult 추가 곱
- 최소 min_raise, 최대 my_stack clamp
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from holdem_main_bot.strategy import StrategyConfig

_RANKS = "23456789TJQKA"
_RANK_INDEX = {r: i for i, r in enumerate(_RANKS)}


@dataclass
class BoardTexture:
    flush_draw: bool
    flush_made: bool
    straight_draw: bool
    straight_made: bool
    paired: bool
    monotone: bool
    wetness: int  # 0..3


def _has_straight(ranks: list[int], need: int = 5) -> bool:
    if len(set(ranks)) < need:
        return False
    uniq = sorted(set(ranks), reverse=True)
    for i in range(len(uniq) - need + 1):
        if uniq[i] - uniq[i + need - 1] == need - 1:
            return True
    return False


def _has_open_ended_draw(ranks: list[int]) -> bool:
    """4 연속 랭크 존재 (OESD) 혹은 gutshot 준하는 3 연속 + 인접."""
    if len(set(ranks)) < 3:
        return False
    uniq = sorted(set(ranks), reverse=True)
    # 4 연속
    for i in range(len(uniq) - 3):
        if uniq[i] - uniq[i + 3] == 3:
            return True
    # 3 연속 (gutshot 가능성)
    for i in range(len(uniq) - 2):
        if uniq[i] - uniq[i + 2] == 2:
            return True
    # 4 카드 내에 3 거리 (ex 9,8,6 → gutshot)
    for i in range(len(uniq) - 2):
        if uniq[i] - uniq[i + 2] <= 4:
            return True
    return False


def board_texture(board: list[str]) -> BoardTexture:
    if len(board) < 3:
        return BoardTexture(False, False, False, False, False, False, 0)

    ranks = [_RANK_INDEX[c[0]] for c in board]
    suits = [c[1] for c in board]

    suit_counts: dict[str, int] = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
    max_suit = max(suit_counts.values())
    monotone = max_suit >= 3
    flush_draw = max_suit >= 3 and max_suit < 5 and len(board) <= 4
    flush_made = max_suit >= 5 or (max_suit >= 4 and len(board) >= 4) or (len(board) == 3 and max_suit >= 3)
    # 단순화: 3-flush 보드는 flush draw 경고 표시. 4 이상은 made.
    flush_made = max_suit >= 4

    straight_made = _has_straight(ranks, need=5) if len(board) >= 5 else False
    straight_draw = _has_open_ended_draw(ranks)

    # paired
    rc: dict[int, int] = {}
    for r in ranks:
        rc[r] = rc.get(r, 0) + 1
    paired = any(c >= 2 for c in rc.values())

    wetness = 0
    if flush_draw or (len(board) == 3 and max_suit >= 3):
        wetness += 1
    if straight_draw:
        wetness += 1
    if flush_made or straight_made:
        wetness += 2
    if paired:
        # paired 는 오히려 drawy 하지 않음 → 보정
        wetness = max(0, wetness - 1)
    wetness = min(3, wetness)

    return BoardTexture(
        flush_draw=flush_draw,
        flush_made=flush_made,
        straight_draw=straight_draw,
        straight_made=straight_made,
        paired=paired,
        monotone=monotone,
        wetness=wetness,
    )


def size_bet(
    phase: str,
    equity: float,
    texture: BoardTexture,
    pot: int,
    min_raise: int,
    my_stack: int,
    cfg: "StrategyConfig",
    n_opps: int = 1,
) -> int:
    """equity + 보드 텍스처 + 상대 수 기반 동적 베팅 사이즈.

    반환은 "이번 라운드 총 베팅 목표액" (BOT_REFERENCE §6.2). 호출자는
    `min(max(min_raise, size), my_stack)` 패턴으로 이미 clamp 됨 → 여기서도 한다.

    v2: n_opps >= 2 면 multiway 전용 bet_frac_* 사용 (value 사이즈 축소).
    멀티웨이에서는 여러 상대 fold 유도 어려우니 크게 베팅해도 payoff 나쁨.
    """
    wet = texture.wetness >= 2
    multiway = n_opps >= 2
    if equity >= cfg.equity_raise_threshold:
        if multiway:
            frac = cfg.bet_frac_wet_strong_multiway if wet else cfg.bet_frac_dry_strong_multiway
        else:
            frac = cfg.bet_frac_wet_strong if wet else cfg.bet_frac_dry_strong
    else:
        if multiway:
            frac = cfg.bet_frac_wet_value_multiway if wet else cfg.bet_frac_dry_value_multiway
        else:
            frac = cfg.bet_frac_wet_value if wet else cfg.bet_frac_dry_value

    target = int(pot * frac)
    if phase == "river" and equity >= cfg.equity_value_bet_threshold:
        target = int(target * cfg.river_value_mult)
    target = max(min_raise, target)
    target = min(target, my_stack)
    return target
