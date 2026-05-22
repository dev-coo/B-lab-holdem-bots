from __future__ import annotations

import dataclasses

import pytest

from holdem_agent.models.state import ActionRecord, BlindLevel, PlayerState
from holdem_agent.strategy.base import Action, DecisionContext, Strategy, safe_fallback
from holdem_agent.strategy.genome import StrategyGenome


def _sample_players() -> list[PlayerState]:
    return [
        PlayerState(name="alice", stack=1000, position="btn", status="active"),
        PlayerState(name="bob", stack=980, position="sb", status="active"),
    ]


def _sample_actions() -> list[ActionRecord]:
    return [
        ActionRecord(phase="preflop", player="alice", action="call", amount=20),
        ActionRecord(phase="preflop", player="bob", action="raise", amount=40),
    ]


def test_decision_context_creation() -> None:
    players = _sample_players()
    action_history = _sample_actions()
    context = DecisionContext(
        hand_number=7,
        hole_cards=["Ah", "Kh"],
        community_cards=["2s", "7d", "Kc"],
        phase="preflop",
        pot=60,
        my_stack=1200,
        my_seat="btn",
        to_call=20,
        min_raise=40,
        blind=(50, 100),
        players=players,
        action_history=action_history,
        blind_structure=[BlindLevel(level=1, small=50, big=100, hands=0)],
        starting_stack=2000,
        room_id=99,
    )

    assert context.hand_number == 7
    assert context.hole_cards == ["Ah", "Kh"]
    assert context.community_cards == ["2s", "7d", "Kc"]
    assert context.phase == "preflop"
    assert context.pot == 60
    assert context.my_stack == 1200
    assert context.my_seat == "btn"
    assert context.to_call == 20
    assert context.min_raise == 40
    assert context.blind == (50, 100)
    assert context.players == players
    assert context.action_history == action_history
    assert context.blind_structure == [BlindLevel(level=1, small=50, big=100, hands=0)]
    assert context.starting_stack == 2000
    assert context.room_id == 99


def test_decision_context_is_frozen() -> None:
    context = DecisionContext(
        hand_number=1,
        hole_cards=["As", "Ad"],
        community_cards=[],
        phase="flop",
        pot=0,
        my_stack=500,
        my_seat="bb",
        to_call=0,
        min_raise=0,
        blind=(25, 50),
        players=_sample_players(),
        action_history=[],
        blind_structure=[],
        starting_stack=1000,
        room_id=1,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.hand_number = 2


def test_action_creation_with_and_without_amount() -> None:
    with_amount = Action(action="raise", amount=150, reasoning="value", strategy_name="gto")
    without_amount = Action(action="check")

    assert with_amount.amount == 150
    assert with_amount.reasoning == "value"
    assert with_amount.strategy_name == "gto"
    assert without_amount.amount is None
    assert without_amount.reasoning == ""
    assert without_amount.strategy_name == ""


def test_action_is_frozen() -> None:
    action = Action(action="call", amount=100)

    with pytest.raises(dataclasses.FrozenInstanceError):
        action.amount = 200


def test_safe_fallback_check_when_no_call_required() -> None:
    context = DecisionContext(
        hand_number=2,
        hole_cards=["Qh", "Qd"],
        community_cards=["Qc", "7h", "2d"],
        phase="flop",
        pot=120,
        my_stack=900,
        my_seat="co",
        to_call=0,
        min_raise=40,
        blind=(50, 100),
        players=_sample_players(),
        action_history=_sample_actions(),
        blind_structure=[BlindLevel(level=2, small=50, big=100, hands=5)],
        starting_stack=1000,
        room_id=11,
    )

    assert safe_fallback(context) == Action(action="check")


def test_safe_fallback_fold_when_call_required() -> None:
    context = DecisionContext(
        hand_number=3,
        hole_cards=["Jh", "Jd"],
        community_cards=[],
        phase="turn",
        pot=200,
        my_stack=500,
        my_seat="utg",
        to_call=30,
        min_raise=60,
        blind=(25, 50),
        players=_sample_players(),
        action_history=[],
        blind_structure=[BlindLevel(level=1, small=25, big=50, hands=2)],
        starting_stack=1000,
        room_id=12,
    )

    assert safe_fallback(context) == Action(action="fold")


def test_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        Strategy()


class DummyStrategy(Strategy):
    def __init__(self, genome: StrategyGenome) -> None:
        self._genome = genome

    def decide(self, context: DecisionContext) -> Action:
        return Action(action="check", reasoning="always check", strategy_name="test")

    @property
    def genome(self) -> StrategyGenome:
        return self._genome

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> Strategy:
        return cls(genome)

    @property
    def name(self) -> str:
        return "test-strategy-v1"


def test_minimal_concrete_strategy_can_be_created_and_decide() -> None:
    strategy = DummyStrategy(genome=StrategyGenome())
    context = DecisionContext(
        hand_number=1,
        hole_cards=["6s", "6d"],
        community_cards=[],
        phase="preflop",
        pot=0,
        my_stack=1000,
        my_seat="btn",
        to_call=0,
        min_raise=0,
        blind=(25, 50),
        players=_sample_players(),
        action_history=[],
        blind_structure=[BlindLevel(level=1, small=25, big=50, hands=1)],
        starting_stack=1000,
        room_id=1,
    )

    action = strategy.decide(context)

    assert action == Action(action="check", reasoning="always check", strategy_name="test")
    assert strategy.name == "test-strategy-v1"


def test_from_genome_roundtrip() -> None:
    genome = StrategyGenome(preflop_raise_threshold={"btn": 0.5, "sb": 0.2, "bb": 0.8, "utg": 0.6, "co": 0.4})
    strategy = DummyStrategy.from_genome(genome)

    assert strategy.genome == genome

    restored = DummyStrategy.from_genome(strategy.genome)
    assert isinstance(restored, Strategy)
    assert restored.genome == genome
