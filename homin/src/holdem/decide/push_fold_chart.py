"""Push/Fold 차트 로더 + (M, pos, hand) → 액션 결정.

YAML 포맷: `configs/nash_charts/simple_push_9max.yaml` 참조.

사용 모드:
  - mode=push_fold: jam_ranges 또는 call_vs_jam_ranges (facing raise/allin 여부).
  - mode=hybrid: hybrid_open_ranges (opening) 또는 call_vs_jam_ranges (facing raise).

Bucket 매칭 규칙:
  sorted(buckets by max_M ascending) → 조건 `m <= max_M` 인 첫 bucket 선택.
  max_M=null 은 최상위 catch-all.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from .hand_notation import expand_range

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "nash_charts" / "simple_push_9max.yaml"
)
_HU_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "nash_charts" / "heads_up.yaml"
)

PositionClass = Literal["EP", "MP", "LP", "BLIND"]
RangeKind = Literal["jam", "hybrid_open", "call_vs_jam", "hu_jam", "hu_call", "hu_open"]


@dataclass(frozen=True)
class Bucket:
    max_M: float   # inf 로 null 처리
    ranges: dict[str, frozenset[str]]   # position_class or "any" → hand set

    def lookup(self, hand: str, pos_class: str) -> bool:
        hands = self.ranges.get(pos_class)
        if hands is not None and hand in hands:
            return True
        any_ = self.ranges.get("any")
        if any_ is not None and hand in any_:
            return True
        return False


@dataclass(frozen=True)
class PushFoldChart:
    jam: list[Bucket]
    hybrid_open: list[Bucket]
    call_vs_jam: list[Bucket]
    hu_jam: list[Bucket]
    hu_call: list[Bucket]
    hu_open: list[Bucket]   # P5-3: deep stack HU first-in raise range.

    @classmethod
    def from_yaml(
        cls,
        path: Path = _CONFIG_PATH,
        hu_path: Path | None = _HU_CONFIG_PATH,
    ) -> "PushFoldChart":
        with path.open() as f:
            data = yaml.safe_load(f)
        hu_data: dict = {}
        if hu_path is not None and Path(hu_path).exists():
            with Path(hu_path).open() as f:
                hu_data = yaml.safe_load(f) or {}
        return cls(
            jam=_load_buckets(data.get("jam_ranges", [])),
            hybrid_open=_load_buckets(data.get("hybrid_open_ranges", [])),
            call_vs_jam=_load_buckets(data.get("call_vs_jam_ranges", [])),
            hu_jam=_load_buckets(hu_data.get("hu_jam_ranges", [])),
            hu_call=_load_buckets(hu_data.get("hu_call_ranges", [])),
            hu_open=_load_buckets(hu_data.get("hu_open_ranges", [])),
        )

    def pick(self, kind: RangeKind, m: float) -> Bucket | None:
        buckets = {
            "jam": self.jam,
            "hybrid_open": self.hybrid_open,
            "call_vs_jam": self.call_vs_jam,
            "hu_jam": self.hu_jam,
            "hu_call": self.hu_call,
            "hu_open": self.hu_open,
        }[kind]
        for b in buckets:
            if m <= b.max_M:
                return b
        return None


def _load_buckets(rows: list[dict]) -> list[Bucket]:
    parsed: list[Bucket] = []
    for row in rows:
        raw_max = row.get("max_M")
        max_m = float("inf") if raw_max is None else float(raw_max)
        ranges: dict[str, frozenset[str]] = {}
        for key, spec in row.items():
            if key == "max_M":
                continue
            ranges[key] = frozenset(expand_range(str(spec)))
        parsed.append(Bucket(max_M=max_m, ranges=ranges))
    parsed.sort(key=lambda b: b.max_M)
    return parsed


_DEFAULT_CHART: PushFoldChart | None = None


def default_chart() -> PushFoldChart:
    global _DEFAULT_CHART
    if _DEFAULT_CHART is None:
        _DEFAULT_CHART = PushFoldChart.from_yaml()
    return _DEFAULT_CHART
