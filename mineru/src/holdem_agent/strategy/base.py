from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod

from holdem_agent.models.state import ActionRecord, BlindLevel, PlayerState
from holdem_agent.strategy.genome import StrategyGenome


@dataclasses.dataclass(frozen=True)
class DecisionContext:
    """Immutable game state snapshot passed to strategy."""

    hand_number: int
    hole_cards: list[str]
    community_cards: list[str]
    phase: str
    pot: int
    my_stack: int
    my_seat: str
    to_call: int
    min_raise: int
    blind: tuple[int, int]
    players: list[PlayerState]
    action_history: list[ActionRecord]
    blind_structure: list[BlindLevel]
    starting_stack: int
    room_id: int


@dataclasses.dataclass(frozen=True)
class Action:
    """A poker action decision."""

    action: str
    amount: int | None = None
    reasoning: str = ""
    strategy_name: str = ""


def safe_fallback(context: DecisionContext) -> Action:
    """Return a safe default action based on call obligation."""

    if context.to_call == 0:
        return Action(action="check")
    return Action(action="fold")


class Strategy(ABC):
    """Base class for all strategies. Strategy = (game_state) -> action function."""

    @abstractmethod
    def decide(self, context: DecisionContext) -> Action:
        """Decide action given current game state.

        Requirements:
        - Must return within 5 seconds (28s hard limit)
        - No I/O operations
        - On exception, safe_fallback is used by the harness
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def genome(self) -> StrategyGenome:
        """Serialize strategy to parameter vector for evolution."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_genome(cls, genome: StrategyGenome) -> "Strategy":
        """Restore strategy from parameter vector."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier (e.g. 'gto-aggressive-v1.2')."""
        raise NotImplementedError
