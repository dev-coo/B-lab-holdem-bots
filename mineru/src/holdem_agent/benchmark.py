from __future__ import annotations

import dataclasses
import json
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from holdem_agent.models.state import ActionRecord, BlindLevel, PlayerState
from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.registry import get_strategy, list_strategies


MINIMUM_GAMES_PER_EVALUATION = 100
DEFAULT_AUTORESEARCH_DIR = Path(
    ".omc/autoresearch/holdem-practical-strategy-search/runs/"
    "2026-05-01-strategy-iteration/evaluations"
)
LEGAL_ACTIONS = {"fold", "check", "call", "raise", "allin"}
INVALID_ACTION_PENALTY = 20.0


@dataclasses.dataclass(frozen=True)
class BenchmarkScenario:
    """One local decision-quality benchmark spot, not a full poker game engine."""

    scenario_id: str
    context: DecisionContext
    action_scores: Mapping[str, float]
    description: str


@dataclasses.dataclass(frozen=True)
class StrategyBenchmarkResult:
    strategy: str
    games: int
    pass_: bool
    score: float
    mean_bb_per_100: float
    standard_error: float
    invalid_actions: int
    action_counts: Mapping[str, int]

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "games": self.games,
            "pass": self.pass_,
            "score": self.score,
            "mean_bb_per_100": self.mean_bb_per_100,
            "standard_error": self.standard_error,
            "invalid_actions": self.invalid_actions,
            "action_counts": dict(self.action_counts),
        }


def evaluate_strategies(
    strategy_names: Sequence[str] | None = None,
    *,
    games_per_strategy: int = 100,
    seed: int = 20260501,
    artifact_dir: Path | None = DEFAULT_AUTORESEARCH_DIR,
) -> dict[str, Any]:
    """Run a deterministic local decision-quality benchmark and return JSON data.

    This evaluator intentionally does not simulate full Hold'em games, assign seats in
    a tournament engine, or call any remote server. It repeatedly presents practical
    decision scenarios to each strategy, scores decision quality with a local rubric,
    and reports a lower-confidence-bound score suitable for smoke-testing strategy
    changes before live play.
    """

    if games_per_strategy < MINIMUM_GAMES_PER_EVALUATION:
        raise ValueError("games_per_strategy must be at least 100")

    selected = list(strategy_names) if strategy_names is not None else list_strategies()
    scenarios = _benchmark_scenarios()
    results = [
        _evaluate_one_strategy(name, games_per_strategy, seed, scenarios)
        for name in selected
    ]
    report: dict[str, Any] = {
        "name": "holdem-practical-strategy-local-benchmark",
        "description": "Deterministic local decision-quality benchmark; not a full game engine.",
        "seed": seed,
        "games_per_strategy": games_per_strategy,
        "scenario_count": len(scenarios),
        "pass": all(result.pass_ for result in results),
        "score": _overall_score(results),
        "results": [result.to_json() for result in results],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if artifact_dir is not None:
        path = _artifact_path(artifact_dir, seed)
        report["artifact_path"] = str(path)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return report


def _evaluate_one_strategy(
    name: str,
    games_per_strategy: int,
    seed: int,
    scenarios: Sequence[BenchmarkScenario],
) -> StrategyBenchmarkResult:
    strategy = get_strategy(name)
    rng = random.Random(f"{seed}:{name}:scenario-variants")
    scores: list[float] = []
    invalid_actions = 0
    action_counts: dict[str, int] = {}

    for index in range(games_per_strategy):
        scenario = scenarios[index % len(scenarios)]
        context = _variant_context(scenario.context, index, rng)
        random.seed(f"{seed}:{name}:{scenario.scenario_id}:{index}")
        action = strategy.decide(context)
        action_counts[action.action] = action_counts.get(action.action, 0) + 1
        legal = is_legal_action(context, action)
        if not legal:
            invalid_actions += 1
        scores.append(_score_action(scenario, action, legal))

    mean = statistics.fmean(scores)
    standard_deviation = statistics.stdev(scores) if len(scores) > 1 else 0.0
    mean_bb_per_100 = mean * 100.0
    standard_error = (standard_deviation / math.sqrt(len(scores))) * 100.0
    score = mean_bb_per_100 - (1.96 * standard_error) - (invalid_actions * INVALID_ACTION_PENALTY)

    return StrategyBenchmarkResult(
        strategy=name,
        games=games_per_strategy,
        pass_=invalid_actions == 0,
        score=round(score, 6),
        mean_bb_per_100=round(mean_bb_per_100, 6),
        standard_error=round(standard_error, 6),
        invalid_actions=invalid_actions,
        action_counts=action_counts,
    )


def is_legal_action(context: DecisionContext, action: Action) -> bool:
    """Validate local action shape for benchmark scoring."""

    if action.action not in LEGAL_ACTIONS:
        return False
    if action.action == "check":
        return context.to_call == 0
    if action.action == "call":
        return context.to_call > 0
    if action.action == "raise":
        return action.amount is not None and context.min_raise <= action.amount <= context.my_stack
    if action.action == "allin":
        return context.my_stack > 0
    return context.to_call > 0


def _score_action(scenario: BenchmarkScenario, action: Action, legal: bool) -> float:
    if not legal:
        return -INVALID_ACTION_PENALTY
    return scenario.action_scores.get(action.action, -2.0)


def _overall_score(results: Sequence[StrategyBenchmarkResult]) -> float:
    if not results:
        return 0.0
    return round(statistics.fmean(result.score for result in results), 6)


def _artifact_path(artifact_dir: Path, seed: int) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir / f"iteration-seed-{seed}.json"


def _variant_context(context: DecisionContext, index: int, rng: random.Random) -> DecisionContext:
    pot_delta = rng.choice((-4, 0, 4, 8))
    stack_delta = rng.choice((-20, 0, 20))
    return dataclasses.replace(
        context,
        hand_number=index + 1,
        pot=max(context.blind[1] * 2, context.pot + pot_delta),
        my_stack=max(context.blind[1] * 3, context.my_stack + stack_delta),
        room_id=10_000 + index,
    )


def _benchmark_scenarios() -> tuple[BenchmarkScenario, ...]:
    return (
        BenchmarkScenario(
            scenario_id="button-open-pressure",
            context=_ctx(hole_cards=["Ah", "7h"], my_seat="btn", pot=6, to_call=0),
            action_scores={"raise": 1.4, "allin": -0.2, "call": -1.0, "check": -0.6, "fold": -1.0},
            description="Late-position steal candidate with ace blocker.",
        ),
        BenchmarkScenario(
            scenario_id="short-stack-premium-push",
            context=_ctx(hole_cards=["As", "Kh"], my_stack=18, blind=(1, 2), to_call=0),
            action_scores={"allin": 1.8, "raise": 1.0, "call": -0.5, "check": -1.2, "fold": -1.8},
            description="Nine-big-blind premium push/fold spot.",
        ),
        BenchmarkScenario(
            scenario_id="squeeze-after-open-call",
            context=_ctx(
                hole_cards=["Ad", "Qs"],
                pot=28,
                to_call=10,
                min_raise=28,
                action_history=[
                    ActionRecord(phase="preflop", player="villain-a", action="raise", amount=8),
                    ActionRecord(phase="preflop", player="villain-b", action="call", amount=8),
                ],
            ),
            action_scores={"raise": 1.6, "allin": 0.4, "call": 0.2, "fold": -1.0, "check": -2.0},
            description="Classic squeeze candidate after open and cold-call.",
        ),
        BenchmarkScenario(
            scenario_id="priced-flush-draw",
            context=_ctx(
                phase="flop",
                hole_cards=["Ah", "Th"],
                community_cards=["2h", "7h", "Ks"],
                pot=80,
                to_call=10,
                min_raise=28,
            ),
            action_scores={"call": 1.2, "raise": 0.8, "allin": -0.6, "fold": -1.2, "check": -2.0},
            description="Nut-flush draw getting a profitable price.",
        ),
        BenchmarkScenario(
            scenario_id="dry-board-position-cbet",
            context=_ctx(
                phase="flop",
                hole_cards=["Ac", "Qd"],
                community_cards=["Kc", "7d", "2s"],
                my_seat="btn",
                pot=44,
                to_call=0,
                min_raise=12,
                action_history=[ActionRecord(phase="preflop", player="hero", action="raise", amount=8)],
            ),
            action_scores={"raise": 1.1, "check": 0.2, "allin": -1.0, "call": -2.0, "fold": -1.0},
            description="Dry-board continuation pressure with position.",
        ),
        BenchmarkScenario(
            scenario_id="maniac-trap-top-pair",
            context=_ctx(
                phase="turn",
                hole_cards=["As", "Qh"],
                community_cards=["Ah", "8d", "3c", "2s"],
                pot=90,
                to_call=24,
                min_raise=72,
                action_history=[
                    ActionRecord(phase="preflop", player="villain", action="raise", amount=8),
                    ActionRecord(phase="flop", player="villain", action="raise", amount=20),
                    ActionRecord(phase="turn", player="villain", action="raise", amount=24),
                ],
            ),
            action_scores={"call": 1.3, "raise": 0.6, "allin": -0.2, "fold": -1.4, "check": -2.0},
            description="Strong hand against a hyper-aggressive line.",
        ),
        BenchmarkScenario(
            scenario_id="blind-defense-vs-small-open",
            context=_ctx(hole_cards=["Kc", "Jh"], my_seat="bb", pot=15, to_call=5, min_raise=16),
            action_scores={"call": 1.0, "raise": 0.8, "allin": -0.8, "fold": -0.8, "check": -2.0},
            description="Big blind defend against a small steal size.",
        ),
        BenchmarkScenario(
            scenario_id="bankroll-preserve-bad-price",
            context=_ctx(
                phase="river",
                hole_cards=["4c", "4d"],
                community_cards=["Ah", "Kd", "9s", "7c", "2h"],
                my_stack=120,
                starting_stack=300,
                pot=70,
                to_call=60,
                min_raise=120,
            ),
            action_scores={"fold": 1.4, "call": -1.5, "raise": -2.0, "allin": -2.0, "check": -2.0},
            description="Weak showdown hand facing a large river price.",
        ),
        BenchmarkScenario(
            scenario_id="value-heavy-wet-board",
            context=_ctx(
                phase="flop",
                hole_cards=["Qs", "Qh"],
                community_cards=["Qd", "Jd", "Td"],
                pot=100,
                to_call=0,
                min_raise=30,
            ),
            action_scores={"raise": 1.7, "allin": 0.9, "check": -0.8, "call": -2.0, "fold": -2.0},
            description="Very strong made hand on a wet board wants value/protection.",
        ),
        BenchmarkScenario(
            scenario_id="combo-draw-pressure",
            context=_ctx(
                phase="flop",
                hole_cards=["9h", "Th"],
                community_cards=["Jh", "Qh", "2c"],
                pot=60,
                to_call=0,
                min_raise=18,
            ),
            action_scores={"raise": 1.5, "allin": 0.3, "check": -0.4, "call": -2.0, "fold": -1.5},
            description="Open-ended straight-flush draw can profitably pressure.",
        ),
    )


def _ctx(**overrides: Any) -> DecisionContext:
    defaults: dict[str, Any] = {
        "hand_number": 1,
        "hole_cards": ["Ah", "Kh"],
        "community_cards": [],
        "phase": "preflop",
        "pot": 20,
        "my_stack": 300,
        "my_seat": "btn",
        "to_call": 0,
        "min_raise": 6,
        "blind": (1, 2),
        "players": [
            PlayerState(name="hero", stack=300, position="btn", status="active"),
            PlayerState(name="villain", stack=300, position="bb", status="active"),
        ],
        "action_history": [],
        "blind_structure": [BlindLevel(level=1, small=1, big=2, hands=20)],
        "starting_stack": 300,
        "room_id": 1,
    }
    defaults.update(overrides)
    return DecisionContext(**defaults)
