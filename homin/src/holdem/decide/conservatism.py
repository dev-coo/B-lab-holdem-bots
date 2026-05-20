"""ConservatismProfile — plan I.9.b 의 단일 프로파일 엔진.

기능:
  - `load_schedule()` / `load_sizing_grid(name)` 로 yaml 로드.
  - `compute_profile(profile, ...)` 로 n_effective → mode/sizing_grid/bluff_factor 등 주입.

n_effective 정의:
    n_eff = w_personal · n_personal
          + w_class    · n_class     (= profile.hands_seen)
          + w_pop      · n_pop       (population prior ESS ≈ 100, 고정)

cold-start 기본 (profile None): n_eff = 0 + 0 + 0.05*100 = 5 → hard_conservative.
데이터 누적에 따라 bucket 자동 승급.

근거: plan I.1 / I.9 / I.10, configs/conservatism_schedule.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from ..state.player_profile import PlayerProfile

_SCHEDULE_PATH = Path(__file__).resolve().parents[3] / "configs" / "conservatism_schedule.yaml"
_SIZING_PATH = Path(__file__).resolve().parents[3] / "configs" / "sizing.yaml"

# population prior ESS (configs/priors.yaml 의 ESS 기준) — 고정 상수로 취급.
_POP_ESS_DEFAULT = 100.0


@dataclass(frozen=True)
class SizingGrid:
    name: str                                # "conservative" | "balanced" | "exploit"
    value_bet: tuple[float, ...]
    bluff_bet: tuple[float, ...]
    protection: tuple[float, ...]
    raise_open_bb: tuple[float, ...]
    three_bet_multiplier: tuple[float, ...]
    max_bet_to_pot: float
    no_allin_unless: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Bucket:
    name: str
    max_n: float | None                      # None = catchall
    sizing_grid: str
    bluff_factor: float
    lambda_mult: float
    opening_mult: float
    allow_allin: bool


@dataclass(frozen=True)
class ConservatismSchedule:
    w_personal: float
    w_class: float
    w_pop: float
    buckets: tuple[_Bucket, ...]
    tau_class: float
    tau_pop: float
    pop_ess: float = _POP_ESS_DEFAULT

    def effective_n(self, n_personal: float, n_class_hands: float, n_pop: float | None = None) -> float:
        n_pop = self.pop_ess if n_pop is None else n_pop
        return self.w_personal * n_personal + self.w_class * n_class_hands + self.w_pop * n_pop

    def pick_bucket(self, n_eff: float) -> _Bucket:
        for b in self.buckets:
            if b.max_n is None:
                return b
            if n_eff <= b.max_n:
                return b
        return self.buckets[-1]


@dataclass(frozen=True)
class ConservatismProfile:
    mode: str
    sizing_grid: SizingGrid
    bluff_factor: float
    lambda_multiplier: float
    opening_multiplier: float
    allow_allin: bool
    n_effective: float
    n_personal: float = 0.0
    n_class_hands: float = 0.0


def _safe_float(val, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def load_schedule(path: Path = _SCHEDULE_PATH) -> ConservatismSchedule:
    with path.open() as f:
        data = yaml.safe_load(f)

    # weights 는 yaml 에 명시적으로 없으면 plan I.9.b 기본값.
    w = data.get("weights") or {}
    w_personal = _safe_float(w.get("personal"), 1.0)
    w_class = _safe_float(w.get("class_") or w.get("class"), 0.3)
    w_pop = _safe_float(w.get("population"), 0.05)

    mode_params = data.get("mode_params") or {}
    raw_buckets = data.get("schedule") or data.get("buckets") or []
    buckets: list[_Bucket] = []
    for item in raw_buckets:
        name = item.get("mode") or item.get("name")
        if name is None:
            continue
        max_n_raw = item.get("n_max", item.get("max_n"))
        max_n = None if max_n_raw is None else float(max_n_raw)
        params = mode_params.get(name, {})
        sizing_grid = str(params.get("sizing_grid", "balanced"))
        bluff = params.get("bluff_factor", 1.0)
        # "personal_AF_based" 같은 문자열은 1.0 으로 fallback (실제 튜닝은 D5+).
        bluff_f = _safe_float(bluff, 1.0)
        opening = params.get("opening_mult", 1.0)
        opening_f = _safe_float(opening, 1.0)
        buckets.append(_Bucket(
            name=name,
            max_n=max_n,
            sizing_grid=sizing_grid,
            bluff_factor=bluff_f,
            lambda_mult=_safe_float(params.get("lambda_mult"), 1.0),
            opening_mult=opening_f,
            allow_allin=bool(params.get("allow_allin", True)),
        ))

    # sort by max_n ascending, None last
    def _sort_key(b: _Bucket):
        return (b.max_n if b.max_n is not None else float("inf"),)
    buckets.sort(key=_sort_key)

    sh = data.get("shrinkage") or {}
    tau_class = _safe_float(sh.get("tau_class"), 8.0)
    tau_pop = _safe_float(sh.get("tau_population"), 40.0)

    return ConservatismSchedule(
        w_personal=w_personal,
        w_class=w_class,
        w_pop=w_pop,
        buckets=tuple(buckets),
        tau_class=tau_class,
        tau_pop=tau_pop,
    )


@lru_cache(maxsize=3)
def load_sizing_grid(name: str, path: Path = _SIZING_PATH) -> SizingGrid:
    """name ∈ {conservative, balanced, exploit} → SizingGrid."""
    with path.open() as f:
        data = yaml.safe_load(f)
    key = f"{name}_grid"
    block = data.get(key)
    if block is None:
        raise KeyError(f"sizing grid {key!r} not in {path}")
    return SizingGrid(
        name=name,
        value_bet=tuple(float(x) for x in block.get("value_bet", [])),
        bluff_bet=tuple(float(x) for x in block.get("bluff_bet", [])),
        protection=tuple(float(x) for x in block.get("protection", [])),
        raise_open_bb=tuple(float(x) for x in block.get("raise_open_bb", [])),
        three_bet_multiplier=tuple(float(x) for x in block.get("three_bet_multiplier", [])),
        max_bet_to_pot=_safe_float(block.get("max_bet_to_pot"), 1.0),
        no_allin_unless=tuple(block.get("no_allin_unless", [])),
    )


def compute_profile(
    profile: Optional[PlayerProfile],
    schedule: Optional[ConservatismSchedule] = None,
    pop_ess: Optional[float] = None,
) -> ConservatismProfile:
    """PlayerProfile → ConservatismProfile.

    n_personal = profile metrics 중 가장 많이 관측된 metric 의 n_obs (VPIP 가 기준 역할).
    n_class_hands = profile.hands_seen.
    n_pop = pop_ess (기본 100).
    profile=None 이면 0/0/pop_ess → hard_conservative.
    """
    schedule = schedule or load_schedule()
    if profile is None:
        n_personal = 0.0
        n_class_hands = 0.0
    else:
        n_personal = max(
            (c.n_obs for c in profile.metrics.values()),
            default=0.0,
        )
        n_class_hands = float(profile.hands_seen)
    n_eff = schedule.effective_n(n_personal, n_class_hands, n_pop=pop_ess)
    bucket = schedule.pick_bucket(n_eff)
    grid = load_sizing_grid(bucket.sizing_grid)
    return ConservatismProfile(
        mode=bucket.name,
        sizing_grid=grid,
        bluff_factor=bucket.bluff_factor,
        lambda_multiplier=bucket.lambda_mult,
        opening_multiplier=bucket.opening_mult,
        allow_allin=bucket.allow_allin,
        n_effective=n_eff,
        n_personal=n_personal,
        n_class_hands=n_class_hands,
    )
