from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from holdem_agent.models.state import ActionRecord

_VPIP_ACTIONS = {"call", "raise", "bet", "allin"}
_PFR_ACTIONS = {"raise", "bet", "allin"}


@dataclasses.dataclass(frozen=True)
class SelfImageAnalysis:
    """Table image inferred from our own action history."""

    hands_observed: int
    vpip_count: int
    pfr_count: int
    vpip: float
    pfr: float
    image: str
    bluff_success_bonus: float
    value_size_multiplier: float


def analyze_self_image(
    action_history: list[ActionRecord],
    hero_names: Iterable[str] | None = None,
) -> SelfImageAnalysis:
    """Estimate our table image from own VPIP/PFR actions.

    Tight images get more bluff credit; loose images should value bet larger.
    """

    hero_name_set = set(hero_names or ())
    hero_actions = [action for action in action_history if not hero_name_set or action.player in hero_name_set]
    preflop_actions = [action for action in hero_actions if action.phase == "preflop"]
    hands_observed = max(1, len(preflop_actions))
    vpip_count = sum(1 for action in preflop_actions if action.action in _VPIP_ACTIONS)
    pfr_count = sum(1 for action in preflop_actions if action.action in _PFR_ACTIONS)
    vpip = vpip_count / hands_observed
    pfr = pfr_count / hands_observed
    image = _classify(vpip, pfr, len(preflop_actions))

    return SelfImageAnalysis(
        hands_observed=hands_observed,
        vpip_count=vpip_count,
        pfr_count=pfr_count,
        vpip=vpip,
        pfr=pfr,
        image=image,
        bluff_success_bonus=_bluff_success_bonus(image),
        value_size_multiplier=_value_size_multiplier(image),
    )


def _classify(vpip: float, pfr: float, action_count: int) -> str:
    if action_count == 0:
        return "neutral"
    if vpip <= 0.25 and pfr <= 0.18:
        return "tight"
    if vpip >= 0.45 or pfr >= 0.35:
        return "loose"
    return "balanced"


def _bluff_success_bonus(image: str) -> float:
    if image == "tight":
        return 0.08
    if image == "loose":
        return -0.04
    return 0.0


def _value_size_multiplier(image: str) -> float:
    if image == "loose":
        return 1.15
    if image == "tight":
        return 0.95
    return 1.0
