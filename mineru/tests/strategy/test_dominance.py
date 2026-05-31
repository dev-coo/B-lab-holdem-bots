from __future__ import annotations

import pytest

from holdem_agent.models.state import ActionRecord, PlayerState
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.builtins.dominance import DOMINANCE_STRATEGIES, DominanceStrategy
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.registry import get_strategy, list_strategies


DOMINANCE_STRATEGY_SLUGS = [
    "dominance-seat-pressure",
    "dominance-shortstack-icm",
    "dominance-squeeze-iso",
    "dominance-nut-draw-leverager",
    "dominance-wet-board-protector",
    "dominance-river-sieve",
    "dominance-counter-punch",
    "dominance-blind-resteal-pro",
    "dominance-value-extractor",
    "dominance-adaptive-conductor",
]


def _ctx(**overrides: object) -> DecisionContext:
    defaults: dict[str, object] = {
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
        "players": [PlayerState(name="hero", stack=300, position="btn", status="active")],
        "action_history": [],
        "blind_structure": [],
        "starting_stack": 300,
        "room_id": 1,
    }
    defaults.update(overrides)
    return DecisionContext(**defaults)


def _representative_contexts() -> list[DecisionContext]:
    return [
        _ctx(hole_cards=["Ah", "7h"], my_seat="btn", to_call=0),
        _ctx(hole_cards=["As", "Kh"], my_stack=18, blind=(1, 2), to_call=0),
        _ctx(
            hole_cards=["Ad", "Qs"],
            to_call=10,
            min_raise=28,
            action_history=[
                ActionRecord(phase="preflop", player="villain-a", action="raise", amount=8),
                ActionRecord(phase="preflop", player="villain-b", action="call", amount=8),
            ],
        ),
        _ctx(
            phase="flop",
            hole_cards=["Ah", "Th"],
            community_cards=["2h", "7h", "Ks"],
            pot=80,
            to_call=10,
            min_raise=28,
        ),
        _ctx(
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
        _ctx(hole_cards=["Kc", "Jh"], my_seat="bb", pot=15, to_call=5, min_raise=16),
        _ctx(
            phase="river",
            hole_cards=["4c", "4d"],
            community_cards=["Ah", "Kd", "9s", "7c", "2h"],
            my_stack=120,
            starting_stack=300,
            pot=70,
            to_call=60,
            min_raise=120,
        ),
    ]


def _is_legal_for_context(context: DecisionContext, action: Action) -> bool:
    if action.action == "check":
        return context.to_call == 0
    if action.action == "call":
        return context.to_call > 0
    if action.action == "fold":
        return context.to_call > 0
    if action.action == "raise":
        return action.amount is not None and context.min_raise <= action.amount <= context.my_stack
    return action.action == "allin" and context.my_stack > 0


def test_dominance_strategy_slugs_are_registered() -> None:
    registered = list_strategies()

    assert [strategy_cls().name for strategy_cls in DOMINANCE_STRATEGIES] == DOMINANCE_STRATEGY_SLUGS
    for slug, strategy_cls in zip(DOMINANCE_STRATEGY_SLUGS, DOMINANCE_STRATEGIES, strict=True):
        strategy = get_strategy(slug)
        assert slug in registered
        assert isinstance(strategy, strategy_cls)
        assert isinstance(strategy, Strategy)


def test_dominance_strategies_support_from_genome() -> None:
    genome = StrategyGenome(bluff_frequency=0.19, exploit_aggression=0.81)

    for strategy_cls in DOMINANCE_STRATEGIES:
        strategy = strategy_cls.from_genome(genome)
        assert isinstance(strategy, DominanceStrategy)
        assert strategy.genome == genome


@pytest.mark.parametrize("slug", DOMINANCE_STRATEGY_SLUGS)
def test_dominance_strategies_return_legal_actions(
    slug: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.58,
    )
    strategy = get_strategy(slug)

    for context in _representative_contexts():
        action = strategy.decide(context)
        assert _is_legal_for_context(context, action), (
            slug,
            context.phase,
            context.to_call,
            action,
        )
        assert action.strategy_name == slug
