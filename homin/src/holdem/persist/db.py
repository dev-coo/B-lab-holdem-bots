"""SQLite 영속 — PlayerProfile 을 세션 간 저장/복원.

근거: plan P4 (전역·영속 프로필), D3 Day 20.

스키마 (단일 파일, 한 테이블):
    opponent_profile(
        name         TEXT PRIMARY KEY,
        hands_seen   REAL NOT NULL DEFAULT 0,
        metrics_json TEXT NOT NULL,         -- {metric: {alpha, beta}}
        agg_aggressive REAL NOT NULL DEFAULT 0,
        agg_passive    REAL NOT NULL DEFAULT 0,
        updated_at   TEXT NOT NULL
    )

단순화: 전량 JSON 으로 보관. 메트릭 종류는 PlayerProfile.METRIC_KEYS 와 동일.
추후 metric 별 조회가 필요하면 join 테이블로 재설계.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..estimate.bayes import DirichletResponse
from ..state.player_profile import AggressionCounter, BetaCounter, PlayerProfile
from ..state.profile_store import ProfileStore
from ..state.response_store import ResponseStore

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opponent_profile (
    name           TEXT PRIMARY KEY,
    hands_seen     REAL NOT NULL DEFAULT 0,
    metrics_json   TEXT NOT NULL,
    agg_aggressive REAL NOT NULL DEFAULT 0,
    agg_passive    REAL NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opponent_response (
    name         TEXT NOT NULL,
    phase        TEXT NOT NULL,
    alpha_fold   REAL NOT NULL DEFAULT 1.0,
    alpha_call   REAL NOT NULL DEFAULT 1.0,
    alpha_raise  REAL NOT NULL DEFAULT 1.0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (name, phase)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    return conn


def _metrics_to_json(metrics: dict[str, BetaCounter]) -> str:
    return json.dumps({k: asdict(v) for k, v in metrics.items()}, separators=(",", ":"))


def _metrics_from_json(s: str) -> dict[str, BetaCounter]:
    raw = json.loads(s) or {}
    out: dict[str, BetaCounter] = {}
    for k, v in raw.items():
        out[k] = BetaCounter(alpha=float(v.get("alpha", 0.0)), beta=float(v.get("beta", 0.0)))
    return out


def save_profile(conn: sqlite3.Connection, prof: PlayerProfile) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO opponent_profile (name, hands_seen, metrics_json,
                                       agg_aggressive, agg_passive, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            hands_seen     = excluded.hands_seen,
            metrics_json   = excluded.metrics_json,
            agg_aggressive = excluded.agg_aggressive,
            agg_passive    = excluded.agg_passive,
            updated_at     = excluded.updated_at
        """,
        (
            prof.name,
            float(prof.hands_seen),
            _metrics_to_json(prof.metrics),
            float(prof.aggression.aggressive),
            float(prof.aggression.passive),
            now,
        ),
    )


def load_profile(conn: sqlite3.Connection, name: str) -> PlayerProfile | None:
    row = conn.execute(
        """SELECT hands_seen, metrics_json, agg_aggressive, agg_passive
             FROM opponent_profile WHERE name = ?""",
        (name,),
    ).fetchone()
    if row is None:
        return None
    hands_seen, metrics_json, aggr, passv = row
    return PlayerProfile(
        name=name,
        hands_seen=int(hands_seen) if float(hands_seen).is_integer() else float(hands_seen),
        metrics=_metrics_from_json(metrics_json),
        aggression=AggressionCounter(aggressive=float(aggr), passive=float(passv)),
    )


def save_store(conn: sqlite3.Connection, store: ProfileStore) -> int:
    """store 전체를 flush (profiles + responses). 반환값: 저장된 profile 수."""
    n = 0
    for prof in store.profiles.values():
        save_profile(conn, prof)
        n += 1
    save_response_store(conn, store.responses)
    return n


def load_store(conn: sqlite3.Connection) -> ProfileStore:
    store = ProfileStore()
    rows = conn.execute(
        """SELECT name, hands_seen, metrics_json, agg_aggressive, agg_passive
             FROM opponent_profile"""
    ).fetchall()
    for name, hands_seen, metrics_json, aggr, passv in rows:
        prof = PlayerProfile(
            name=name,
            hands_seen=int(hands_seen) if float(hands_seen).is_integer() else float(hands_seen),
            metrics=_metrics_from_json(metrics_json),
            aggression=AggressionCounter(aggressive=float(aggr), passive=float(passv)),
        )
        store.profiles[name] = prof
    store.responses = load_response_store(conn)
    return store


def save_response(conn: sqlite3.Connection, name: str, phase: str, r: DirichletResponse) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO opponent_response (name, phase, alpha_fold, alpha_call, alpha_raise, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, phase) DO UPDATE SET
            alpha_fold  = excluded.alpha_fold,
            alpha_call  = excluded.alpha_call,
            alpha_raise = excluded.alpha_raise,
            updated_at  = excluded.updated_at
        """,
        (name, phase, float(r.alpha_fold), float(r.alpha_call), float(r.alpha_raise), now),
    )


def save_response_store(conn: sqlite3.Connection, store: ResponseStore) -> int:
    n = 0
    for (name, phase), r in store.table.items():
        save_response(conn, name, phase, r)
        n += 1
    return n


def load_response_store(conn: sqlite3.Connection) -> ResponseStore:
    store = ResponseStore()
    rows = conn.execute(
        """SELECT name, phase, alpha_fold, alpha_call, alpha_raise FROM opponent_response"""
    ).fetchall()
    for name, phase, af, ac, ar in rows:
        store.table[(name, phase)] = DirichletResponse(
            alpha_fold=float(af),
            alpha_call=float(ac),
            alpha_raise=float(ar),
        )
    return store
