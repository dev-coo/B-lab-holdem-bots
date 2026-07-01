"""Fold-equity + EV(action) primitive (v5 §A).

`_postflop` 이 기존에는 `equity ≥ raise_thr → raise` 식의 threshold cascade 로만
동작했다. 이 모듈은:
  1. 보드 텍스처 · 상대 tier · 프로필 통계로 fold_equity (FE) 를 추정한다.
  2. 각 액션의 EV 를 계산해 argmax 로 선택한다.

기존 threshold 는 **safety floor** 로 유지한다 (EV argmax 가 너무 공격적으로
기울어 equity 가 낮은데도 raise 를 고르는 사고 방지). 호출자는 argmax 결과와
safety 결과를 동시에 얻고, safety 가 raise 를 금지하면 downgrade 한다.

반환되는 EV 단위는 "이번 의사결정이 끝난 뒤 얻는 평균 칩 (현재 pot 제외)" —
절대값 비교가 아니라 **같은 의사결정 내에서만 argmax** 목적.

공식 (heads-up 가정, multiway 는 호출자가 equity 를 이미 multiway MC 로 얻었을
것이므로 그대로 통과):

  EV_raise = fe * pot
             + (1 - fe) * [(2 * equity - 1) * (pot + raise_size + to_call)]
           * 단, fold-equity 가 0 이면 순수 valuebet EV 와 같음.
  EV_call  = equity * (pot + to_call) - (1 - equity) * to_call
  EV_check = 0  (to_call == 0 일 때 baseline)
  EV_fold  = 0

`raise_size` 는 호출자가 결정한 목표 bet (size_bet 결과). 이 값은 _postflop 가
이미 계산해서 넘겨준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# FE 휴리스틱 테이블. 실전 로그·프로필 통계 없을 때의 폴백.
# 보드 텍스처 × 상대 tier 2 축.
_FE_BASE: dict[str, dict[str, float]] = {
    "dry": {"top10": 0.18, "top20": 0.25, "top40": 0.35, "any": 0.40},
    "semi": {"top10": 0.14, "top20": 0.20, "top40": 0.28, "any": 0.33},
    "wet": {"top10": 0.10, "top20": 0.15, "top40": 0.22, "any": 0.27},
}

# 프로필 fold_to_cbet 비율이 있을 때 우선 사용 (clamp 후 보정).
_FE_PROFILE_MIN = 0.05
_FE_PROFILE_MAX = 0.70
_FE_TOP10_CAP = 0.45  # top10 상대는 fe 상한 (risk-management)
_FE_DEFAULT_CAP = 0.65


def _bucket_board(wetness: int) -> str:
    """board_texture.wetness 0..3 → dry/semi/wet."""
    if wetness <= 0:
        return "dry"
    if wetness <= 1:
        return "semi"
    return "wet"


def estimate_fold_equity(
    opp_tier: str | None,
    board_wetness: int,
    profile_stats: dict[str, Any] | None = None,
    phase: str = "flop",
    multiway: bool = False,
) -> float:
    """FE ∈ [0.05, 0.70] 반환.

    profile_stats 에 `fold_to_cbet_rate` 있으면 우선 반영 (blend 50/50 with table).
    multiway 에서는 한 명만 fold 해도 pot 이 다시 열리므로 discount (×0.7).
    river 는 draw 가 끝났으니 FE 가 감소 (×0.9).
    """
    tier = opp_tier if opp_tier in ("top10", "top20", "top40", "any") else "any"
    bucket = _bucket_board(board_wetness)
    base = _FE_BASE[bucket].get(tier, _FE_BASE[bucket]["any"])

    fe = base
    if profile_stats:
        raw = profile_stats.get("fold_to_cbet_rate")
        if isinstance(raw, (int, float)) and 0.0 <= float(raw) <= 1.0:
            fe = 0.5 * base + 0.5 * float(raw)

    if multiway:
        fe *= 0.7
    if phase == "river":
        fe *= 0.9

    cap = _FE_TOP10_CAP if tier == "top10" else _FE_DEFAULT_CAP
    if fe < _FE_PROFILE_MIN:
        fe = _FE_PROFILE_MIN
    if fe > cap:
        fe = cap
    return fe


@dataclass(frozen=True)
class EVResult:
    ev_raise: float
    ev_call: float
    ev_check: float
    ev_fold: float
    fe: float
    choice: str  # "raise" / "call" / "check" / "fold"


def action_ev(
    equity: float,
    pot: int,
    to_call: int,
    my_stack: int,
    raise_size: int,
    fold_equity: float,
) -> EVResult:
    """액션별 EV 계산 + argmax 선택.

    `raise_size` 는 이번 라운드 총 베팅 목표액 (size_bet 결과, _clamp_raise_amount 전).
    호출자는 결과의 ev_* 값과 choice 를 모두 meta 에 기록한다.
    """
    fe = max(0.0, min(1.0, float(fold_equity)))
    pot_f = float(pot)
    tc_f = float(to_call)
    raise_add = max(0, int(raise_size) - int(to_call))
    # raise 가 to_call 보다 작으면 raise 가 아니라 call 과 같음 (방어).
    if raise_add == 0:
        ev_raise = equity * (pot_f + tc_f) - (1.0 - equity) * tc_f
    else:
        # 상대 콜 시 새 pot 규모 대략: pot + raise_size (내) + raise_size (상대 콜 매칭)
        called_pot = pot_f + 2.0 * float(raise_size)
        # 상대 콜 시 equity 기반 기대 return (contested pot): (2*eq-1) * called_pot
        ev_if_called = (2.0 * equity - 1.0) * called_pot / 2.0
        ev_raise = fe * pot_f + (1.0 - fe) * ev_if_called

    ev_call = equity * (pot_f + tc_f) - (1.0 - equity) * tc_f
    ev_check = 0.0  # to_call == 0 baseline
    ev_fold = 0.0

    choices = {
        "raise": ev_raise,
        "call": ev_call if tc_f > 0 else ev_check,
        "check": ev_check,
        "fold": ev_fold,
    }
    # check 와 fold 구분: to_call 0 면 check, 아니면 fold.
    if tc_f == 0:
        choices.pop("fold", None)
    else:
        choices.pop("check", None)

    # raise 가 stack 을 초과한다면 후보에서 제외 (clamp 은 호출자가 수행).
    if raise_size > my_stack or raise_size <= to_call:
        choices.pop("raise", None)

    best = max(choices, key=lambda k: choices[k])
    return EVResult(
        ev_raise=float(ev_raise),
        ev_call=float(ev_call),
        ev_check=float(ev_check),
        ev_fold=float(ev_fold),
        fe=float(fe),
        choice=best,
    )
