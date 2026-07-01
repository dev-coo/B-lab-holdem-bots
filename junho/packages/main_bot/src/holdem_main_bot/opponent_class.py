"""상대 봇 분류 — 듀얼 모드(exploit vs balanced) 전환의 트리거.

사용자 맥락(v3 동기): 현재 우리가 이기는 상대는 "스크립트로만 동작하는 간단한 봇들".
미래 상대는 "우리처럼 봇을 만드는 상대들" — 적응형·혼합 전략 가능성. 같은 전략은
두 부류에 동시에 최적일 수 없다.

분류 체계:
- `unknown`: hands_seen < min_hands. 기본적으로 balanced 로 시작(안전).
- `script`: 간단한 스크립트 봇. 패턴 단조로움 = VPIP-PFR 차이 적음, 3bet 거의 0,
            베팅 사이즈 고정, 블러프 없음. → **exploit 모드** (현 v2 공격적)
- `adaptive`: 변동성·3bet·블러프 존재. → **balanced 모드** (v3.x 에서 구현,
              현재는 exploit 보수판)

이 모듈은 **분류만** 수행. 모드 전환·전략 분기는 `rule_based.py` 에서.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OpponentClass = Literal["unknown", "script", "adaptive"]


@dataclass(frozen=True)
class ClassificationConfig:
    min_hands_for_classification: int = 20
    # script 판정: VPIP-PFR 차이 < 0.10 (= limp 거의 없음 또는 call-only 봇)
    #              AND 3bet 빈도 < 0.03
    script_vpip_pfr_diff_max: float = 0.10
    script_threebet_rate_max: float = 0.03
    # adaptive 판정: 3bet > 0.05 OR VPIP-PFR > 0.20 (limp/call 다양)
    adaptive_threebet_rate_min: float = 0.05
    adaptive_vpip_pfr_diff_min: float = 0.20


def classify_opponent(
    profile: dict[str, object] | None,
    cfg: ClassificationConfig | None = None,
) -> OpponentClass:
    """단일 상대 프로필 → 분류.

    profile 스키마 (summary.py 참조):
        {hands_seen: int, vpip_n: int, pfr_n: int, threebet_n: int,
         showdown_n: int, showdown_won_n: int, ...}

    vpip_n 등은 카운트(정수) 또는 비율(0~1 float). 양쪽 모두 처리.
    """
    c = cfg or ClassificationConfig()
    if not profile:
        return "unknown"
    try:
        hands = int(profile.get("hands_seen", 0) or 0)
    except (TypeError, ValueError):
        return "unknown"
    if hands < c.min_hands_for_classification:
        return "unknown"

    def _rate(key: str) -> float:
        raw = profile.get(key)
        if raw is None:
            return 0.0
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return 0.0
        # 이미 0~1 비율이면 그대로, 카운트면 hands 로 나눔.
        if 0.0 <= v <= 1.0:
            return v
        return v / max(hands, 1)

    vpip = _rate("vpip_n") or _rate("vpip")
    pfr = _rate("pfr_n") or _rate("pfr")
    threebet = _rate("threebet_n") or _rate("threebet")

    diff = vpip - pfr

    # adaptive 조건 우선 (강한 신호)
    if threebet >= c.adaptive_threebet_rate_min:
        return "adaptive"
    if diff >= c.adaptive_vpip_pfr_diff_min:
        return "adaptive"

    # script 조건
    if diff <= c.script_vpip_pfr_diff_max and threebet <= c.script_threebet_rate_max:
        return "script"

    # 애매 → unknown (보수적)
    return "unknown"


def classify_all(
    profiles: dict[str, dict[str, object]] | None,
    cfg: ClassificationConfig | None = None,
) -> dict[str, OpponentClass]:
    """전체 프로필 → {name: class} 매핑."""
    if not profiles:
        return {}
    return {name: classify_opponent(prof, cfg) for name, prof in profiles.items()}


def resolve_table_mode(
    active_names: list[str],
    classes: dict[str, OpponentClass],
    strategy_mode: str = "auto",
) -> str:
    """이번 핸드의 활성 상대들 분류로 최종 사용 모드 결정.

    규칙:
    - strategy_mode 가 "exploit"/"balanced" 이면 강제 그대로.
    - "auto":
        - 활성 상대 중 adaptive 가 1명이라도 있으면 "balanced"
        - 전원 script 면 "exploit"
        - 그 외(unknown 포함) → "balanced" (보수적 기본값)
    """
    if strategy_mode in ("exploit", "balanced"):
        return strategy_mode
    if not active_names:
        return "balanced"
    seen = [classes.get(n, "unknown") for n in active_names]
    if any(c == "adaptive" for c in seen):
        return "balanced"
    if all(c == "script" for c in seen):
        return "exploit"
    return "balanced"
