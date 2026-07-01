"""SPR-indexed decision tree (v5 §B).

SPR (Stack-to-Pot Ratio) = `my_stack / max(pot, 1)`. 같은 equity 라도 SPR 에 따라
최적 액션이 달라진다:

- low (≤3)  : commit 단계. raise 를 쉽게 지르고, 드로우도 끝까지 chase.
- mid (3~10): v4 기본 calibration. 그대로.
- high (>10): 딥 스택. pot control 우선, 오히려 raise 줄이고 bet size 줄임.

v4 는 commit 판정을 `m < 10 & equity >= 0.35` 단일 분기로만 처리. SPR bucket 을
첫 번째 axis 로 두면 postflop 결정 전반에 threshold + sizing 스케일링이 붙는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Bucket = Literal["low", "mid", "high"]


@dataclass(frozen=True)
class SPRAdjust:
    """SPR bucket 별 보정값. StrategyConfig 에서 주입."""

    raise_thr_delta: float
    call_margin_delta: float
    draw_pot_ratio_delta: float
    bet_frac_mult: float


def spr_value(my_stack: int, pot: int) -> float:
    return float(my_stack) / float(max(pot, 1))


def spr_bucket(my_stack: int, pot: int, low_max: float = 3.0, high_min: float = 10.0) -> Bucket:
    """my_stack / pot 으로 bucket. low_max, high_min 은 StrategyConfig 에서 주입."""
    spr = spr_value(my_stack, pot)
    if spr <= low_max:
        return "low"
    if spr > high_min:
        return "high"
    return "mid"


def adjust_for_bucket(
    bucket: Bucket,
    raise_thr_low: float,
    raise_thr_high: float,
    call_margin_low: float,
    call_margin_high: float,
    draw_pot_low: float,
    draw_pot_high: float,
    bet_frac_low: float,
    bet_frac_high: float,
) -> SPRAdjust:
    """bucket 에 따라 v4 기본값에 더할 delta 반환. mid 는 0."""
    if bucket == "low":
        return SPRAdjust(
            raise_thr_delta=-raise_thr_low,
            call_margin_delta=-call_margin_low,
            draw_pot_ratio_delta=draw_pot_low,
            bet_frac_mult=bet_frac_low,
        )
    if bucket == "high":
        return SPRAdjust(
            raise_thr_delta=raise_thr_high,
            call_margin_delta=call_margin_high,
            draw_pot_ratio_delta=-draw_pot_high,
            bet_frac_mult=bet_frac_high,
        )
    return SPRAdjust(
        raise_thr_delta=0.0,
        call_margin_delta=0.0,
        draw_pot_ratio_delta=0.0,
        bet_frac_mult=1.0,
    )
