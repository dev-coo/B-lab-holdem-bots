"""게임 모드 선택기 — M 값 기반.

근거: plan A1 (모드 스위치), `configs/blind_schedule.yaml` 의 mode_thresholds.

Modes:
    push_fold: M ≤ 8       — Nash 차트 순수 lookup
    hybrid:    8 < M ≤ 15  — open = min raise, 3bet 이후 jam 차트
    mid:       15 < M ≤ 30 — 개인 Bayesian 비중↑, EV tree 얕음
    deep:      M > 30      — 원 계획 L3/L4 풀 가동
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Mode = Literal["push_fold", "hybrid", "mid", "deep"]

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "blind_schedule.yaml"


@dataclass(frozen=True)
class ModeThresholds:
    push_fold_max: float
    hybrid_max: float
    mid_max: float

    @classmethod
    def from_yaml(cls, path: Path = _CONFIG_PATH) -> "ModeThresholds":
        with path.open() as f:
            data = yaml.safe_load(f)
        t = data["mode_thresholds"]
        return cls(
            push_fold_max=float(t["push_fold"]["max_M"]),
            hybrid_max=float(t["hybrid"]["max_M"]),
            mid_max=float(t["mid"]["max_M"]),
        )


_DEFAULT_THRESHOLDS: ModeThresholds | None = None


def _defaults() -> ModeThresholds:
    global _DEFAULT_THRESHOLDS
    if _DEFAULT_THRESHOLDS is None:
        _DEFAULT_THRESHOLDS = ModeThresholds.from_yaml()
    return _DEFAULT_THRESHOLDS


def select_mode(m: float, thresholds: ModeThresholds | None = None) -> Mode:
    t = thresholds or _defaults()
    if m <= t.push_fold_max:
        return "push_fold"
    if m <= t.hybrid_max:
        return "hybrid"
    if m <= t.mid_max:
        return "mid"
    return "deep"
