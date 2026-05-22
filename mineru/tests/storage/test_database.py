from __future__ import annotations

# pyright: reportMissingImports=false

import sqlite3

import pytest

from holdem_agent.storage.database import Database


def test_in_memory_creation() -> None:
    db = Database.in_memory()

    assert db.conn is not None
    assert db.conn.row_factory is sqlite3.Row

    db.close()


def test_tables_created() -> None:
    db = Database.in_memory()

    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
    ).fetchall()

    assert {row["name"] for row in rows} == {
        "decisions",
        "games",
        "hand_results",
        "strategy_versions",
    }

    db.close()


def test_insert_and_query() -> None:
    db = Database.in_memory()

    cursor = db.execute(
        "INSERT INTO games (room_id, strategy_name, started_at) VALUES (?, ?, ?)",
        (10, "baseline", "2026-04-18T00:00:00+00:00"),
    )
    db.commit()

    row = db.execute("SELECT * FROM games WHERE id=?", (cursor.lastrowid,)).fetchone()

    assert row is not None
    assert row["room_id"] == 10
    assert row["strategy_name"] == "baseline"

    db.close()


def test_foreign_keys_enforced() -> None:
    db = Database.in_memory()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO decisions "
            "(game_id, room_id, hand_number, action_type, strategy_name, phase, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (999, 1, 1, "fold", "baseline", "preflop", "2026-04-18T00:00:00+00:00"),
        )

    db.close()


def test_context_manager() -> None:
    with Database(":memory:") as db:
        row = db.execute("SELECT 1 AS value").fetchone()
        assert row is not None
        assert row["value"] == 1

    with pytest.raises(RuntimeError, match="Database not connected"):
        _ = db.conn
