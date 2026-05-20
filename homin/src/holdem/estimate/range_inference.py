"""Range inference — 상대의 액션 이력으로 플레이 가능 핸드 범위를 좁힘.

근거: plan 3-2 / H.3, D5.

최소 구현:
  - Preflop opener → 포지션별 opening_chart (default balanced range).
  - VPIP 가 population 대비 현저히 높으면 ×1.3 확장, 낮으면 ×0.8 축소 (coarse).
  - Postflop 액션 필터: 간이 — raise/bet 시 range 상위 40%, check 시 전 range 유지.

반환: hand code set (예: {"AA", "KK", "QQ", "AKs", ...}).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..decide.hand_notation import expand_range
from ..decide.opening_chart import OpeningChart, default_opening_chart
from ..state.player_profile import PlayerProfile


# 간이 핸드 강도 순위 — preflop equity 기준 대략 상위 25%.
_PREMIUM_HANDS = frozenset(expand_range("77+,ATs+,AJo+,KQs"))
_STRONG_HANDS = frozenset(expand_range("22+,A2s+,KTs+,QJs,ATo+,KJo+"))
# Broadways & suited connectors
_PLAYABLE_HANDS = frozenset(expand_range(
    "22+,A2s+,A7o+,K9s+,KJo+,Q9s+,QJo,J9s+,JTo,T9s,98s,87s,76s"
))


@dataclass(frozen=True)
class InferredRange:
    hands: frozenset[str]
    confidence: float       # 0 (fully prior) .. 1 (fully personal)


def _vpip_multiplier(profile: PlayerProfile | None) -> float:
    """VPIP 상대값 (population ~25% 기준) → range 확장/축소 계수."""
    if profile is None or profile.hands_seen < 20:
        return 1.0
    v = profile.vpip()
    if v <= 0.15:
        return 0.75
    if v <= 0.22:
        return 0.9
    if v <= 0.30:
        return 1.0
    if v <= 0.40:
        return 1.2
    return 1.4


def infer_open_range(
    pos_class: str,
    profile: PlayerProfile | None = None,
    chart: OpeningChart | None = None,
) -> InferredRange:
    """상대가 open raise 했을 때 추정 range."""
    chart = chart or default_opening_chart()
    base = chart.ranges.get(pos_class) or frozenset()
    mult = _vpip_multiplier(profile)
    confidence = min(1.0, (profile.hands_seen / 80.0) if profile else 0.0)

    if mult >= 1.0:
        # 확장은 playable 풀 상한까지만.
        extra = _PLAYABLE_HANDS - base
        n_extra = int(round((mult - 1.0) * len(extra)))
        if n_extra > 0:
            extra_sorted = sorted(extra)   # 결정적 선택을 위해 정렬
            chosen = frozenset(extra_sorted[:n_extra])
            base = base | chosen
    else:
        # 축소: premium-leaning 상위 절반만 유지.
        # base 의 약한 핸드를 제거 — _PREMIUM_HANDS 를 뼈대로.
        shrunk = base & (_STRONG_HANDS | _PREMIUM_HANDS)
        shrink_ratio = mult   # 예: 0.75 → 75% 유지
        if shrink_ratio < 1.0 and len(base) > 0:
            base_sorted = sorted(base)
            keep_n = max(len(shrunk), int(len(base_sorted) * shrink_ratio))
            base = frozenset(base_sorted[:keep_n])

    return InferredRange(hands=base, confidence=confidence)


def filter_after_raise(inferred: InferredRange) -> InferredRange:
    """상대가 postflop raise → premium/strong 만 유지."""
    narrowed = inferred.hands & _STRONG_HANDS
    if not narrowed:
        narrowed = inferred.hands & _PREMIUM_HANDS
    return InferredRange(hands=narrowed, confidence=inferred.confidence)


def filter_after_call(inferred: InferredRange) -> InferredRange:
    """상대가 call — raise 범위 제외 (상단 강함은 보통 3bet). 단순화: 그대로 유지."""
    # 실제로는 3bet 이 기대되는 상위 핸드 제외. 데이터 없으므로 그대로.
    return inferred


def filter_after_check(inferred: InferredRange) -> InferredRange:
    """Check — 정보 이득 적음. 그대로."""
    return inferred
