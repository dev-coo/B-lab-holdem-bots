"""토너먼트 단계 식별 + stage 별 conservatism 보정.

`Stage` enum 과 `identify_stage(req)` — alive 인원에 대한 magic check 가 정책
코드 내에 흩어지지 않도록 단일 진리.

`stage_bluff_multiplier(stage)` — P2 의 핵심: 단계별 bluff_factor 보정.
1 등 승률 우선이라는 목표를 반영해 다음 정책으로 설정:
  - early / mid                 : 1.0  (chip-EV 그대로)
  - near_final / final_table    : 0.85 / 0.80  (버블/페이아웃 점핑 단계 — flip 회피)
  - heads_up                    : 1.15  (chip = chip-EV. 손실 ≠ ladder 위험)

ICM 자체는 ITM 보호용 — 직접 적용 시 1 등 승률 감소 가능. 따라서 본 모듈은
ICM 수치를 직접 EV 에 주입하지 않고, **bluff_factor multiplier** 로 단순화.
정밀 ICM 가중은 후속 PR 에서 별도 옵션으로 추가.
"""
from __future__ import annotations

import dataclasses
from enum import Enum
from typing import TYPE_CHECKING

from ..transport import protocol as p

if TYPE_CHECKING:
    from .conservatism import ConservatismProfile


class Stage(str, Enum):
    EARLY = "early"
    MID = "mid"
    NEAR_FINAL = "near_final"
    FINAL_TABLE = "final_table"
    HEADS_UP = "heads_up"


def _table_player_count(req: p.ActionRequest) -> int:
    """req.players 의 길이 — 탈락자는 server 가 list 에서 제거.

    안전을 위해 빈 이름 placeholder 는 제외 (테스트 / 멀티웨이 시뮬에서 더미
    슬롯을 채우는 경우 보호).
    """
    return sum(1 for pl in req.players if (pl.name or "").strip())


def identify_stage(
    req: p.ActionRequest, *, original_table_size: int | None = None
) -> Stage:
    """ActionRequest → Stage. 활성 테이블 인원수 + 시작 인원 기반 분류.

    P5-2 / P-6max: small-table (5-6 max) 토너먼트는 시작 인원이 곧 정상 게임 →
    full-table = MID, 1명 빠지면 NEAR_FINAL, 2명+ 빠지면 FINAL_TABLE.

    분기 규칙:
      - n ≤ 2 → HEADS_UP (모든 토너먼트 사이즈 공통)
      - original_table_size ∈ {3,4,5,6}: small-table 분기
          n == size  → MID (full)
          n == size-1 → NEAR_FINAL (1명 탈락)
          n ≤ size-2  → FINAL_TABLE
      - 그 외 (≥7 또는 None): 9-max 기존 임계
    """
    n = _table_player_count(req)
    if n <= 2:
        return Stage.HEADS_UP
    if original_table_size is not None and 3 <= original_table_size <= 6:
        # small-table (5-max / 6-max). 시작 인원이 곧 full game.
        if n >= original_table_size:
            return Stage.MID
        if n == original_table_size - 1:
            return Stage.NEAR_FINAL
        return Stage.FINAL_TABLE
    # 9-max (또는 size 알 수 없음) 디폴트.
    if n <= 4:
        return Stage.FINAL_TABLE
    if n <= 6:
        return Stage.NEAR_FINAL
    if n <= 8:
        return Stage.MID
    return Stage.EARLY


# 1 등 승률 우선 관점의 stage 별 bluff_factor multiplier.
# v7: table-size 별 분기. 5p / 6p 의 NEAR_FINAL/FINAL_TABLE 는 의미가 다름.
#   5p NEAR_FINAL = 4-handed bubble (3 paid)        → 강한 보수 (0.85)
#   5p FINAL_TABLE = 3-handed ITM                   → 약한 보수 (0.93)
#   6p NEAR_FINAL = 5-handed pre-bubble             → chip 누적 우선 (0.97)
#   6p FINAL_TABLE = 4-handed bubble or 3-handed ITM → 약한 보수 (0.93)
# 7p+ 또는 size 알 수 없음 → flat default (기존 v5-B 부분 롤백 값).
_STAGE_BLUFF_MULT_DEFAULT: dict[Stage, float] = {
    Stage.EARLY: 1.00,
    Stage.MID: 1.00,
    Stage.NEAR_FINAL: 0.92,
    Stage.FINAL_TABLE: 0.93,
    Stage.HEADS_UP: 1.10,
}

# table-size 별 NEAR_FINAL/FINAL_TABLE 의 override. 그 외 stage 는 default 사용.
_STAGE_BLUFF_MULT_BY_SIZE: dict[int, dict[Stage, float]] = {
    5: {
        Stage.NEAR_FINAL: 0.85,
        Stage.FINAL_TABLE: 0.93,
    },
    6: {
        Stage.NEAR_FINAL: 0.97,
        Stage.FINAL_TABLE: 0.93,
    },
}

# v7 호환성: 외부에서 _STAGE_BLUFF_MULT 를 import 하던 코드가 있으면 default 로 fallback.
_STAGE_BLUFF_MULT = _STAGE_BLUFF_MULT_DEFAULT


def stage_bluff_multiplier(stage: Stage, table_size: int | None = None) -> float:
    """Stage × table_size 별 bluff_factor 곱셈 보정. 1.0 = 변경 없음.

    < 1.0  → 더 보수 (flip 회피, chip 손실 위험 회피)
    > 1.0  → 더 공격 (HU 처럼 chip-EV 가 곧 1 등 EV)

    table_size 미지정 / 7+ 는 default flat 사용.
    """
    if table_size is not None:
        size_overrides = _STAGE_BLUFF_MULT_BY_SIZE.get(table_size)
        if size_overrides is not None and stage in size_overrides:
            return size_overrides[stage]
    return _STAGE_BLUFF_MULT_DEFAULT.get(stage, 1.0)


def apply_stage_to_conservatism(
    cons: "ConservatismProfile", stage: Stage, table_size: int | None = None
) -> "ConservatismProfile":
    """ConservatismProfile 에 stage_bluff_multiplier 를 적용한 새 인스턴스 반환.

    cons.bluff_factor *= stage_bluff_multiplier(stage, table_size). multiplier == 1.0
    이면 원본을 그대로 반환 (할당 회피).
    """
    mult = stage_bluff_multiplier(stage, table_size)
    if mult == 1.0:
        return cons
    new_bf = max(0.0, min(1.0, cons.bluff_factor * mult))
    return dataclasses.replace(cons, bluff_factor=new_bf)
