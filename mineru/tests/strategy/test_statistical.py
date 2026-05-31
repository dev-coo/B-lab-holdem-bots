from __future__ import annotations

from typing import Any

import pytest

from holdem_agent.models.state import ActionRecord, PlayerState
from holdem_agent.strategy.base import Action, DecisionContext, Strategy
from holdem_agent.strategy.builtins.statistical import (
    STATISTICAL_STRATEGIES,
    BayesianExploit,
    LearningFieldExploit,
    RobustFieldExploit,
    StageSafeFieldCounter,
    StatisticalLCBFusion,
)
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.registry import get_strategy, list_strategies


STATISTICAL_STRATEGY_SLUGS = [
    "statistical-lcb-fusion",
    "bayesian-exploit",
    "robust-field-exploit",
    "learning-field-exploit",
    "stage-safe-field-counter",
]


def _ctx(**overrides: object) -> DecisionContext:
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


def test_statistical_strategy_slug_is_registered() -> None:
    registered = list_strategies()

    assert [strategy_cls().name for strategy_cls in STATISTICAL_STRATEGIES] == STATISTICAL_STRATEGY_SLUGS
    strategy = get_strategy("statistical-lcb-fusion")
    assert "statistical-lcb-fusion" in registered
    assert "bayesian-exploit" in registered
    assert "robust-field-exploit" in registered
    assert "learning-field-exploit" in registered
    assert "stage-safe-field-counter" in registered
    assert isinstance(strategy, StatisticalLCBFusion)
    assert isinstance(get_strategy("bayesian-exploit"), BayesianExploit)
    assert isinstance(get_strategy("robust-field-exploit"), RobustFieldExploit)
    assert isinstance(get_strategy("learning-field-exploit"), LearningFieldExploit)
    assert isinstance(get_strategy("stage-safe-field-counter"), StageSafeFieldCounter)
    assert isinstance(strategy, Strategy)


def test_statistical_strategy_supports_from_genome() -> None:
    genome = StrategyGenome(bluff_frequency=0.07, exploit_aggression=0.62)

    strategy = StatisticalLCBFusion.from_genome(genome)

    assert isinstance(strategy, StatisticalLCBFusion)
    assert strategy.genome == genome

    bayesian = BayesianExploit.from_genome(genome)

    assert isinstance(bayesian, BayesianExploit)
    assert bayesian.genome == genome

    robust = RobustFieldExploit.from_genome(genome)

    assert isinstance(robust, RobustFieldExploit)
    assert robust.genome == genome

    learning = LearningFieldExploit.from_genome(genome)

    assert isinstance(learning, LearningFieldExploit)
    assert learning.genome == genome

    counter = StageSafeFieldCounter.from_genome(genome)

    assert isinstance(counter, StageSafeFieldCounter)
    assert counter.genome == genome


@pytest.mark.parametrize("slug", STATISTICAL_STRATEGY_SLUGS)
def test_statistical_strategy_returns_legal_actions(
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


def test_statistical_strategy_keeps_local_high_signal_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = get_strategy("statistical-lcb-fusion")

    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.47,
    )
    squeeze = _ctx(
        hole_cards=["Ad", "Qs"],
        to_call=10,
        min_raise=28,
        action_history=[
            ActionRecord(phase="preflop", player="villain-a", action="raise", amount=8),
            ActionRecord(phase="preflop", player="villain-b", action="call", amount=8),
        ],
    )

    assert strategy.decide(squeeze).action == "raise"

    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.44,
    )
    river_bad_price = _ctx(
        phase="river",
        hole_cards=["4c", "4d"],
        community_cards=["Ah", "Kd", "9s", "7c", "2h"],
        my_stack=120,
        pot=70,
        to_call=60,
        min_raise=120,
    )

    assert strategy.decide(river_bad_price).action == "fold"


def test_statistical_strategy_uses_low_variance_bluff_catch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.58,
    )
    strategy = get_strategy("statistical-lcb-fusion")
    context = _ctx(
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
    )

    action = strategy.decide(context)

    assert action.action == "call"
    assert action.strategy_name == "statistical-lcb-fusion"


def test_bayesian_exploit_deduplicates_replayed_action_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.58,
    )
    strategy = BayesianExploit()
    context = _ctx(
        players=[
            PlayerState(name="hero", stack=300, position="btn", status="active"),
            PlayerState(name="villain", stack=300, position="bb", status="active"),
        ],
        action_history=[
            ActionRecord(phase="preflop", player="villain", action="call", amount=2),
            ActionRecord(phase="flop", player="villain", action="fold", amount=0),
        ],
    )

    strategy.decide(context)
    strategy.decide(context)

    profile = strategy.opponent_profiles["villain"]
    assert profile.hands_seen == 1
    assert profile.total_actions == 2
    assert profile.call_count == 1
    assert profile.fold_count == 1


def test_bayesian_exploit_attacks_overfolders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.34,
    )
    strategy = BayesianExploit()
    for hand_number in range(1, 5):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                hole_cards=["9c", "2d"],
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="villain", stack=300, position="bb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="villain", action="fold", amount=0),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=5,
            hole_cards=["9c", "2d"],
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="villain", stack=300, position="bb", status="active"),
            ],
        )
    )

    assert action.action == "raise"
    assert "overfolder" in action.reasoning
    assert action.strategy_name == "bayesian-exploit"


def test_bayesian_exploit_value_targets_calling_stations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.61,
    )
    strategy = BayesianExploit()
    for hand_number in range(1, 5):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="station", stack=300, position="bb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="station", action="call", amount=2),
                    ActionRecord(phase="flop", player="station", action="call", amount=10),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=5,
            phase="flop",
            community_cards=["Ah", "8d", "2c"],
            pot=80,
            min_raise=20,
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="station", stack=300, position="bb", status="active"),
            ],
        )
    )

    assert action.action == "raise"
    assert "station" in action.reasoning
    assert action.strategy_name == "bayesian-exploit"


def test_bayesian_exploit_bluff_catches_maniacs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.52,
    )
    strategy = BayesianExploit()
    for hand_number in range(1, 5):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="maniac", stack=300, position="bb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="maniac", action="raise", amount=8),
                    ActionRecord(phase="flop", player="maniac", action="raise", amount=24),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=5,
            to_call=10,
            pot=40,
            min_raise=30,
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="maniac", stack=300, position="bb", status="active"),
            ],
            action_history=[
                ActionRecord(phase="preflop", player="maniac", action="raise", amount=10),
            ],
        )
    )

    assert action.action == "call"
    assert "maniac" in action.reasoning
    assert action.strategy_name == "bayesian-exploit"


def test_robust_field_exploit_steals_only_when_field_overfolds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.33,
    )
    strategy = RobustFieldExploit()
    for hand_number in range(1, 6):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                hole_cards=["9c", "2d"],
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="folder-a", stack=300, position="bb", status="active"),
                    PlayerState(name="folder-b", stack=300, position="sb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="folder-a", action="fold", amount=0),
                    ActionRecord(phase="preflop", player="folder-b", action="fold", amount=0),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=6,
            hole_cards=["9c", "2d"],
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="folder-a", stack=300, position="bb", status="active"),
                PlayerState(name="folder-b", stack=300, position="sb", status="active"),
            ],
        )
    )

    assert action.action == "raise"
    assert "field confidence steal" in action.reasoning
    assert action.strategy_name == "robust-field-exploit"


def test_robust_field_exploit_does_not_average_station_and_folder_into_bluff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.33,
    )
    strategy = RobustFieldExploit()
    for hand_number in range(1, 6):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                hole_cards=["9c", "2d"],
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="station", stack=300, position="bb", status="active"),
                    PlayerState(name="folder", stack=300, position="sb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="station", action="call", amount=2),
                    ActionRecord(phase="flop", player="station", action="call", amount=8),
                    ActionRecord(phase="preflop", player="folder", action="fold", amount=0),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=6,
            phase="flop",
            hole_cards=["9c", "2d"],
            community_cards=["Ah", "7d", "2c"],
            pot=60,
            to_call=0,
            min_raise=16,
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="station", stack=300, position="bb", status="active"),
                PlayerState(name="folder", stack=300, position="sb", status="active"),
            ],
        )
    )

    assert action.action == "check"
    assert "station mix" in action.reasoning
    assert action.strategy_name == "robust-field-exploit"


def test_robust_field_exploit_value_bets_mixed_station_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.63,
    )
    strategy = RobustFieldExploit()
    for hand_number in range(1, 6):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="station", stack=300, position="bb", status="active"),
                    PlayerState(name="balanced", stack=300, position="sb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="station", action="call", amount=2),
                    ActionRecord(phase="flop", player="station", action="call", amount=8),
                    ActionRecord(phase="preflop", player="balanced", action="check", amount=0),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=6,
            phase="flop",
            community_cards=["Qd", "Jd", "2c"],
            pot=80,
            to_call=0,
            min_raise=20,
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="station", stack=300, position="bb", status="active"),
                PlayerState(name="balanced", stack=300, position="sb", status="active"),
            ],
        )
    )

    assert action.action == "raise"
    assert "station mix" in action.reasoning
    assert action.strategy_name == "robust-field-exploit"


def test_robust_field_exploit_uses_pressure_actor_against_mixed_maniac_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.52,
    )
    strategy = RobustFieldExploit()
    for hand_number in range(1, 6):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="maniac", stack=300, position="bb", status="active"),
                    PlayerState(name="station", stack=300, position="sb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="maniac", action="raise", amount=8),
                    ActionRecord(phase="flop", player="maniac", action="raise", amount=20),
                    ActionRecord(phase="preflop", player="station", action="call", amount=8),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=6,
            phase="turn",
            community_cards=["Ah", "8d", "3c", "2s"],
            pot=90,
            to_call=24,
            min_raise=72,
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="maniac", stack=300, position="bb", status="active"),
                PlayerState(name="station", stack=300, position="sb", status="active"),
            ],
            action_history=[
                ActionRecord(phase="turn", player="maniac", action="raise", amount=24),
            ],
        )
    )

    assert action.action == "call"
    assert "maniac" in action.reasoning
    assert action.strategy_name == "robust-field-exploit"


def test_learning_field_exploit_strengthens_after_more_hands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.29,
    )

    def train(strategy: LearningFieldExploit) -> None:
        for hand_number in range(1, 6):
            strategy.decide(
                _ctx(
                    hand_number=hand_number,
                    hole_cards=["2h", "7d"],
                    players=[
                        PlayerState(name="hero", stack=300, position="btn", status="active"),
                        PlayerState(name="folder", stack=300, position="bb", status="active"),
                        PlayerState(name="balanced", stack=300, position="sb", status="active"),
                    ],
                    action_history=[
                        ActionRecord(phase="preflop", player="folder", action="fold", amount=0),
                        ActionRecord(phase="preflop", player="balanced", action="check", amount=0),
                    ],
                )
            )

    early = LearningFieldExploit()
    train(early)
    early_action = early.decide(
        _ctx(
            hand_number=6,
            hole_cards=["2h", "7d"],
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="folder", stack=300, position="bb", status="active"),
                PlayerState(name="balanced", stack=300, position="sb", status="active"),
            ],
        )
    )

    late = LearningFieldExploit()
    train(late)
    late_action = late.decide(
        _ctx(
            hand_number=20,
            hole_cards=["2h", "7d"],
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="folder", stack=300, position="bb", status="active"),
                PlayerState(name="balanced", stack=300, position="sb", status="active"),
            ],
        )
    )

    assert early_action.action == "check"
    assert late_action.action == "raise"
    assert "learning late-stage steal" in late_action.reasoning
    assert late_action.strategy_name == "learning-field-exploit"


def test_stage_safe_field_counter_controls_early_multiway_weak_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.33,
    )
    strategy = StageSafeFieldCounter()
    context = _ctx(
        hand_number=1,
        hole_cards=["9c", "2d"],
        players=[
            PlayerState(name="hero", stack=300, position="utg", status="active"),
            PlayerState(name="v1", stack=300, position="mp", status="active"),
            PlayerState(name="v2", stack=300, position="co", status="active"),
            PlayerState(name="v3", stack=300, position="btn", status="active"),
            PlayerState(name="v4", stack=300, position="bb", status="active"),
        ],
        my_seat="utg",
    )

    action = strategy.decide(context)

    assert action.action == "check"
    assert "multiway early-range control" in action.reasoning
    assert action.strategy_name == "stage-safe-field-counter"


@pytest.mark.parametrize(
    ("player_count", "hand_number"),
    [
        (2, 1),
        (6, 12),
        (9, 30),
    ],
)
def test_stage_safe_field_counter_handles_table_size_and_stage_matrix(
    monkeypatch: pytest.MonkeyPatch,
    player_count: int,
    hand_number: int,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.52,
    )
    positions = ["btn", "sb", "bb", "utg", "hj", "co", "mp", "utg1", "mp1"]
    players = [
        PlayerState(name="hero", stack=300, position="btn", status="active"),
        *[
            PlayerState(name=f"villain-{index}", stack=300, position=positions[index], status="active")
            for index in range(1, player_count)
        ],
    ]
    strategy = StageSafeFieldCounter()

    action = strategy.decide(
        _ctx(
            hand_number=hand_number,
            phase="flop",
            hole_cards=["As", "Qh"],
            community_cards=["Ah", "8d", "3c"],
            pot=60,
            to_call=12,
            min_raise=36,
            players=players,
        )
    )

    assert _is_legal_for_context(_ctx(to_call=12, min_raise=36, players=players), action)
    assert action.strategy_name == "stage-safe-field-counter"


def test_stage_safe_field_counter_defends_late_position_steals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.38,
    )
    strategy = StageSafeFieldCounter()
    for hand_number in range(1, 9):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                hole_cards=["Ah", "7d"],
                my_seat="bb",
                to_call=8,
                min_raise=20,
                players=[
                    PlayerState(name="button", stack=300, position="btn", status="active"),
                    PlayerState(name="hero", stack=300, position="bb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="button", action="raise", amount=8),
                    ActionRecord(phase="flop", player="button", action="raise", amount=18),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=20,
            hole_cards=["Ah", "7d"],
            my_seat="bb",
            to_call=8,
            min_raise=20,
            players=[
                PlayerState(name="button", stack=300, position="btn", status="active"),
                PlayerState(name="hero", stack=300, position="bb", status="active"),
            ],
            action_history=[
                ActionRecord(phase="preflop", player="button", action="raise", amount=8),
            ],
        )
    )

    assert action.action == "raise"
    assert "anti-steal" in action.reasoning
    assert action.strategy_name == "stage-safe-field-counter"


def test_stage_safe_field_counter_applies_late_safe_pressure_to_overfolders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "holdem_agent.strategy.builtins.practical.estimated_equity",
        lambda *_args, **_kwargs: 0.32,
    )
    strategy = StageSafeFieldCounter()
    for hand_number in range(1, 7):
        strategy.decide(
            _ctx(
                hand_number=hand_number,
                hole_cards=["Kc", "7d"],
                my_seat="btn",
                players=[
                    PlayerState(name="hero", stack=300, position="btn", status="active"),
                    PlayerState(name="folder-a", stack=300, position="sb", status="active"),
                    PlayerState(name="folder-b", stack=300, position="bb", status="active"),
                ],
                action_history=[
                    ActionRecord(phase="preflop", player="folder-a", action="fold", amount=0),
                    ActionRecord(phase="preflop", player="folder-b", action="fold", amount=0),
                ],
            )
        )

    action = strategy.decide(
        _ctx(
            hand_number=24,
            hole_cards=["Kc", "7d"],
            my_seat="btn",
            players=[
                PlayerState(name="hero", stack=300, position="btn", status="active"),
                PlayerState(name="folder-a", stack=300, position="sb", status="active"),
                PlayerState(name="folder-b", stack=300, position="bb", status="active"),
            ],
        )
    )

    assert action.action == "raise"
    assert "safe field steal" in action.reasoning
    assert action.strategy_name == "stage-safe-field-counter"
