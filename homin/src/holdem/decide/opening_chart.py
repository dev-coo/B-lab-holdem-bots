"""Preflop RFI chart lookup.

근거: configs/open_ranges/rfi_9max.yaml, plan H.3.
저데이터 구간에서 포지션 기반 디폴트 RFI 범위.

사용:
  chart = OpeningChart.from_yaml()
  if chart.in_rfi_range(hand_code, pos_class):
      size_bb = chart.rfi_size_bb(pos_class)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .hand_notation import expand_range

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "open_ranges" / "rfi_9max.yaml"


def _expand_section(data: dict, key: str) -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}
    for pos, spec in data.get(key, {}).items():
        out[pos] = frozenset(expand_range(str(spec)))
    return out


@dataclass(frozen=True)
class OpeningChart:
    ranges: dict[str, frozenset[str]]   # pos_class → hand code set (default = 9-max)
    sizes: dict[str, float]              # pos_class → bb multiplier
    # P-Adapt2: loose-passive 메타 시 사용할 확장 RFI. yaml 의 loose_meta_ranges
    # 키가 없으면 ranges 와 동일.
    loose_meta_ranges: dict[str, frozenset[str]] = None  # type: ignore[assignment]
    # P5-1: 5-max 전용 RFI. n_players ≤ 5 일 때 사용.
    ranges_5max: dict[str, frozenset[str]] = None        # type: ignore[assignment]
    loose_meta_ranges_5max: dict[str, frozenset[str]] = None  # type: ignore[assignment]
    # v5-A: 6-max 전용 RFI. n_players == 6 일 때 사용 (5-max 와 분리).
    ranges_6max: dict[str, frozenset[str]] = None        # type: ignore[assignment]
    loose_meta_ranges_6max: dict[str, frozenset[str]] = None  # type: ignore[assignment]

    @classmethod
    def from_yaml(cls, path: Path = _CONFIG_PATH) -> "OpeningChart":
        with path.open() as f:
            data = yaml.safe_load(f)
        ranges = _expand_section(data, "ranges")
        sizes = {k: float(v) for k, v in data.get("rfi_size_bb", {}).items()}
        loose = _expand_section(data, "loose_meta_ranges")
        # 누락된 pos_class 는 base ranges 로 fallback.
        for pos, base in ranges.items():
            loose.setdefault(pos, base)
        # 5-max 분기 (없으면 9-max 와 동일하게 fallback).
        ranges_5 = _expand_section(data, "ranges_5max") or dict(ranges)
        for pos, base in ranges.items():
            ranges_5.setdefault(pos, base)
        loose_5 = _expand_section(data, "loose_meta_ranges_5max")
        for pos, base in ranges_5.items():
            loose_5.setdefault(pos, base)
        # v5-A: 6-max 분기 (없으면 5-max 와 동일하게 fallback).
        ranges_6 = _expand_section(data, "ranges_6max") or dict(ranges_5)
        for pos, base in ranges_5.items():
            ranges_6.setdefault(pos, base)
        loose_6 = _expand_section(data, "loose_meta_ranges_6max")
        for pos, base in ranges_6.items():
            loose_6.setdefault(pos, base)
        return cls(
            ranges=ranges, sizes=sizes,
            loose_meta_ranges=loose,
            ranges_5max=ranges_5,
            loose_meta_ranges_5max=loose_5,
            ranges_6max=ranges_6,
            loose_meta_ranges_6max=loose_6,
        )

    def _select_ranges(
        self, *, meta_loose: bool, n_players: int | None
    ) -> dict[str, frozenset[str]]:
        # v5-A: 5-max / 6-max chart 분리. 6-max GTO baseline 이 5-max 보다 tight
        # (BTN ~50% vs ~70%), 9-max 보다는 wider. 6p 메타 ITM 회복.
        if n_players is not None and n_players <= 5:
            if meta_loose and self.loose_meta_ranges_5max is not None:
                return self.loose_meta_ranges_5max
            if self.ranges_5max is not None:
                return self.ranges_5max
        if n_players == 6:
            if meta_loose and self.loose_meta_ranges_6max is not None:
                return self.loose_meta_ranges_6max
            if self.ranges_6max is not None:
                return self.ranges_6max
        if meta_loose and self.loose_meta_ranges is not None:
            return self.loose_meta_ranges
        return self.ranges

    def in_rfi_range(
        self,
        hand_code: str,
        pos_class: str,
        *,
        meta_loose: bool = False,
        n_players: int | None = None,
    ) -> bool:
        ranges = self._select_ranges(meta_loose=meta_loose, n_players=n_players)
        r = ranges.get(pos_class)
        return r is not None and hand_code in r

    def rfi_size_bb(self, pos_class: str, default: float = 2.5) -> float:
        return self.sizes.get(pos_class, default)


_DEFAULT_CHART: OpeningChart | None = None


def default_opening_chart() -> OpeningChart:
    global _DEFAULT_CHART
    if _DEFAULT_CHART is None:
        _DEFAULT_CHART = OpeningChart.from_yaml()
    return _DEFAULT_CHART
