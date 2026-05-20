"""4-class 소프트 typing — NIT / TAG / LAG / Fish.

근거: plan H.1.c, configs/class_priors.yaml (centroid + boundaries).

알고리즘:
  - 각 클래스의 centroid (VPIP, AF_target_mean) 대비 거리 → softmax.
  - 거리 metric: log-scaled AF 차이 + VPIP 차이 (스케일 정규화).
  - 관측 부족 (n < min_obs) 이면 균등 사전 반환.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..state.player_profile import PlayerProfile
from .priors import ClassPriors, load_class_priors

CLASSES = ("NIT", "TAG", "LAG", "Fish")


@dataclass(frozen=True)
class TypingConfig:
    min_hands_for_typing: int = 20
    temperature: float = 0.05     # softmax sharpness
    vpip_scale: float = 1.0        # VPIP 차이 정규화 (이미 0~1)
    af_log_scale: float = 1.0      # log-AF 차이 정규화 (typical log-range ~2.0)


def _distance(vpip: float, af: float, centroid: dict[str, float], cfg: TypingConfig) -> float:
    dv = (vpip - centroid["VPIP"]) / cfg.vpip_scale
    af_safe = max(0.1, af)
    af_c = max(0.1, centroid["AF_target_mean"])
    da = (math.log(af_safe) - math.log(af_c)) / cfg.af_log_scale
    return dv * dv + da * da


def soft_assign(
    profile: PlayerProfile,
    class_priors: ClassPriors | None = None,
    cfg: TypingConfig | None = None,
) -> dict[str, float]:
    """플레이어 → {class_name: probability}. 합 1.0."""
    class_priors = class_priors or load_class_priors()
    cfg = cfg or TypingConfig()

    # 최소 관측 부족 시 균등
    if profile.hands_seen < cfg.min_hands_for_typing or profile.aggression.n_obs <= 0:
        return {c: 0.25 for c in CLASSES}

    vpip = profile.vpip()
    af = profile.af()

    # 거리 → 음수화 → softmax
    dists = {c: _distance(vpip, af, class_priors.centroids[c], cfg) for c in CLASSES}
    min_d = min(dists.values())
    # softmax with temperature
    unnorm = {c: math.exp(-(d - min_d) / cfg.temperature) for c, d in dists.items()}
    total = sum(unnorm.values())
    if total <= 0:
        return {c: 0.25 for c in CLASSES}
    return {c: v / total for c, v in unnorm.items()}


def hard_assign(
    profile: PlayerProfile,
    class_priors: ClassPriors | None = None,
) -> str:
    """soft assignment 의 argmax. typing 확률 분포에서 최빈 class."""
    probs = soft_assign(profile, class_priors=class_priors)
    return max(probs.items(), key=lambda kv: kv[1])[0]
