from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    """SQLite database with schema management."""

    def __init__(self, path: str = "db/holdem.db") -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def in_memory(cls) -> "Database":
        """Create an in-memory database for testing."""
        db = cls(":memory:")
        db.connect()
        return db

    def connect(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executescript(self, sql: str) -> None:
        self.conn.executescript(sql)

    def commit(self) -> None:
        self.conn.commit()

    def _migrate(self) -> None:
        self.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                strategy_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                final_rank INTEGER,
                final_chips INTEGER,
                total_hands INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER REFERENCES games(id),
                room_id INTEGER NOT NULL,
                hand_number INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                amount INTEGER,
                reasoning TEXT DEFAULT '',
                strategy_name TEXT NOT NULL,
                phase TEXT NOT NULL,
                pot INTEGER DEFAULT 0,
                to_call INTEGER DEFAULT 0,
                my_stack INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hand_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER REFERENCES games(id),
                room_id INTEGER NOT NULL,
                hand_number INTEGER NOT NULL,
                pot INTEGER NOT NULL,
                won INTEGER DEFAULT 0,
                community_cards TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                genome_json TEXT NOT NULL,
                origin TEXT DEFAULT 'manual',
                parent_name TEXT,
                parent_version INTEGER,
                games_played INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_games_strategy ON games(strategy_name);
            CREATE INDEX IF NOT EXISTS idx_decisions_game ON decisions(game_id);
            CREATE INDEX IF NOT EXISTS idx_hand_results_game ON hand_results(game_id);
            CREATE INDEX IF NOT EXISTS idx_strategy_versions_name ON strategy_versions(name, version);
            """
        )
        self.commit()

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
