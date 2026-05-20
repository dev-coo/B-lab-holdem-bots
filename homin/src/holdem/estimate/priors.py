"""configs/priors.yaml + configs/class_priors.yaml → BetaCounter 변환.

로딩 시점에 한 번만 파싱, 이후 read-only.
서버 규칙(플레이어 수 2~9) 에 따라 4/6/9-max server_prior 중 선택.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ..state.player_profile import BetaCounter

_PRIORS_PATH = Path(__file__).resolve().parents[3] / "configs" / "priors.yaml"
_CLASS_PRIORS_PATH = Path(__file__).resolve().parents[3] / "configs" / "class_priors.yaml"


@dataclass(frozen=True)
class ShrinkageHyperparams:
    tau_class: float = 8.0
    tau_population: float = 40.0


@dataclass(frozen=True)
class PopulationPriors:
    """인원수 별 server_prior metrics. n_players → {metric → BetaCounter}."""
    by_players: dict[int, dict[str, BetaCounter]]
    shrinkage: ShrinkageHyperparams

    def for_players(self, n_players: int) -> dict[str, BetaCounter]:
        # 가장 가까운 하위 키.
        candidates = sorted(self.by_players.keys())
        chosen = candidates[0]
        for k in candidates:
            if k <= n_players:
                chosen = k
        return self.by_players[chosen]


@dataclass(frozen=True)
class ClassPriors:
    """class_name → {metric → BetaCounter} + centroid(VPIP, AF)."""
    priors: dict[str, dict[str, BetaCounter]]
    centroids: dict[str, dict[str, float]]
    boundaries: dict[str, float]


def _to_beta(block: dict) -> BetaCounter:
    return BetaCounter(alpha=float(block["alpha"]), beta=float(block["beta"]))


@lru_cache(maxsize=1)
def load_population_priors(path: Path = _PRIORS_PATH) -> PopulationPriors:
    with path.open() as f:
        data = yaml.safe_load(f)

    by_players: dict[int, dict[str, BetaCounter]] = {}
    # priors.yaml 의 server_prior_{N}max 블록과 application.select_by_players 매핑 사용
    prior_sets = {
        "server_prior_4max": data["server_prior_4max"],
        "server_prior_6max": data["server_prior_6max"],
        "server_prior_9max": data["server_prior_9max"],
    }
    select = data["application"]["select_by_players"]
    for n_players, set_name in select.items():
        block = prior_sets[set_name]
        by_players[int(n_players)] = {k: _to_beta(v) for k, v in block.items()}

    sh = data.get("shrinkage", {})
    hp = ShrinkageHyperparams(
        tau_class=float(sh.get("tau_class", 8)),
        tau_population=float(sh.get("tau_population", 40)),
    )
    return PopulationPriors(by_players=by_players, shrinkage=hp)


@lru_cache(maxsize=1)
def load_class_priors(path: Path = _CLASS_PRIORS_PATH) -> ClassPriors:
    with path.open() as f:
        data = yaml.safe_load(f)

    priors: dict[str, dict[str, BetaCounter]] = {}
    centroids: dict[str, dict[str, float]] = {}
    for cls, block in data["server_class_priors"].items():
        metrics = {}
        for metric, params in block.items():
            if isinstance(params, dict) and "alpha" in params:
                metrics[metric] = _to_beta(params)
        priors[cls] = metrics
        centroids[cls] = {
            "VPIP": metrics["VPIP"].rate(default=0.5) if "VPIP" in metrics else 0.25,
            "AF_target_mean": float(block.get("af_target_mean", 1.5)),
        }

    bounds = data.get("boundaries", {})
    boundaries = {
        "tight_vpip_max": float(bounds.get("tight_vpip_max", 0.30)),
        "loose_vpip_min": float(bounds.get("loose_vpip_min", 0.45)),
        "passive_af_max": float(bounds.get("passive_af_max", 1.5)),
        "aggressive_af_min": float(bounds.get("aggressive_af_min", 2.0)),
    }
    return ClassPriors(priors=priors, centroids=centroids, boundaries=boundaries)
