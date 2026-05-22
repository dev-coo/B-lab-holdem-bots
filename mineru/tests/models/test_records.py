import json

import pytest
from pydantic import ValidationError

from holdem_agent.models.records import (
    ActionRequestRecord,
    DecisionRecord,
    GameRecord,
    HandResultRecord,
    StrategyMetrics,
    StrategyVersionRecord,
)


def test_game_record_creation_fields_and_types() -> None:
    record = GameRecord(
        room_id=101,
        strategy_name="baseline",
        started_at="2026-01-01T00:00:00Z",
        total_hands=7,
    )

    assert record.id is None
    assert record.room_id == 101
    assert record.strategy_name == "baseline"
    assert record.started_at == "2026-01-01T00:00:00Z"
    assert record.finished_at is None
    assert record.final_rank is None
    assert record.final_chips is None
    assert record.total_hands == 7

    assert isinstance(record.id, type(None))
    assert isinstance(record.room_id, int)
    assert isinstance(record.strategy_name, str)


def test_game_record_frozen() -> None:
    record = GameRecord(room_id=1, strategy_name="x", started_at="s")

    with pytest.raises(ValidationError):
        record.total_hands = 9


def test_game_record_json_default_id() -> None:
    record = GameRecord(room_id=1, strategy_name="x", started_at="t")

    assert record.id is None


def test_action_request_record_creation_and_json_round_trip() -> None:
    hole_cards = ["Ah", "Ad"]
    community_cards = ["Ks", "Qc", "2h"]
    players = [{"name": "alice", "stack": 1000}, {"name": "bob", "stack": 850}]
    action_history = [
        {"street": "preflop", "action": "call"},
        {"street": "preflop", "action": "raise", "amount": 40},
    ]
    payload = ActionRequestRecord(
        game_id=11,
        room_id=101,
        hand_number=2,
        phase="preflop",
        hole_cards=json.dumps(hole_cards),
        community_cards=json.dumps(community_cards),
        pot=120,
        my_stack=500,
        to_call=20,
        min_raise=40,
        seat="utg",
        players_json=json.dumps(players),
        action_history_json=json.dumps(action_history),
        timestamp="2026-01-01T00:00:10Z",
    )

    assert payload.id is None
    assert payload.game_id == 11
    assert payload.room_id == 101
    assert payload.hand_number == 2
    assert payload.phase == "preflop"
    assert json.loads(payload.hole_cards) == hole_cards
    assert json.loads(payload.community_cards) == community_cards
    assert json.loads(payload.players_json) == players
    assert json.loads(payload.action_history_json) == action_history

    assert isinstance(payload.pot, int)
    assert isinstance(payload.to_call, int)


def test_action_request_record_frozen() -> None:
    payload = ActionRequestRecord(
        game_id=11,
        room_id=101,
        hand_number=2,
        phase="flop",
        hole_cards="[]",
        community_cards="[]",
        pot=0,
        my_stack=100,
        to_call=0,
        min_raise=0,
        seat="btn",
        players_json="[]",
        action_history_json="[]",
        timestamp="2026-01-01T00:00:20Z",
    )

    with pytest.raises(ValidationError):
        payload.timestamp = "x"



def test_hand_result_record_default_id_none() -> None:
    record = HandResultRecord(
        game_id=20,
        room_id=555,
        hand_number=9,
        pot=2300,
        winners_json="[]",
        showdown_json="[]",
        community_cards="[]",
        eliminated_json="[]",
        timestamp="2026-01-01T00:02:00Z",
    )

    assert record.id is None


def test_decision_record_creation_optional_amount_default_none() -> None:
    record = DecisionRecord(
        game_id=3,
        room_id=42,
        hand_number=1,
        action_type="check",
        strategy_name="baseline",
        timestamp="2026-01-01T00:01:00Z",
    )

    assert record.id is None
    assert record.amount is None
    assert record.reasoning == ""


def test_decision_record_frozen() -> None:
    record = DecisionRecord(
        game_id=3,
        room_id=42,
        hand_number=1,
        action_type="call",
        amount=75,
        strategy_name="balanced",
        timestamp="2026-01-01T00:01:00Z",
    )

    with pytest.raises(ValidationError):
        record.action_type = "raise"


def test_hand_result_record_creation_and_json_round_trip() -> None:
    winners = ["alice"]
    showdown = [{"alice": "pair of aces"}]
    community_cards = ["Ah", "Ad", "7d"]
    eliminated = ["bob"]

    record = HandResultRecord(
        game_id=20,
        room_id=555,
        hand_number=9,
        pot=2300,
        winners_json=json.dumps(winners),
        showdown_json=json.dumps(showdown),
        community_cards=json.dumps(community_cards),
        eliminated_json=json.dumps(eliminated),
        timestamp="2026-01-01T00:02:00Z",
    )

    assert record.pot == 2300
    assert json.loads(record.winners_json) == winners
    assert json.loads(record.showdown_json) == showdown
    assert json.loads(record.community_cards) == community_cards
    assert json.loads(record.eliminated_json) == eliminated
    assert isinstance(record.winners_json, str)


def test_hand_result_record_frozen() -> None:
    record = HandResultRecord(
        game_id=20,
        room_id=555,
        hand_number=9,
        pot=2300,
        winners_json="[]",
        showdown_json="[]",
        community_cards="[]",
        eliminated_json="[]",
        timestamp="2026-01-01T00:02:00Z",
    )

    with pytest.raises(ValidationError):
        record.pot = 2400


def test_strategy_version_record_creation_and_json_round_trip() -> None:
    genome = {"traits": [1, 2, 3], "threshold": 0.8}

    record = StrategyVersionRecord(
        name="baseline",
        version=4,
        genome_json=json.dumps(genome),
        origin="manual",
        created_at="2026-01-01T00:03:00Z",
    )

    assert record.id is None
    assert record.parent_name is None
    assert record.parent_version is None
    assert record.games_played == 0
    assert record.win_rate == 0.0
    assert json.loads(record.genome_json) == genome


def test_strategy_version_record_frozen() -> None:
    record = StrategyVersionRecord(
        name="x",
        version=1,
        genome_json="{}",
        origin="mutation",
        created_at="2026-01-01T00:04:00Z",
        games_played=12,
        win_rate=0.55,
    )

    with pytest.raises(ValidationError):
        record.version = 2


def test_strategy_metrics_creation_fields_and_types() -> None:
    record = StrategyMetrics(
        strategy_name="v1",
        games_played=30,
        win_rate=0.62,
        avg_roi=1.8,
        total_hands=300,
        vpip=0.28,
        pfr=0.22,
        money_won=1500,
    )

    assert record.strategy_name == "v1"
    assert record.games_played == 30
    assert record.money_won == 1500
    assert isinstance(record.win_rate, float)
    assert isinstance(record.avg_roi, float)
    assert isinstance(record.vpip, float)
    assert isinstance(record.pfr, float)


def test_strategy_metrics_frozen() -> None:
    record = StrategyMetrics(
        strategy_name="v2",
        games_played=10,
        win_rate=0.5,
        avg_roi=1.0,
        total_hands=100,
        vpip=0.3,
        pfr=0.1,
        money_won=0,
    )

    with pytest.raises(ValidationError):
        record.money_won = 10
