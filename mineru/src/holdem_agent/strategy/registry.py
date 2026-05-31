from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from holdem_agent.strategy.base import Strategy
from holdem_agent.strategy.genome import StrategyGenome

logger = logging.getLogger(__name__)

# Built-in strategy registry
_BUILTIN_STRATEGIES: dict[str, type[Strategy]] = {}


def _register_builtin(name: str, cls: type[Strategy]) -> None:
    _BUILTIN_STRATEGIES[name] = cls


def register(cls: type[Strategy]) -> type[Strategy]:
    """Decorator to register a strategy class."""
    instance = cls()
    _register_builtin(instance.name, cls)
    return cls


def get_strategy(name: str, genome: StrategyGenome | None = None) -> Strategy:
    """Get a strategy by name with optional genome."""
    if name in _BUILTIN_STRATEGIES:
        cls = _BUILTIN_STRATEGIES[name]
        if genome is not None:
            return cls.from_genome(genome)
        return cls()
    raise KeyError(f"Unknown strategy: {name}")


def list_strategies() -> list[str]:
    """List all registered strategy names."""
    return sorted(_BUILTIN_STRATEGIES.keys())


def strategy_exists(name: str) -> bool:
    """Check if a strategy is registered."""
    return name in _BUILTIN_STRATEGIES


class StrategyRegistry:
    """Manages strategy versions with optional file persistence."""

    def __init__(self, data_dir: str | Path = "data/strategies") -> None:
        self._data_dir = Path(data_dir)
        self._versions: dict[str, list[dict[str, Any]]] = {}  # name → list of version dicts

    def register_version(
        self,
        name: str,
        version: int,
        genome: StrategyGenome,
        origin: str = "manual",
        parent_name: str | None = None,
        parent_version: int | None = None,
    ) -> None:
        """Register a new strategy version."""
        entry = {
            "name": name,
            "version": version,
            "genome": genome.to_dict(),
            "origin": origin,
            "parent_name": parent_name,
            "parent_version": parent_version,
        }
        if name not in self._versions:
            self._versions[name] = []
        self._versions[name].append(entry)

    def get_latest_version(self, name: str) -> dict[str, Any] | None:
        """Get the latest version entry for a strategy."""
        versions = self._versions.get(name, [])
        return versions[-1] if versions else None

    def get_version(self, name: str, version: int) -> dict[str, Any] | None:
        """Get a specific version."""
        for v in self._versions.get(name, []):
            if v["version"] == version:
                return v
        return None

    def get_genome(self, name: str, version: int | None = None) -> StrategyGenome | None:
        """Get genome for a strategy version."""
        if version is not None:
            entry = self.get_version(name, version)
        else:
            entry = self.get_latest_version(name)

        if entry and "genome" in entry:
            return StrategyGenome.from_dict(entry["genome"])
        return None

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """List all versions of a strategy."""
        return list(self._versions.get(name, []))

    def list_registered(self) -> list[str]:
        """List all strategy names with versions."""
        return sorted(self._versions.keys())

    def save_to_file(self, name: str) -> None:
        """Persist strategy versions to JSON file."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        versions = self._versions.get(name, [])
        path = self._data_dir / f"{name}.json"
        path.write_text(json.dumps(versions, indent=2))

    def load_from_file(self, name: str) -> bool:
        """Load strategy versions from JSON file."""
        path = self._data_dir / f"{name}.json"
        if not path.exists():
            return False
        versions = cast(list[dict[str, Any]], json.loads(path.read_text()))
        self._versions[name] = versions
        return True


# Auto-register built-in strategies on import
def _auto_register() -> None:
    try:
        from holdem_agent.strategy.builtins.calling_station import CallingStation

        _register_builtin("calling-station", CallingStation)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.gto_baseline import GTOBaseline

        _register_builtin("gto-baseline", GTOBaseline)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.tight_aggressive import TightAggressive

        _register_builtin("tight-aggressive", TightAggressive)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.hybrid_gto import HybridGTO

        _register_builtin("hybrid-gto", HybridGTO)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.omni import OmniStrategy

        _register_builtin("omni", OmniStrategy)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.aggressive import Aggressive

        _register_builtin("aggressive", Aggressive)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.adaptive import Adaptive

        _register_builtin("adaptive", Adaptive)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.practical import PRACTICAL_STRATEGIES

        for strategy_cls in PRACTICAL_STRATEGIES:
            _register_builtin(strategy_cls().name, strategy_cls)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.dominance import DOMINANCE_STRATEGIES

        for strategy_cls in DOMINANCE_STRATEGIES:
            _register_builtin(strategy_cls().name, strategy_cls)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.statistical import STATISTICAL_STRATEGIES

        for strategy_cls in STATISTICAL_STRATEGIES:
            _register_builtin(strategy_cls().name, strategy_cls)
    except ImportError:
        pass
    try:
        from holdem_agent.strategy.builtins.arena import ARENA_STRATEGIES

        for strategy_cls in ARENA_STRATEGIES:
            _register_builtin(strategy_cls().name, strategy_cls)
    except ImportError:
        pass


_auto_register()
