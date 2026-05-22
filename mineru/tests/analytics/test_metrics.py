from __future__ import annotations

from holdem_agent.analytics.comparator import StrategyComparator
from holdem_agent.analytics.metrics import MetricsCalculator
from holdem_agent.storage.database import Database


def test_metrics_empty_strategy() -> None:
    db = Database.in_memory()
    calc = MetricsCalculator(db)

    summary = calc.get_strategy_metrics("empty")

    assert summary == {
        "strategy_name": "empty",
        "games_played": 0,
        "win_rate": 0.0,
        "avg_rank": 0.0,
        "total_hands": 0,
        "total_decisions": 0,
        "folds": 0,
        "raises": 0,
        "calls": 0,
    }
    assert calc.get_win_rate("empty") == 0.0
    assert calc.get_vpip("empty") == 0.0
    assert calc.get_aggression_factor("empty") == 0.0
    assert calc.get_action_distribution("empty") == {}

    db.close()


def _insert_strategy_game(
    db: Database,
    game_id: int,
    room_id: int,
    strategy_name: str,
    final_rank: int | None,
    total_hands: int,
) -> None:
    db.execute(
        "INSERT INTO games (id, room_id, strategy_name, started_at, final_rank, total_hands) VALUES (?, ?, ?, '2024-01-01', ?, ?)",
        (game_id, room_id, strategy_name, final_rank, total_hands),
    )


def _insert_decision(
    db: Database,
    game_id: int,
    room_id: int,
    hand_number: int,
    action_type: str,
    strategy_name: str,
    phase: str,
    pot: int,
    to_call: int,
    my_stack: int,
) -> None:
    db.execute(
        "INSERT INTO decisions (game_id, room_id, hand_number, action_type, strategy_name, phase, pot, to_call, my_stack, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2024-01-01')",
        (game_id, room_id, hand_number, action_type, strategy_name, phase, pot, to_call, my_stack),
    )


def test_metrics_get_win_rate() -> None:
    db = Database.in_memory()
    calc = MetricsCalculator(db)

    _insert_strategy_game(db, 1, 1, "strat-win-rate", 1, 10)
    _insert_strategy_game(db, 2, 1, "strat-win-rate", 3, 12)
    db.commit()

    assert calc.get_win_rate("strat-win-rate") == 0.5

    db.close()


def test_metrics_get_vpip() -> None:
    db = Database.in_memory()
    calc = MetricsCalculator(db)

    _insert_strategy_game(db, 1, 1, "strat-vpip", 2, 10)
    _insert_decision(db, 1, 1, 1, "call", "strat-vpip", "preflop", 10, 5, 300)
    _insert_decision(db, 1, 1, 2, "fold", "strat-vpip", "preflop", 20, 0, 290)
    _insert_decision(db, 1, 1, 3, "raise", "strat-vpip", "flop", 30, 0, 280)
    db.commit()

    assert calc.get_vpip("strat-vpip") == 2 / 3

    db.close()


def test_metrics_get_aggression_factor() -> None:
    db = Database.in_memory()
    calc = MetricsCalculator(db)

    _insert_strategy_game(db, 1, 1, "strat-af", 2, 9)
    _insert_decision(db, 1, 1, 1, "raise", "strat-af", "preflop", 10, 5, 300)
    _insert_decision(db, 1, 1, 2, "raise", "strat-af", "flop", 20, 0, 290)
    _insert_decision(db, 1, 1, 3, "call", "strat-af", "turn", 30, 10, 285)
    db.commit()

    assert calc.get_aggression_factor("strat-af") == 2.0

    db.close()


def test_metrics_action_distribution() -> None:
    db = Database.in_memory()
    calc = MetricsCalculator(db)

    _insert_strategy_game(db, 1, 1, "strat-dist", 1, 8)
    _insert_decision(db, 1, 1, 1, "raise", "strat-dist", "preflop", 10, 5, 300)
    _insert_decision(db, 1, 1, 2, "call", "strat-dist", "flop", 20, 0, 290)
    _insert_decision(db, 1, 1, 3, "call", "strat-dist", "turn", 30, 0, 280)
    _insert_decision(db, 1, 1, 4, "fold", "strat-dist", "river", 40, 0, 260)
    db.commit()

    assert calc.get_action_distribution("strat-dist") == {"raise": 1, "call": 2, "fold": 1}

    db.close()


def test_comparator_compare() -> None:
    db = Database.in_memory()
    comp = StrategyComparator(db)

    _insert_strategy_game(db, 1, 1, "strategy-a", 1, 10)
    _insert_strategy_game(db, 2, 1, "strategy-a", 4, 6)
    _insert_strategy_game(db, 3, 1, "strategy-b", 2, 8)
    db.commit()

    compared = comp.compare(["strategy-a", "strategy-b"])

    assert compared[0]["strategy_name"] == "strategy-a"
    assert compared[1]["strategy_name"] == "strategy-b"

    db.close()


def test_comparator_best_strategy() -> None:
    db = Database.in_memory()
    comp = StrategyComparator(db)

    _insert_strategy_game(db, 1, 1, "strategy-a", 2, 10)
    _insert_strategy_game(db, 2, 1, "strategy-a", 3, 12)
    _insert_strategy_game(db, 3, 1, "strategy-b", 1, 7)
    db.commit()

    assert comp.best_strategy(["strategy-a", "strategy-b"]) == "strategy-b"

    db.close()


def test_comparator_rank_strategies() -> None:
    db = Database.in_memory()
    comp = StrategyComparator(db)

    _insert_strategy_game(db, 1, 1, "strategy-a", 1, 10)
    _insert_strategy_game(db, 2, 1, "strategy-b", 3, 6)
    _insert_strategy_game(db, 3, 1, "strategy-c", 1, 8)
    db.commit()

    ranked = comp.rank_strategies(["strategy-a", "strategy-b", "strategy-c"])

    assert [row["strategy_name"] for row in ranked] == ["strategy-a", "strategy-c", "strategy-b"]
    assert [row["rank"] for row in ranked] == [1, 2, 3]

    db.close()
