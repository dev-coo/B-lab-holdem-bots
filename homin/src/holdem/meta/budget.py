"""LLM 호출 예산 카운터 — per-hand / per-game / per-minute / per-day.

근거: configs/llm.yaml budget, plan D7.

사용:
    tracker = BudgetTracker.from_yaml()
    if tracker.allow_call():
        tracker.record_call(hand_number, room_id)
        ...

핸드 종료 시 `on_hand_end(hand_number)` 호출로 per-hand 카운터 리셋.
game 종료 시 `on_game_end(room_id)` 호출로 per-game 카운터 리셋.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "llm.yaml"


@dataclass(frozen=True)
class BudgetLimits:
    per_hand: int = 1
    per_game: int = 20
    per_minute: int = 10
    per_day: int = 5000


@dataclass
class BudgetTracker:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    # 카운터
    hand_counters: dict[tuple[int, int], int] = field(default_factory=dict)  # (room, hand) → count
    game_counters: dict[int, int] = field(default_factory=dict)              # room → count
    minute_window: list[float] = field(default_factory=list)                 # timestamps (sec)
    day_count: int = 0
    day_started: float = field(default_factory=time.time)

    @classmethod
    def from_yaml(cls, path: Path = _CONFIG_PATH) -> "BudgetTracker":
        with path.open() as f:
            data = yaml.safe_load(f)
        b = data.get("budget") or {}
        limits = BudgetLimits(
            per_hand=int(b.get("per_hand_max_calls", 1)),
            per_game=int(b.get("per_game_max_calls", 20)),
            per_minute=int(b.get("per_minute_max_calls", 10)),
            per_day=int(b.get("per_day_max_calls", 5000)),
        )
        return cls(limits=limits)

    def _prune_minute_window(self, now: float) -> None:
        cutoff = now - 60.0
        self.minute_window[:] = [t for t in self.minute_window if t >= cutoff]

    def _maybe_reset_day(self, now: float) -> None:
        # 86400 초 경과시 day counter reset.
        if now - self.day_started >= 86400.0:
            self.day_count = 0
            self.day_started = now

    def allow_call(self, room_id: int | None = None, hand_number: int | None = None,
                   now: float | None = None) -> tuple[bool, str]:
        """LLM 호출 허용 여부 + 거부 사유.

        Returns (ok, reason). ok=True 면 reason="ok".
        """
        now = now if now is not None else time.time()
        self._maybe_reset_day(now)
        self._prune_minute_window(now)

        if self.day_count >= self.limits.per_day:
            return False, "budget_day"
        if len(self.minute_window) >= self.limits.per_minute:
            return False, "budget_minute"
        if room_id is not None and self.game_counters.get(room_id, 0) >= self.limits.per_game:
            return False, "budget_game"
        if room_id is not None and hand_number is not None:
            key = (room_id, hand_number)
            if self.hand_counters.get(key, 0) >= self.limits.per_hand:
                return False, "budget_hand"
        return True, "ok"

    def record_call(self, room_id: int | None = None, hand_number: int | None = None,
                    now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.day_count += 1
        self.minute_window.append(now)
        if room_id is not None:
            self.game_counters[room_id] = self.game_counters.get(room_id, 0) + 1
            if hand_number is not None:
                key = (room_id, hand_number)
                self.hand_counters[key] = self.hand_counters.get(key, 0) + 1

    def on_hand_end(self, room_id: int, hand_number: int) -> None:
        self.hand_counters.pop((room_id, hand_number), None)

    def on_game_end(self, room_id: int) -> None:
        self.game_counters.pop(room_id, None)
        # hand counters of this room also cleared
        self.hand_counters = {k: v for k, v in self.hand_counters.items() if k[0] != room_id}
