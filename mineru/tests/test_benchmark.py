from __future__ import annotations

import json
from pathlib import Path

import pytest

from holdem_agent.benchmark import evaluate_strategies


PRACTICAL_STRATEGY_SLUGS = [
    "positional-pressure",
    "short-stack-push-fold",
    "squeeze-aggressor",
    "pot-odds-grinder",
    "draw-semi-bluff-pressure",
    "value-heavy-station-punisher",
    "anti-maniac-trapper",
    "blind-defense-resteal",
    "bankroll-preserver",
    "meta-adaptive-blend",
]


def test_evaluate_strategies_runs_100_deterministic_scenarios_and_writes_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.58,
    )

    first = evaluate_strategies(
        PRACTICAL_STRATEGY_SLUGS,
        games_per_strategy=100,
        seed=1234,
        artifact_dir=tmp_path,
    )
    second = evaluate_strategies(
        PRACTICAL_STRATEGY_SLUGS,
        games_per_strategy=100,
        seed=1234,
        artifact_dir=None,
    )

    assert first["pass"] is True
    assert isinstance(first["score"], float)
    assert first["games_per_strategy"] == 100
    assert len(first["results"]) == len(PRACTICAL_STRATEGY_SLUGS)
    assert [result["strategy"] for result in first["results"]] == PRACTICAL_STRATEGY_SLUGS
    assert all(result["games"] == 100 for result in first["results"])
    assert all(isinstance(result["score"], float) for result in first["results"])
    assert all(result["pass"] is True for result in first["results"])

    assert first["score"] == second["score"]
    assert first["results"] == second["results"]

    artifact_path = Path(str(first["artifact_path"]))
    assert artifact_path == tmp_path / "iteration-seed-1234.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["pass"] is True
    assert artifact["results"] == first["results"]


def test_evaluate_strategies_enforces_minimum_game_count() -> None:
    with pytest.raises(ValueError, match="games_per_strategy must be at least 100"):
        evaluate_strategies(["positional-pressure"], games_per_strategy=99, artifact_dir=None)
