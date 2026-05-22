from __future__ import annotations

import json
from datetime import datetime, timezone

from holdem_agent.storage.database import Database
from holdem_agent.strategy.genome import StrategyGenome


class StrategyStore:
    """CRUD for strategy versions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save_version(
        self,
        name: str,
        version: int,
        genome: StrategyGenome,
        origin: str = "manual",
        parent_name: str | None = None,
        parent_version: int | None = None,
    ) -> int:
        cursor = self._db.execute(
            """INSERT INTO strategy_versions
               (name, version, genome_json, origin, parent_name, parent_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                version,
                json.dumps(genome.to_dict()),
                origin,
                parent_name,
                parent_version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_latest_version(self, name: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM strategy_versions WHERE name=? ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        return dict(row) if row else None

    def get_version(self, name: str, version: int) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM strategy_versions WHERE name=? AND version=?",
            (name, version),
        ).fetchone()
        return dict(row) if row else None

    def get_genome(self, name: str, version: int | None = None) -> StrategyGenome | None:
        entry = self.get_version(name, version) if version is not None else self.get_latest_version(name)
        if entry and "genome_json" in entry:
            return StrategyGenome.from_dict(json.loads(entry["genome_json"]))
        return None

    def update_stats(self, name: str, version: int, games_played: int, win_rate: float) -> None:
        self._db.execute(
            "UPDATE strategy_versions SET games_played=?, win_rate=? WHERE name=? AND version=?",
            (games_played, win_rate, name, version),
        )
        self._db.commit()

    def list_versions(self, name: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM strategy_versions WHERE name=? ORDER BY version",
            (name,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_next_version(self, name: str) -> int:
        row = self._db.execute(
            "SELECT MAX(version) FROM strategy_versions WHERE name=?",
            (name,),
        ).fetchone()
        return (row[0] or 0) + 1
