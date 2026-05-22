from __future__ import annotations

# pyright: reportMissingImports=false

from holdem_agent.harness.replayer import GameReplayer, ReplayAction, ReplayHand
from holdem_agent.storage.database import Database


def _seed_game_and_decisions(db: Database) -> None:
    db.execute(
        "INSERT INTO games (id, room_id, strategy_name, started_at, final_rank, total_hands) "
        "VALUES (1, 1, 'test', '2024-01-01', 1, 5)"
    )
    db.execute(
        "INSERT INTO decisions (game_id, room_id, hand_number, action_type, amount, reasoning, strategy_name, phase, pot, "
        "to_call, my_stack, timestamp) VALUES (1, 1, 1, 'fold', NULL, 'weak', 'test', 'preflop', 10, 5, 300, '2024-01-01')"
    )
    db.execute(
        "INSERT INTO decisions (game_id, room_id, hand_number, action_type, amount, reasoning, strategy_name, phase, pot, "
        "to_call, my_stack, timestamp) VALUES (1, 1, 1, 'call', NULL, 'decent', 'test', 'flop', 20, 10, 295, '2024-01-01')"
    )
    db.execute(
        "INSERT INTO decisions (game_id, room_id, hand_number, action_type, amount, reasoning, strategy_name, phase, pot, "
        "to_call, my_stack, timestamp) VALUES (1, 1, 2, 'raise', 40, 'strong', 'test', 'turn', 40, 0, 285, '2024-01-01')"
    )
    db.commit()


def test_replay_nonexistent_game() -> None:
    db = Database.in_memory()
    replayer = GameReplayer(db)

    assert replayer.replay_game(999) is None

    db.close()


def test_replay_game_basic() -> None:
    db = Database.in_memory()
    _seed_game_and_decisions(db)
    replayer = GameReplayer(db)

    summary = replayer.replay_game(1)

    assert summary is not None
    assert summary.game_id == 1
    assert summary.strategy_name == "test"
    assert summary.total_hands == 5
    assert summary.final_rank == 1
    assert summary.final_chips is None
    assert len(summary.actions) == 3
    assert isinstance(summary.actions[0], ReplayAction)
    assert summary.actions[0].action_type == "fold"
    assert summary.actions[1].hand_number == 1
    assert summary.actions[2].phase == "turn"

    db.close()


def test_replay_action_counts() -> None:
    db = Database.in_memory()
    _seed_game_and_decisions(db)
    replayer = GameReplayer(db)

    summary = replayer.replay_game(1)

    assert summary is not None
    assert summary.fold_count == 1
    assert summary.call_count == 1
    assert summary.raise_count == 1

    db.close()


def test_replay_action_sequence() -> None:
    db = Database.in_memory()
    _seed_game_and_decisions(db)
    replayer = GameReplayer(db)

    hand_one_actions = replayer.get_action_sequence(1, 1)

    assert len(hand_one_actions) == 2
    assert hand_one_actions[0].action_type == "fold"
    assert hand_one_actions[1].action_type == "call"
    assert all(a.hand_number == 1 for a in hand_one_actions)

    db.close()


def test_replay_summary_properties() -> None:
    db = Database.in_memory()
    _seed_game_and_decisions(db)
    db.execute(
        "INSERT INTO hand_results (game_id, room_id, hand_number, pot, won, community_cards, timestamp) "
        "VALUES (1, 1, 1, 20, 100, '[]', '2024-01-01')"
    )
    db.execute(
        "INSERT INTO hand_results (game_id, room_id, hand_number, pot, won, community_cards, timestamp) "
        "VALUES (1, 1, 2, 30, 50, '[]', '2024-01-01')"
    )
    db.commit()

    replayer = GameReplayer(db)
    summary = replayer.replay_game(1)

    assert summary is not None
    assert summary.total_won == 150
    assert summary.fold_count == 1
    assert summary.call_count == 1
    assert summary.raise_count == 1
    assert len(summary.hands) == 2
    assert isinstance(summary.hands[0], ReplayHand)
    assert summary.hands[0].result_won == 100
    assert summary.hands[1].result_won == 50

    db.close()
