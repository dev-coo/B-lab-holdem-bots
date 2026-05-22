from __future__ import annotations

# pyright: reportMissingImports=false

from holdem_agent.harness.recorder import GameRecorder
from holdem_agent.storage.database import Database
from holdem_agent.storage.game_store import GameStore


def test_recorder_game_start() -> None:
    db = Database.in_memory()
    recorder = GameRecorder(db, strategy_name="test")
    game_store = GameStore(db)

    recorder.record_game_start({"room_id": 101})

    game_id = recorder.get_game_id(101)
    game = game_store.get_game(game_id) if game_id is not None else None

    assert game_id is not None
    assert game is not None
    assert game["room_id"] == 101
    assert game["strategy_name"] == "test"

    db.close()


def test_recorder_decision() -> None:
    db = Database.in_memory()
    recorder = GameRecorder(db, strategy_name="test")
    game_store = GameStore(db)

    recorder.record_game_start({"room_id": 202})
    recorder.record_decision(
        room_id=202,
        hand_number=3,
        action_type="call",
        amount=0,
        reasoning="small pot",
        phase="preflop",
        pot=50,
        to_call=2,
        my_stack=100,
    )

    game_id = recorder.get_game_id(202)
    decisions = game_store.get_decisions(game_id) if game_id is not None else []

    assert game_id is not None
    assert len(decisions) == 1
    assert decisions[0]["action_type"] == "call"
    assert decisions[0]["amount"] == 0
    assert decisions[0]["hand_number"] == 3
    assert decisions[0]["phase"] == "preflop"

    db.close()


def test_recorder_hand_result() -> None:
    db = Database.in_memory()
    recorder = GameRecorder(db, strategy_name="test")

    recorder.record_game_start({"room_id": 303})
    recorder.record_hand_result(
        {
            "room_id": 303,
            "hand_number": 7,
            "pot": 500,
            "community_cards": ["Ah", "Ks", "Qc", "2d", "9c"],
            "winners": [{"name": "bot", "amount": 500}],
        }
    )

    game_id = recorder.get_game_id(303)
    row = db.execute("SELECT * FROM hand_results WHERE game_id=?", (game_id,)).fetchone()

    assert row is not None
    assert row["hand_number"] == 7
    assert row["pot"] == 500
    assert row["won"] == 500
    assert row["community_cards"] == '["Ah", "Ks", "Qc", "2d", "9c"]'
    assert game_id is not None
    assert row["room_id"] == 303
    assert row["game_id"] == game_id

    db.close()


def test_recorder_game_end() -> None:
    db = Database.in_memory()
    recorder = GameRecorder(db, strategy_name="test")
    game_store = GameStore(db)

    recorder.record_game_start({"room_id": 404})
    game_id = recorder.get_game_id(404)
    recorder.record_game_end(
        {
            "room_id": 404,
            "rankings": [
                {"rank": 1, "chips": 1200},
                {"rank": 2, "chips": 800},
            ],
        }
    )

    game = game_store.get_game(game_id)

    assert game is not None
    assert game["final_rank"] == 1
    assert game["final_chips"] == 1200
    assert recorder.get_game_id(404) is None

    db.close()


def test_recorder_full_game() -> None:
    db = Database.in_memory()
    recorder = GameRecorder(db, strategy_name="full")
    game_store = GameStore(db)

    room_id = 505
    recorder.record_game_start({"room_id": room_id})

    recorder.record_decision(
        room_id=room_id,
        hand_number=1,
        action_type="raise",
        amount=20,
        reasoning="aggressive",
        phase="flop",
        pot=40,
        to_call=4,
        my_stack=300,
    )
    recorder.record_hand_result(
        {
            "room_id": room_id,
            "hand_number": 1,
            "pot": 240,
            "community_cards": ["7c", "8d", "9h", "2s", "3d"],
            "winners": [{"amount": 240}],
        }
    )
    recorder.record_game_end(
        {
            "room_id": room_id,
            "rankings": [{"rank": 2, "chips": 900}],
        }
    )

    game_id = game_store.get_game_count("full")
    game_rows = db.execute("SELECT * FROM games WHERE strategy_name=? ORDER BY id DESC", ("full",)).fetchall()
    game = game_rows[0]
    decisions = game_store.get_decisions(game["id"])
    hand_result = db.execute(
        "SELECT * FROM hand_results WHERE game_id=?", (game["id"],)
    ).fetchone()

    assert game_id == 1
    assert len(decisions) == 1
    assert decisions[0]["action_type"] == "raise"
    assert hand_result is not None
    assert hand_result["won"] == 240
    assert hand_result["hand_number"] == 1
    assert hand_result["pot"] == 240
    assert game["final_rank"] == 2
    assert game["final_chips"] == 900
    assert recorder.get_game_id(room_id) is None

    db.close()
