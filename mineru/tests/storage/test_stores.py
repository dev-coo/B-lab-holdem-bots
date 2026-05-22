from __future__ import annotations

# pyright: reportMissingImports=false

from holdem_agent.storage.database import Database
from holdem_agent.storage.game_store import GameStore
from holdem_agent.storage.metrics_store import MetricsStore
from holdem_agent.storage.strategy_store import StrategyStore
from holdem_agent.strategy.genome import StrategyGenome


def _position_dict(value: float) -> dict[str, float]:
    return {
        "btn": value,
        "sb": value,
        "bb": value,
        "utg": value,
        "co": value,
    }


def _sample_genome() -> StrategyGenome:
    return StrategyGenome(
        preflop_raise_threshold=_position_dict(0.4),
        preflop_call_threshold=_position_dict(0.55),
        preflop_3bet_threshold=_position_dict(0.1),
        cbet_frequency=0.6,
        cbet_size_pot_fraction=0.7,
        raise_size_pot_fraction=1.2,
        three_bet_size_pot_fraction=1.4,
        bluff_frequency=0.09,
        semi_bluff_equity_threshold=0.24,
        river_bluff_frequency=0.04,
        fold_to_raise_equity=0.28,
        check_raise_frequency=0.08,
        donk_bet_frequency=0.03,
        m_conservative=14.0,
        m_desperate=4.0,
        exploit_aggression=0.45,
        adapt_speed=0.11,
    )


def test_game_store_create_and_finish() -> None:
    db = Database.in_memory()
    store = GameStore(db)

    game_id = store.create_game(room_id=101, strategy_name="tag")
    store.finish_game(game_id, final_rank=1, final_chips=2300, total_hands=18)

    game = store.get_game(game_id)

    assert game is not None
    assert game["room_id"] == 101
    assert game["strategy_name"] == "tag"
    assert game["final_rank"] == 1
    assert game["final_chips"] == 2300
    assert game["total_hands"] == 18
    assert game["finished_at"] is not None

    db.close()


def test_game_store_record_decision() -> None:
    db = Database.in_memory()
    store = GameStore(db)
    game_id = store.create_game(room_id=5, strategy_name="gto")

    store.record_decision(
        game_id=game_id,
        room_id=5,
        hand_number=12,
        action_type="raise",
        amount=160,
        reasoning="Value raise with top pair",
        strategy_name="gto",
        phase="flop",
        pot=200,
        to_call=40,
        my_stack=1800,
    )

    decisions = store.get_decisions(game_id)

    assert len(decisions) == 1
    assert decisions[0]["hand_number"] == 12
    assert decisions[0]["action_type"] == "raise"
    assert decisions[0]["amount"] == 160
    assert decisions[0]["reasoning"] == "Value raise with top pair"
    assert decisions[0]["phase"] == "flop"

    db.close()


def test_game_store_record_hand_result() -> None:
    db = Database.in_memory()
    store = GameStore(db)
    game_id = store.create_game(room_id=9, strategy_name="gto")

    store.record_hand_result(
        game_id=game_id,
        room_id=9,
        hand_number=7,
        pot=320,
        won=1,
        community_cards="Ah,Kd,7s,2c,2d",
    )

    row = db.execute("SELECT * FROM hand_results WHERE game_id=?", (game_id,)).fetchone()

    assert row is not None
    assert row["hand_number"] == 7
    assert row["pot"] == 320
    assert row["won"] == 1
    assert row["community_cards"] == "Ah,Kd,7s,2c,2d"

    db.close()


def test_game_store_get_count() -> None:
    db = Database.in_memory()
    store = GameStore(db)

    store.create_game(room_id=1, strategy_name="tag")
    store.create_game(room_id=2, strategy_name="tag")
    store.create_game(room_id=3, strategy_name="gto")

    assert store.get_game_count() == 3
    assert store.get_game_count("tag") == 2
    assert store.get_game_count("gto") == 1
    assert store.get_avg_rank("unknown") == 0.0

    db.close()


def test_strategy_store_save_and_get() -> None:
    db = Database.in_memory()
    store = StrategyStore(db)
    genome = _sample_genome()

    version_id = store.save_version(
        name="tag",
        version=1,
        genome=genome,
        origin="manual",
    )

    latest = store.get_latest_version("tag")
    exact = store.get_version("tag", 1)

    assert version_id > 0
    assert latest is not None
    assert exact is not None
    assert latest["id"] == version_id
    assert latest["name"] == "tag"
    assert latest["version"] == 1
    assert exact["origin"] == "manual"

    db.close()


def test_strategy_store_get_genome() -> None:
    db = Database.in_memory()
    store = StrategyStore(db)
    genome = _sample_genome()

    store.save_version(name="tag", version=1, genome=genome)

    restored = store.get_genome("tag")

    assert restored == genome

    db.close()


def test_strategy_store_next_version() -> None:
    db = Database.in_memory()
    store = StrategyStore(db)

    assert store.get_next_version("tag") == 1

    store.save_version(name="tag", version=1, genome=_sample_genome())
    store.save_version(name="tag", version=2, genome=_sample_genome())

    assert store.get_next_version("tag") == 3

    db.close()


def test_strategy_store_update_stats() -> None:
    db = Database.in_memory()
    store = StrategyStore(db)

    store.save_version(name="tag", version=1, genome=_sample_genome())
    store.update_stats(name="tag", version=1, games_played=24, win_rate=0.375)

    updated = store.get_version("tag", 1)

    assert updated is not None
    assert updated["games_played"] == 24
    assert updated["win_rate"] == 0.375

    db.close()


def test_metrics_store_summary() -> None:
    db = Database.in_memory()
    game_store = GameStore(db)
    metrics = MetricsStore(db)

    game_one = game_store.create_game(room_id=1, strategy_name="tag")
    game_two = game_store.create_game(room_id=2, strategy_name="tag")

    game_store.finish_game(game_one, final_rank=1, final_chips=2500, total_hands=10)
    game_store.finish_game(game_two, final_rank=3, final_chips=400, total_hands=14)

    game_store.record_decision(game_one, 1, 1, "raise", 60, "Open", "tag", "preflop", 30, 10, 1500)
    game_store.record_decision(game_one, 1, 2, "call", 40, "Defend", "tag", "flop", 120, 40, 1440)
    game_store.record_decision(game_two, 2, 1, "fold", None, "No equity", "tag", "turn", 200, 80, 900)

    summary = metrics.get_strategy_summary("tag")

    assert summary == {
        "strategy_name": "tag",
        "games_played": 2,
        "win_rate": 0.5,
        "avg_rank": 2.0,
        "total_hands": 24,
        "total_decisions": 3,
        "folds": 1,
        "raises": 1,
        "calls": 1,
    }

    db.close()


def test_metrics_store_action_distribution() -> None:
    db = Database.in_memory()
    game_store = GameStore(db)
    metrics = MetricsStore(db)
    game_id = game_store.create_game(room_id=1, strategy_name="gto")

    game_store.record_decision(game_id, 1, 1, "raise", 80, "Open", "gto", "preflop", 30, 10, 2000)
    game_store.record_decision(game_id, 1, 2, "raise", 120, "Barrel", "gto", "flop", 160, 0, 1920)
    game_store.record_decision(game_id, 1, 3, "call", 60, "Pot odds", "gto", "turn", 240, 60, 1800)

    distribution = metrics.get_action_distribution("gto")

    assert distribution == {"call": 1, "raise": 2}

    db.close()
