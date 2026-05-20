"""Information Gain 보너스 — 데이터 수집 유도용 EV 가산치.

근거: plan H.6 — 초기 탐색 시 IG 높은 액션에 소액 프리미엄.
      γ = γ_0 · exp(-n_total / τ), τ ≈ 300 에서 e^-1 감쇠.

단순화:
  - metric-level posterior entropy 차이는 closed-form 로 복잡 → schedule 스칼라 사용.
  - action-type 별 정보 산출량은 heuristic multiplier 로 근사:
      fold = 0 (관측 없음), call ~1.3× (쇼다운 가능), raise ~1.0× (상대 반응 관측),
      check ~0.3× (정보 적음).
  - 최종값에 cap 을 두어 어떤 경우에도 EV 를 "뒤집지 않도록" 안전 장치.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


_ACTION_INFO_WEIGHT: dict[str, float] = {
    "fold": 0.0,
    "check": 0.3,
    "call": 1.3,
    "raise": 1.0,
    "allin": 1.0,
}


@dataclass(frozen=True)
class IGConfig:
    gamma_0: float = 0.02          # BB 단위 — "한 관측의 가치"
    tau: float = 300.0             # 총 관측 수에 대한 감쇠 스케일
    cap_per_action: float = 0.05   # raise/call 한 번에 붙는 최대 보너스
    enable: bool = True


def ig_schedule(n_total_obs: float, cfg: IGConfig | None = None) -> float:
    """총 관측수 n_total → γ · exp(-n/τ). 0 이상."""
    cfg = cfg or IGConfig()
    if not cfg.enable:
        return 0.0
    n = max(0.0, n_total_obs)
    return cfg.gamma_0 * math.exp(-n / cfg.tau)


def action_ig_bonus(
    action: str,
    n_total_obs: float,
    cfg: IGConfig | None = None,
) -> float:
    """액션별 IG 보너스 (BB 단위). cap 적용."""
    cfg = cfg or IGConfig()
    if not cfg.enable:
        return 0.0
    base = ig_schedule(n_total_obs, cfg)
    weight = _ACTION_INFO_WEIGHT.get(action, 0.0)
    return min(cfg.cap_per_action, base * weight)


def apply_ig_to_candidates(
    ev_by_action: dict[str, float],
    n_total_obs: float,
    cfg: IGConfig | None = None,
) -> dict[str, float]:
    """후보 EV dict 에 IG 보너스를 가산한 새 dict 반환."""
    cfg = cfg or IGConfig()
    adjusted: dict[str, float] = {}
    for action, ev in ev_by_action.items():
        adjusted[action] = ev + action_ig_bonus(action, n_total_obs, cfg)
    return adjusted
