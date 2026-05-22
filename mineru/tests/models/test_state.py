import pytest
from pydantic import ValidationError

from holdem_agent.models.state import ActionRecord, BlindLevel, PlayerInfo, PlayerState


def test_player_state_creation() -> None:
    state = PlayerState(
        name="alice",
        stack=1000,
        position="btn",
        status="active",
    )

    assert state.name == "alice"
    assert state.stack == 1000
    assert state.position == "btn"
    assert state.status == "active"
    assert state.action is None
    assert state.bet == 0


def test_player_state_frozen() -> None:
    state = PlayerState(
        name="alice",
        stack=1000,
        position="btn",
        status="active",
    )

    with pytest.raises(ValidationError):
        state.name = "bob"


def test_action_record() -> None:
    record = ActionRecord(phase="preflop", player="alice", action="raise", amount=50)

    assert record.phase == "preflop"
    assert record.player == "alice"
    assert record.action == "raise"
    assert record.amount == 50


def test_blind_level() -> None:
    level = BlindLevel(level=1, small=10, big=20, hands=0)

    assert level.level == 1
    assert level.small == 10
    assert level.big == 20
    assert level.hands == 0


def test_player_info() -> None:
    with_stack = PlayerInfo(name="alice", type="bot", stack=2000)
    without_stack = PlayerInfo(name="carol", type="human")

    assert with_stack.name == "alice"
    assert with_stack.type == "bot"
    assert with_stack.stack == 2000
    assert without_stack.name == "carol"
    assert without_stack.type == "human"
    assert without_stack.stack is None
