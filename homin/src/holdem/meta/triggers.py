"""Escalation triggers 계산 — ActionRequest + 상황에서 LLM 조건 플래그 산출.

근거: configs/llm.yaml escalation_gate, plan D7.

플래그 의미:
  - M_lt_6 — 내 M < 6 (푸시/폴드 경계 이하).
  - near_bubble — 전체 플레이어 중 남은 수가 3 이하이지만 종료 전 (heads-up 제외).
  - stack_gt_100bb_pot_gt_50bb — deep stack 대형 팟 (100BB+ vs 50BB+ pot).
  - multiway_3plus_borderline — 액티브 상대 ≥ 3 + borderline 조건.
  - fold_equity_uncertain — 개인 관측 부족 (n_personal < 20) 으로 상대 반응 불확실.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..math.m_ratio import compute_m
from ..state.profile_store import ProfileStore
from ..transport import protocol as p
from .llm_coordinator import EscalationTriggers


@dataclass(frozen=True)
class TriggerConfig:
    m_short_threshold: float = 6.0
    bubble_remaining_max: int = 3
    deep_stack_bb_min: int = 100
    deep_pot_bb_min: int = 50
    multiway_min_active: int = 3
    uncertain_personal_obs_max: float = 20.0


def count_active_opponents(req: p.ActionRequest, bot_name: str) -> int:
    return sum(1 for pl in req.players
               if pl.status == "active" and pl.name != bot_name and pl.name != "")


def count_remaining(req: p.ActionRequest) -> int:
    """게임에 남아있는 (eliminated 가 아닌) 플레이어 수."""
    return sum(1 for pl in req.players if pl.status != "eliminated")


def build_triggers(
    req: p.ActionRequest,
    bot_name: str,
    profile_store: Optional[ProfileStore] = None,
    cfg: Optional[TriggerConfig] = None,
) -> EscalationTriggers:
    cfg = cfg or TriggerConfig()

    sb = req.blind[0] if len(req.blind) >= 1 else 0
    bb = req.blind[1] if len(req.blind) >= 2 else 0
    m = compute_m(req.my_stack, sb, bb)
    bb_safe = max(1, bb)

    m_lt_6 = m < cfg.m_short_threshold
    remaining = count_remaining(req)
    # near_bubble: heads-up 은 bubble 아님. 3-way 이하 AND M > 1 (plays on).
    near_bubble = (2 < remaining <= cfg.bubble_remaining_max) and m >= 1.0

    stack_bb = req.my_stack / bb_safe
    pot_bb = req.pot / bb_safe
    deep_big_pot = stack_bb >= cfg.deep_stack_bb_min and pot_bb >= cfg.deep_pot_bb_min

    n_active = count_active_opponents(req, bot_name)
    multiway = n_active >= cfg.multiway_min_active

    # fold_equity_uncertain: 활성 상대 중 한 명이라도 관측 부족 → 상대 반응 분포 신뢰 X.
    uncertain = False
    if profile_store is not None:
        for pl in req.players:
            if pl.status != "active" or pl.name == bot_name or not pl.name:
                continue
            prof = profile_store.profiles.get(pl.name)
            n_personal = 0.0 if prof is None else max(
                (c.n_obs for c in prof.metrics.values()), default=0.0
            )
            if n_personal < cfg.uncertain_personal_obs_max:
                uncertain = True
                break
    else:
        uncertain = n_active > 0

    return EscalationTriggers(
        multiway_3plus_borderline=multiway,
        fold_equity_uncertain=uncertain,
        M_lt_6=m_lt_6,
        near_bubble=near_bubble,
        stack_gt_100bb_pot_gt_50bb=deep_big_pot,
    )
