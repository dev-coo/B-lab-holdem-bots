"""Opponent metric lookup — 개인 posterior + class prior + pop prior shrinkage 를
한 번의 호출로 계산.

사용:
    rate = posterior_rate(profile, metric="CBET", n_players=9)
    # → shrunk alpha/(alpha+beta) (personal + weighted class + weighted pop)

설계:
  - ``profile`` 이 없으면 (n_obs=0) population + class(soft_assign) 만으로 계산.
  - class soft assignment 는 class_typer 에 위임. 충분한 hands 없으면 균등 (0.25×4).
  - 반환 타입은 ``PosteriorSummary`` (rate + ESS + components) 로 디버깅 용이.

plan H.1 / D3 Day 19.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..state.player_profile import BetaCounter, PlayerProfile
from .class_typer import CLASSES, soft_assign
from .priors import (
    ClassPriors,
    PopulationPriors,
    load_class_priors,
    load_population_priors,
)
from .shrinkage import shrink, soft_class_prior


@dataclass(frozen=True)
class PosteriorSummary:
    rate: float
    ess: float               # effective sample size (alpha + beta)
    n_personal: float
    class_weights: dict[str, float]

    @property
    def is_data_rich(self) -> bool:
        return self.n_personal >= 30


def posterior_rate(
    profile: Optional[PlayerProfile],
    metric: str,
    n_players: int = 9,
    default: float = 0.5,
    population: Optional[PopulationPriors] = None,
    class_priors: Optional[ClassPriors] = None,
) -> PosteriorSummary:
    """3-layer shrinkage 결과의 rate + ESS + class_weights 요약."""
    population = population or load_population_priors()
    class_priors = class_priors or load_class_priors()

    pop_block = population.for_players(n_players)
    pop_metric = pop_block.get(metric) or BetaCounter()

    # class 별 prior
    class_metric_map: dict[str, BetaCounter] = {}
    for cls in CLASSES:
        cls_block = class_priors.priors.get(cls, {})
        class_metric_map[cls] = cls_block.get(metric) or BetaCounter()

    if profile is None:
        weights = {c: 0.25 for c in CLASSES}
        personal = BetaCounter()
    else:
        weights = soft_assign(profile, class_priors=class_priors)
        personal = profile.metrics.get(metric) or BetaCounter()

    class_mixed = soft_class_prior(class_metric_map, weights)
    eff = shrink(personal, class_mixed, pop_metric, population.shrinkage)
    rate = eff.rate(default=default)
    return PosteriorSummary(
        rate=rate,
        ess=eff.n_obs,
        n_personal=personal.n_obs,
        class_weights=weights,
    )


def opponent_rate(
    store,                               # ProfileStore | None
    name: str,
    metric: str,
    n_players: int = 9,
    default: float = 0.5,
) -> float:
    """ProfileStore + name → shrunk rate. Store 없거나 없는 이름이면 default 가 아닌
    class-uniform + population 기반 rate."""
    profile = None
    if store is not None:
        profile = store.profiles.get(name)
    summary = posterior_rate(profile, metric=metric, n_players=n_players, default=default)
    return summary.rate
