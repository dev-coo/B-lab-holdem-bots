"""좌석(seat) → 4-class (EP/MP/LP/BLIND) 매핑.

근거: configs/position_class_map.yaml (BOT_GUIDE §4).
인원(2~9) 에 따라 동일 seat 이 다른 class 에 속함.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "position_class_map.yaml"

PositionClass = Literal["EP", "MP", "LP", "BLIND"]


class PositionMap:
    def __init__(self, data: dict):
        self._by_count: dict[int, dict[str, str]] = {
            int(k): v for k, v in data["positions_by_player_count"].items()
        }

    @classmethod
    def from_yaml(cls, path: Path = _CONFIG_PATH) -> "PositionMap":
        with path.open() as f:
            return cls(yaml.safe_load(f))

    def classify(self, seat: str, n_players: int) -> PositionClass:
        """좌석 이름 + 인원수 → 4-class. 알 수 없으면 BLIND 로 안전 처리."""
        table = self._by_count.get(n_players)
        if table is None:
            # 가장 가까운 등록된 인원수 선택
            candidates = [c for c in self._by_count if c <= n_players]
            if not candidates:
                return "BLIND"
            table = self._by_count[max(candidates)]
        cls = table.get(seat, "BLIND")
        if cls not in ("EP", "MP", "LP", "BLIND"):
            return "BLIND"
        return cls  # type: ignore[return-value]


_DEFAULT_MAP: PositionMap | None = None


def default_map() -> PositionMap:
    global _DEFAULT_MAP
    if _DEFAULT_MAP is None:
        _DEFAULT_MAP = PositionMap.from_yaml()
    return _DEFAULT_MAP
