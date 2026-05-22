from __future__ import annotations

from collections.abc import Generator

import pytest

from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.builtins.adaptive import Adaptive
from holdem_agent.strategy.builtins.aggressive import Aggressive
from holdem_agent.strategy.builtins.calling_station import CallingStation
from holdem_agent.strategy.builtins.gto_baseline import GTOBaseline
from holdem_agent.strategy.builtins.tight_aggressive import TightAggressive
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.registry import (
    StrategyRegistry,
    _BUILTIN_STRATEGIES,
    get_strategy,
    list_strategies,
    register,
    strategy_exists,
)


@pytest.fixture(autouse=True)
def _reset_builtin_registry() -> Generator[None, None, None]:
    original = dict(_BUILTIN_STRATEGIES)
    try:
        yield
    finally:
        _BUILTIN_STRATEGIES.clear()
        _BUILTIN_STRATEGIES.update(original)


def test_register_builtin() -> None:
    @register
    class MockStrategy(Strategy):
        def decide(self, context: DecisionContext) -> Action:
            return Action(action="check", strategy_name="mock")

        @property
        def genome(self) -> StrategyGenome:
            return StrategyGenome()

        @classmethod
        def from_genome(cls, genome: StrategyGenome) -> "MockStrategy":
            return cls()

        @property
        def name(self) -> str:
            return "mock-strategy"

    assert "mock-strategy" in list_strategies()


def test_get_strategy_calling_station() -> None:
    strategy = get_strategy("calling-station")

    assert isinstance(strategy, CallingStation)


def test_get_strategy_gto() -> None:
    strategy = get_strategy("gto-baseline")

    assert isinstance(strategy, GTOBaseline)


def test_get_strategy_tag() -> None:
    strategy = get_strategy("tight-aggressive")

    assert isinstance(strategy, TightAggressive)


def test_get_strategy_aggressive() -> None:
    strategy = get_strategy("aggressive")

    assert isinstance(strategy, Aggressive)


def test_get_strategy_adaptive() -> None:
    strategy = get_strategy("adaptive")

    assert isinstance(strategy, Adaptive)


def test_get_strategy_unknown() -> None:
    with pytest.raises(KeyError, match="Unknown strategy: does-not-exist"):
        get_strategy("does-not-exist")


def test_strategy_exists_true() -> None:
    assert strategy_exists("calling-station")


def test_strategy_exists_false() -> None:
    assert strategy_exists("missing-strategy") is False


def test_list_strategies() -> None:
    strategies = list_strategies()

    assert "calling-station" in strategies
    assert "gto-baseline" in strategies
    assert "tight-aggressive" in strategies
    assert "aggressive" in strategies
    assert "adaptive" in strategies


def test_registry_register_version() -> None:
    registry = StrategyRegistry()
    genome = StrategyGenome(
        preflop_raise_threshold={"btn": 0.3, "sb": 0.2, "bb": 0.2, "utg": 0.4, "co": 0.5}
    )

    registry.register_version("test-strategy", 1, genome)
    entry = registry.get_version("test-strategy", 1)

    assert entry is not None
    assert entry["version"] == 1
    assert entry["genome"] == genome.to_dict()
    assert entry["origin"] == "manual"


def test_registry_get_latest() -> None:
    registry = StrategyRegistry()
    first = StrategyGenome(cbet_frequency=0.2)
    second = StrategyGenome(cbet_frequency=0.9)

    registry.register_version("test-strategy", 1, first)
    registry.register_version("test-strategy", 2, second)

    latest = registry.get_latest_version("test-strategy")

    assert latest is not None
    assert latest["version"] == 2
    assert latest["genome"] == second.to_dict()


def test_registry_get_genome() -> None:
    registry = StrategyRegistry()
    genome = StrategyGenome(bluff_frequency=0.11)

    registry.register_version("test-strategy", 1, genome)

    assert registry.get_genome("test-strategy", 1) == genome


def test_registry_list_versions() -> None:
    registry = StrategyRegistry()
    first = StrategyGenome(adapt_speed=0.2)
    second = StrategyGenome(adapt_speed=0.25)

    registry.register_version("multi", 1, first)
    registry.register_version("multi", 2, second)

    versions = registry.list_versions("multi")

    assert [v["version"] for v in versions] == [1, 2]


def test_registry_list_registered() -> None:
    registry = StrategyRegistry()

    registry.register_version("strategy-a", 1, StrategyGenome())
    registry.register_version("strategy-b", 1, StrategyGenome())

    assert registry.list_registered() == ["strategy-a", "strategy-b"]
