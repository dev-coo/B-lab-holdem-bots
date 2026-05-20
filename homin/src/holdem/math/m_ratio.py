"""M ratio — 토너먼트 압박 지표.

정의 (BOT_GUIDE §11):
    M = my_stack / (SB + BB)

해석:
    M > 20:  deep, 정상 플레이
    15 < M ≤ 20:  mid
    8  < M ≤ 15:  hybrid
    M  ≤ 8:  push_fold
"""
from __future__ import annotations


def compute_m(stack: int | float, sb: int | float, bb: int | float) -> float:
    """M = stack / (sb + bb).

    blinds 합 0 이면 float('inf') 반환 (시작 전/오류 상태).
    음수 스택은 0 으로 clamp (이벤트 도착 타이밍 이슈 방어).
    """
    total_blinds = sb + bb
    if total_blinds <= 0:
        return float("inf")
    s = max(stack, 0)
    return s / total_blinds
