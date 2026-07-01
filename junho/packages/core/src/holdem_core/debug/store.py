"""SQLite 기반 디버그 데이터 저장소.

이전에는 `.debug/` 아래에 다음 파일을 흩뿌렸었다:
- `room_{id}.jsonl`         : WS 이벤트 raw 스트림 (DebugDumper)
- `summary_{room}_{run}.json`: 세션 요약 (SummaryWriter)
- `opponent_profiles.json`  : 누적 상대 프로필 (SummaryWriter)
- `bluff_prior.json`        : 뻥카 Beta posterior (BluffPriorStore)

본 모듈은 같은 데이터를 단일 SQLite DB (`{base_dir}/holdem.db`) 로 모은다.
- WAL 저널 모드 — 동시에 여러 프로세스가 read 가능, single writer
- `iter_events()` 는 기존 JSONL record dict 와 같은 shape 의 dict 를 yield 하므로
  loader/dashboard 등 컨슈머는 거의 그대로 동작.
- 변경/삽입은 모두 짧은 transaction 내에서 수행. tmp+rename 원자성 동등.

병행 안전성
-----------
같은 DB 에 봇 프로세스(write) + 분석 CLI(read+write) + Streamlit(read) 가 붙을
수 있다. WAL + `busy_timeout=5000ms` + 짧은 트랜잭션으로 충돌을 흡수한다. 봇별
로 `DEBUG_DIR` 이 분리되면 DB 파일도 분리되어 경합이 사실상 사라진다.

JSONL 호환
----------
기본은 SQLite 단일 적재. `HOLDEM_DEBUG_JSONL=1` 로 명시 켜면 JSONL/JSON 파일도
함께 쓴다(긴급 백업/디버그용). 본 store 는 JSONL 을 직접 다루지 않는다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from holdem_core.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA_VERSION = 1
_DB_FILENAME = "holdem.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    run_id TEXT,
    bot_name TEXT,
    room_id INTEGER,
    direction TEXT NOT NULL,           -- 'in' | 'out' | 'marker'
    event_type TEXT,                   -- inbound: hand_start/action_request/...
    kind TEXT,                         -- outbound: action/auth/...
    hand_number INTEGER,
    phase TEXT,
    raw_text TEXT,                     -- inbound only
    payload_json TEXT,                 -- parsed payload / event dump
    meta_json TEXT                     -- outbound action only
);
CREATE INDEX IF NOT EXISTS idx_events_room_ts ON events(room_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_room_run ON events(room_id, run_id, id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_room_type ON events(room_id, event_type, id);
CREATE INDEX IF NOT EXISTS idx_events_room_dir_kind
    ON events(room_id, direction, kind, id);

CREATE TABLE IF NOT EXISTS session_summaries (
    room_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    started_at REAL,
    ended_at REAL,
    total_hands INTEGER,
    participated_hands INTEGER,
    vpip REAL, pfr REAL,
    showdowns INTEGER, showdowns_won INTEGER, showdown_win_rate REAL,
    final_rank INTEGER, final_chips INTEGER,
    max_stack INTEGER, min_stack INTEGER,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (room_id, run_id, bot_name)
);

CREATE TABLE IF NOT EXISTS opponent_profiles (
    player_name TEXT PRIMARY KEY,
    hands_seen INTEGER NOT NULL DEFAULT 0,
    vpip_n INTEGER NOT NULL DEFAULT 0,
    pfr_n INTEGER NOT NULL DEFAULT 0,
    threebet_n INTEGER NOT NULL DEFAULT 0,
    showdown_n INTEGER NOT NULL DEFAULT 0,
    showdown_won_n INTEGER NOT NULL DEFAULT 0,
    made_hand_histogram_json TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bluff_priors (
    player TEXT NOT NULL,
    street TEXT NOT NULL,
    sizing TEXT NOT NULL,
    action_type TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta REAL NOT NULL,
    n REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (player, street, sizing, action_type)
);
"""


def default_db_path(base_dir: str | Path) -> Path:
    """`{base_dir}/holdem.db` 경로 반환."""
    return Path(base_dir) / _DB_FILENAME


class DebugStore:
    """SQLite 백엔드. thread-safe (RLock) — 단일 connection 을 여러 thread 가 공유.

    - `open()` 으로 생성. WAL 모드 + busy_timeout 자동 적용.
    - read/write 모두 같은 인스턴스 사용 가능.
    - 프로세스 종료 시 `close()` 권장 (최소 WAL 체크포인트 + connection 해제).
    """

    def __init__(self, conn: sqlite3.Connection, db_path: Path, read_only: bool) -> None:
        self._conn = conn
        self._db_path = db_path
        self._read_only = read_only
        self._lock = threading.RLock()

    # ── lifecycle ───────────────────────────────────────────────────────────

    @classmethod
    def open(
        cls,
        base_dir: str | Path,
        *,
        read_only: bool = False,
        db_filename: str | None = None,
    ) -> DebugStore:
        """`{base_dir}/holdem.db` 를 열고 (없으면 만들고) 스키마 적용."""
        base = Path(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        db_path = base / (db_filename or _DB_FILENAME)
        if read_only and not db_path.exists():
            # read-only 인데 파일 없으면 빈 DB 를 만들지 않고 실패 모드로 만든다.
            # 호출자가 fallback 가능하도록 None 대신 raise.
            raise FileNotFoundError(f"DebugStore read-only but db missing: {db_path}")
        if read_only:
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5.0)
        else:
            conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # WAL + 동시성 관련 PRAGMA. read-only 일 때는 일부 PRAGMA 무시되어도 무해.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.OperationalError as e:
            logger.warning("debug_store_pragma_failed", extra={"error": repr(e)})
        store = cls(conn=conn, db_path=db_path, read_only=read_only)
        if not read_only:
            store._init_schema()
        return store

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version(version) VALUES(?)", (_SCHEMA_VERSION,)
                )
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                if not self._read_only:
                    try:
                        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except sqlite3.OperationalError:
                        pass
                self._conn.close()
            except sqlite3.Error:
                pass

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── event recording ─────────────────────────────────────────────────────

    def record_marker(
        self,
        run_id: str,
        bot_name: str | None,
        room_id: int | None = None,
        ts: float | None = None,
    ) -> None:
        """`_run_started` 마커 기록."""
        if self._read_only:
            return
        ts = ts if ts is not None else time.time()
        payload = {"_run_started": ts, "run_id": run_id, "bot_name": bot_name}
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO events(ts, run_id, bot_name, room_id, direction,"
                    " event_type, payload_json) VALUES(?,?,?,?,?,?,?)",
                    (
                        ts,
                        run_id,
                        bot_name,
                        room_id,
                        "marker",
                        "_run_started",
                        json.dumps(payload, ensure_ascii=False, default=str),
                    ),
                )
        except sqlite3.Error as e:
            logger.warning("debug_store_marker_failed", extra={"error": repr(e)})

    def record_inbound(
        self,
        *,
        run_id: str | None,
        room_id: int | None,
        evt_type: str | None,
        raw_text: str | None,
        payload: dict[str, Any] | None,
        bot_name: str | None = None,
        hand_number: int | None = None,
        phase: str | None = None,
        ts: float | None = None,
    ) -> None:
        if self._read_only:
            return
        ts = ts if ts is not None else time.time()
        # payload 에서 hand_number/phase 자동 추출 (없을 때)
        if hand_number is None and isinstance(payload, dict):
            hn = payload.get("hand_number")
            if isinstance(hn, int):
                hand_number = hn
        if phase is None and isinstance(payload, dict):
            ph = payload.get("phase")
            if isinstance(ph, str):
                phase = ph
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO events(ts, run_id, bot_name, room_id, direction,"
                    " event_type, hand_number, phase, raw_text, payload_json)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts,
                        run_id,
                        bot_name,
                        room_id,
                        "in",
                        evt_type,
                        hand_number,
                        phase,
                        raw_text,
                        json.dumps(payload, ensure_ascii=False, default=str)
                        if payload is not None
                        else None,
                    ),
                )
        except sqlite3.Error as e:
            logger.warning("debug_store_inbound_failed", extra={"error": repr(e)})

    def record_outbound(
        self,
        *,
        run_id: str | None,
        room_id: int | None,
        kind: str | None,
        payload: Any,
        meta: dict[str, Any] | None = None,
        bot_name: str | None = None,
        hand_number: int | None = None,
        phase: str | None = None,
        ts: float | None = None,
    ) -> None:
        if self._read_only:
            return
        ts = ts if ts is not None else time.time()
        if isinstance(payload, dict):
            payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        elif payload is None:
            payload_json = None
        else:
            # 문자열 등 raw 그대로 저장 (parse 실패 케이스)
            payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        if phase is None and isinstance(meta, dict):
            ph = meta.get("phase")
            if isinstance(ph, str):
                phase = ph
        # outbound action 의 hand_number 는 meta 에서 추출 (payload 에 없는 경우 多).
        # 이게 없으면 VPIP/PFR 등 hand 단위 SQL 집계가 모두 실패.
        if hand_number is None and isinstance(meta, dict):
            hn = meta.get("hand_number")
            if isinstance(hn, int):
                hand_number = hn
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO events(ts, run_id, bot_name, room_id, direction,"
                    " kind, hand_number, phase, payload_json, meta_json)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts,
                        run_id,
                        bot_name,
                        room_id,
                        "out",
                        kind,
                        hand_number,
                        phase,
                        payload_json,
                        json.dumps(meta, ensure_ascii=False, default=str)
                        if meta is not None
                        else None,
                    ),
                )
        except sqlite3.Error as e:
            logger.warning("debug_store_outbound_failed", extra={"error": repr(e)})

    # ── event reading (JSONL-shape compatible) ─────────────────────────────

    def iter_events(
        self,
        *,
        room_id: int | None = None,
        run_id: str | None = None,
        include_markers: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """events 테이블을 JSONL record 와 같은 dict shape 로 반환.

        - inbound:  `{ts, run_id, dir:"in", type, room_id, raw, event}`
        - outbound: `{ts, run_id, dir:"out", kind, room_id, payload, meta}`
        - marker:   `{ts, run_id, _run_started, bot_name}`

        loader.iter_jsonl 와 호환되도록 의도. 정렬은 `id ASC` (삽입 순서).
        """
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if room_id is not None:
            sql += " AND room_id = ?"
            params.append(room_id)
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if not include_markers:
            sql += " AND direction != 'marker'"
        sql += " ORDER BY id ASC"
        with self._lock:
            cur = self._conn.execute(sql, params)
            for row in cur:
                yield _row_to_record(row)

    def fetch_events(
        self,
        *,
        room_id: int | None = None,
        run_id: str | None = None,
        include_markers: bool = True,
    ) -> list[dict[str, Any]]:
        return list(
            self.iter_events(
                room_id=room_id, run_id=run_id, include_markers=include_markers
            )
        )

    def list_rooms(self) -> list[int]:
        """events 에 한 번이라도 등장한 room_id 목록."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT room_id FROM events"
                " WHERE room_id IS NOT NULL ORDER BY room_id ASC"
            )
            return [int(row[0]) for row in cur if row[0] is not None]

    def list_run_ids(self, room_id: int | None = None) -> list[str]:
        sql = "SELECT DISTINCT run_id FROM events WHERE run_id IS NOT NULL"
        params: list[Any] = []
        if room_id is not None:
            sql += " AND room_id = ?"
            params.append(room_id)
        sql += " ORDER BY run_id"
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [str(row[0]) for row in cur]

    def list_room_run_pairs(self) -> list[tuple[int, str]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT room_id, run_id FROM events"
                " WHERE room_id IS NOT NULL AND run_id IS NOT NULL"
                " ORDER BY room_id, run_id"
            )
            return [(int(r[0]), str(r[1])) for r in cur]

    # ── session summaries ──────────────────────────────────────────────────

    def upsert_summary(self, summary: dict[str, Any]) -> None:
        """summary dict (holdem_core.debug.summary._build_summary 결과) 를 저장."""
        if self._read_only:
            return
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO session_summaries(room_id, run_id, bot_name,"
                    " started_at, ended_at, total_hands, participated_hands,"
                    " vpip, pfr, showdowns, showdowns_won, showdown_win_rate,"
                    " final_rank, final_chips, max_stack, min_stack, data_json,"
                    " updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(room_id, run_id, bot_name) DO UPDATE SET"
                    " started_at=excluded.started_at,"
                    " ended_at=excluded.ended_at,"
                    " total_hands=excluded.total_hands,"
                    " participated_hands=excluded.participated_hands,"
                    " vpip=excluded.vpip, pfr=excluded.pfr,"
                    " showdowns=excluded.showdowns,"
                    " showdowns_won=excluded.showdowns_won,"
                    " showdown_win_rate=excluded.showdown_win_rate,"
                    " final_rank=excluded.final_rank,"
                    " final_chips=excluded.final_chips,"
                    " max_stack=excluded.max_stack, min_stack=excluded.min_stack,"
                    " data_json=excluded.data_json,"
                    " updated_at=excluded.updated_at",
                    (
                        int(summary.get("room_id") or 0),
                        str(summary.get("run_id") or ""),
                        str(summary.get("bot_name") or ""),
                        summary.get("started_at"),
                        summary.get("ended_at"),
                        summary.get("total_hands"),
                        summary.get("participated_hands"),
                        summary.get("vpip"),
                        summary.get("pfr"),
                        summary.get("showdowns"),
                        summary.get("showdowns_won"),
                        summary.get("showdown_win_rate"),
                        summary.get("final_rank"),
                        summary.get("final_chips"),
                        summary.get("max_stack"),
                        summary.get("min_stack"),
                        json.dumps(summary, ensure_ascii=False, default=str),
                        time.time(),
                    ),
                )
        except sqlite3.Error as e:
            logger.warning("debug_store_summary_upsert_failed", extra={"error": repr(e)})

    def get_summary(
        self, room_id: int, run_id: str, bot_name: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json FROM session_summaries"
                " WHERE room_id=? AND run_id=? AND bot_name=?",
                (int(room_id), str(run_id), str(bot_name)),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def list_summaries(
        self, room_id: int | None = None, bot_name: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT data_json FROM session_summaries WHERE 1=1"
        params: list[Any] = []
        if room_id is not None:
            sql += " AND room_id=?"
            params.append(int(room_id))
        if bot_name is not None:
            sql += " AND bot_name=?"
            params.append(bot_name)
        sql += " ORDER BY started_at"
        out: list[dict[str, Any]] = []
        with self._lock:
            for row in self._conn.execute(sql, params):
                try:
                    out.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    continue
        return out

    # ── opponent profiles ──────────────────────────────────────────────────

    def merge_opponent_profile(self, name: str, delta: dict[str, Any]) -> None:
        """이 핸드의 카운트를 누적. SummaryWriter._merge_profiles 와 동일 의미."""
        if self._read_only:
            return
        try:
            with self._lock, self._conn:
                cur = self._conn.execute(
                    "SELECT hands_seen, vpip_n, pfr_n, threebet_n, showdown_n,"
                    " showdown_won_n, made_hand_histogram_json"
                    " FROM opponent_profiles WHERE player_name=?",
                    (name,),
                )
                row = cur.fetchone()
                if row is None:
                    base = {
                        "hands_seen": 0,
                        "vpip_n": 0,
                        "pfr_n": 0,
                        "threebet_n": 0,
                        "showdown_n": 0,
                        "showdown_won_n": 0,
                        "made_hand_histogram": {},
                    }
                else:
                    try:
                        hist = json.loads(row["made_hand_histogram_json"] or "{}")
                    except json.JSONDecodeError:
                        hist = {}
                    base = {
                        "hands_seen": int(row["hands_seen"] or 0),
                        "vpip_n": int(row["vpip_n"] or 0),
                        "pfr_n": int(row["pfr_n"] or 0),
                        "threebet_n": int(row["threebet_n"] or 0),
                        "showdown_n": int(row["showdown_n"] or 0),
                        "showdown_won_n": int(row["showdown_won_n"] or 0),
                        "made_hand_histogram": hist if isinstance(hist, dict) else {},
                    }

                base["hands_seen"] += int(delta.get("hands_seen", 0))
                base["vpip_n"] += int(delta.get("vpip_n", 0))
                base["pfr_n"] += int(delta.get("pfr_n", 0))
                base["threebet_n"] += int(delta.get("threebet_n", 0))
                sd_n = delta.get("showdown_n")
                if sd_n is None:
                    sd_n = delta.get("showdowns", 0)
                base["showdown_n"] += int(sd_n or 0)
                base["showdown_won_n"] += int(delta.get("showdown_won_n", 0) or 0)
                hist = base["made_hand_histogram"]
                for cat, cnt in (delta.get("made_hand_histogram") or {}).items():
                    hist[str(cat)] = int(hist.get(str(cat), 0)) + int(cnt or 0)

                self._conn.execute(
                    "INSERT INTO opponent_profiles(player_name, hands_seen, vpip_n,"
                    " pfr_n, threebet_n, showdown_n, showdown_won_n,"
                    " made_hand_histogram_json, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(player_name) DO UPDATE SET"
                    " hands_seen=excluded.hands_seen,"
                    " vpip_n=excluded.vpip_n,"
                    " pfr_n=excluded.pfr_n,"
                    " threebet_n=excluded.threebet_n,"
                    " showdown_n=excluded.showdown_n,"
                    " showdown_won_n=excluded.showdown_won_n,"
                    " made_hand_histogram_json=excluded.made_hand_histogram_json,"
                    " updated_at=excluded.updated_at",
                    (
                        name,
                        base["hands_seen"],
                        base["vpip_n"],
                        base["pfr_n"],
                        base["threebet_n"],
                        base["showdown_n"],
                        base["showdown_won_n"],
                        json.dumps(base["made_hand_histogram"], ensure_ascii=False),
                        time.time(),
                    ),
                )
        except sqlite3.Error as e:
            logger.warning(
                "debug_store_profile_merge_failed",
                extra={"error": repr(e), "player": name},
            )

    def reset_opponent_profiles(self) -> None:
        """오프라인 재집계 시 중복 누적 방지용."""
        if self._read_only:
            return
        try:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM opponent_profiles")
        except sqlite3.Error as e:
            logger.warning("debug_store_profile_reset_failed", extra={"error": repr(e)})

    def get_opponent_profiles(self) -> dict[str, dict[str, Any]]:
        """`{name: profile_data}` 반환 — strategy._load_opponent_profiles 가 기대하는 shape."""
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            cur = self._conn.execute(
                "SELECT player_name, hands_seen, vpip_n, pfr_n, threebet_n,"
                " showdown_n, showdown_won_n, made_hand_histogram_json, updated_at"
                " FROM opponent_profiles"
            )
            for row in cur:
                try:
                    hist = json.loads(row["made_hand_histogram_json"] or "{}")
                except json.JSONDecodeError:
                    hist = {}
                out[row["player_name"]] = {
                    "hands_seen": int(row["hands_seen"] or 0),
                    "vpip_n": int(row["vpip_n"] or 0),
                    "pfr_n": int(row["pfr_n"] or 0),
                    "threebet_n": int(row["threebet_n"] or 0),
                    "showdown_n": int(row["showdown_n"] or 0),
                    "showdown_won_n": int(row["showdown_won_n"] or 0),
                    "made_hand_histogram": hist if isinstance(hist, dict) else {},
                    "last_updated": row["updated_at"],
                }
        return out

    # ── bluff priors ───────────────────────────────────────────────────────

    def upsert_bluff_prior(
        self,
        player: str,
        street: str,
        sizing: str,
        action_type: str,
        alpha: float,
        beta: float,
        n: float,
    ) -> None:
        if self._read_only:
            return
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO bluff_priors(player, street, sizing, action_type,"
                    " alpha, beta, n, updated_at) VALUES(?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(player, street, sizing, action_type) DO UPDATE SET"
                    " alpha=excluded.alpha, beta=excluded.beta, n=excluded.n,"
                    " updated_at=excluded.updated_at",
                    (
                        player,
                        street,
                        sizing,
                        action_type,
                        float(alpha),
                        float(beta),
                        float(n),
                        time.time(),
                    ),
                )
        except sqlite3.Error as e:
            logger.warning("debug_store_bluff_upsert_failed", extra={"error": repr(e)})

    def all_bluff_priors(self) -> dict[str, dict[str, float]]:
        """`{f"{player}|{street}|{sizing}|{atype}": {alpha,beta,n}}` 반환."""
        out: dict[str, dict[str, float]] = {}
        with self._lock:
            cur = self._conn.execute(
                "SELECT player, street, sizing, action_type, alpha, beta, n"
                " FROM bluff_priors"
            )
            for row in cur:
                key = f"{row['player']}|{row['street']}|{row['sizing']}|{row['action_type']}"
                out[key] = {
                    "alpha": float(row["alpha"]),
                    "beta": float(row["beta"]),
                    "n": float(row["n"]),
                }
        return out

    def reset_bluff_priors(self) -> None:
        if self._read_only:
            return
        try:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM bluff_priors")
        except sqlite3.Error as e:
            logger.warning("debug_store_bluff_reset_failed", extra={"error": repr(e)})

    # ── dashboard 집계 (SQL-side, JSON1 사용) ─────────────────────────────

    def list_hand_numbers(self, room_id: int) -> list[int]:
        """방의 hand_start 이벤트들에서 hand_number 추출 (오름차순)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT hand_number FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start'"
                " AND hand_number IS NOT NULL"
                " ORDER BY hand_number ASC",
                (int(room_id),),
            )
            return [int(r[0]) for r in cur if r[0] is not None]

    def fetch_hand_events(
        self, room_id: int, hand_number: int
    ) -> list[dict[str, Any]]:
        """특정 핸드의 이벤트만 (hand_start ~ 다음 hand_start 직전).

        hand_number 가 NULL 인 phase_change/hand_result 도 id 범위로 포함.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(id) FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start' AND hand_number = ?",
                (int(room_id), int(hand_number)),
            ).fetchone()
            start_id = row[0] if row else None
            if start_id is None:
                return []
            row2 = self._conn.execute(
                "SELECT MIN(id) FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start' AND hand_number > ?",
                (int(room_id), int(hand_number)),
            ).fetchone()
            next_id = row2[0] if row2 else None
            if next_id is None:
                cur = self._conn.execute(
                    "SELECT * FROM events WHERE room_id = ? AND id >= ?"
                    " ORDER BY id ASC",
                    (int(room_id), int(start_id)),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM events WHERE room_id = ? AND id >= ? AND id < ?"
                    " ORDER BY id ASC",
                    (int(room_id), int(start_id), int(next_id)),
                )
            return [_row_to_record(r) for r in cur]

    def detect_bot_name(self, room_id: int | None = None) -> str | None:
        """marker 의 bot_name → 없으면 첫 hand_start 의 your_seat 매칭."""
        with self._lock:
            row = self._conn.execute(
                "SELECT bot_name FROM events"
                " WHERE bot_name IS NOT NULL AND bot_name != ''"
                " ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return str(row[0])

            sql = (
                "SELECT json_extract(payload_json, '$.your_seat') AS seat,"
                " payload_json"
                " FROM events WHERE event_type = 'hand_start'"
            )
            params: list[Any] = []
            if room_id is not None:
                sql += " AND room_id = ?"
                params.append(int(room_id))
            sql += " ORDER BY id ASC LIMIT 1"
            row = self._conn.execute(sql, params).fetchone()
            if not row or not row["payload_json"]:
                return None
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                return None
            seat = row["seat"]
            for p in payload.get("players") or []:
                if isinstance(p, dict) and p.get("position") == seat and p.get("name"):
                    return str(p["name"])
        return None

    def fetch_hand_starts(self, room_id: int) -> list[dict[str, Any]]:
        """hand_start 페이로드의 핵심 필드만 한 번에."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, ts, hand_number,"
                " json_extract(payload_json, '$.your_cards') AS your_cards_json,"
                " json_extract(payload_json, '$.your_seat') AS seat,"
                " json_extract(payload_json, '$.your_stack') AS start_stack,"
                " json_extract(payload_json, '$.blind') AS blind_json,"
                " json_extract(payload_json, '$.players') AS players_json"
                " FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start'"
                " ORDER BY hand_number ASC",
                (int(room_id),),
            )
            out: list[dict[str, Any]] = []
            for r in cur:
                out.append(
                    {
                        "ts": r["ts"],
                        "hand_number": r["hand_number"],
                        "your_cards": _safe_json(r["your_cards_json"]) or [],
                        "seat": r["seat"],
                        "start_stack": r["start_stack"],
                        "blind": _safe_json(r["blind_json"]) or [],
                        "players": _safe_json(r["players_json"]) or [],
                    }
                )
            return out

    def fetch_hand_results(self, room_id: int) -> list[dict[str, Any]]:
        """hand_result 페이로드 핵심 필드만 한 번에."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT hand_number,"
                " json_extract(payload_json, '$.community_cards') AS board_json,"
                " json_extract(payload_json, '$.winners') AS winners_json,"
                " json_extract(payload_json, '$.showdown') AS showdown_json,"
                " json_extract(payload_json, '$.eliminated') AS eliminated_json,"
                " json_extract(payload_json, '$.pot') AS pot"
                " FROM events"
                " WHERE room_id = ? AND event_type = 'hand_result'"
                " ORDER BY id ASC",
                (int(room_id),),
            )
            out: list[dict[str, Any]] = []
            for r in cur:
                out.append(
                    {
                        "hand_number": r["hand_number"],
                        "board_final": _safe_json(r["board_json"]) or [],
                        "winners": _safe_json(r["winners_json"]) or [],
                        "showdown": _safe_json(r["showdown_json"]) or [],
                        "eliminated": _safe_json(r["eliminated_json"]) or [],
                        "pot": r["pot"],
                    }
                )
            return out

    def fetch_my_actions(self, room_id: int) -> list[dict[str, Any]]:
        """outbound action 레코드 + meta 의 주요 필드를 평면화 — 결정 테이블/캘리브용."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, ts, hand_number, phase,"
                " json_extract(payload_json, '$.action') AS action,"
                " json_extract(payload_json, '$.amount') AS amount,"
                " json_extract(meta_json, '$.equity') AS equity,"
                " json_extract(meta_json, '$.pot_odds') AS pot_odds,"
                " json_extract(meta_json, '$.reason') AS reason,"
                " json_extract(meta_json, '$.opp_tier') AS opp_tier,"
                " json_extract(meta_json, '$.made_hand') AS made_hand,"
                " json_extract(meta_json, '$.made_hand_ko') AS made_hand_ko,"
                " json_extract(meta_json, '$.your_cards') AS your_cards_json,"
                " json_extract(meta_json, '$.community_cards') AS community_cards_json,"
                " json_extract(meta_json, '$.to_call') AS to_call,"
                " json_extract(meta_json, '$.pot') AS pot,"
                " json_extract(meta_json, '$.my_stack') AS my_stack,"
                " json_extract(meta_json, '$.seat') AS seat,"
                " meta_json"
                " FROM events"
                " WHERE room_id = ? AND direction = 'out' AND kind = 'action'"
                " ORDER BY id ASC",
                (int(room_id),),
            )
            out: list[dict[str, Any]] = []
            for r in cur:
                meta = _safe_json(r["meta_json"]) if r["meta_json"] else None
                out.append(
                    {
                        "id": r["id"],
                        "time": r["ts"],
                        "hand_number": r["hand_number"],
                        "phase": r["phase"]
                        or (meta.get("phase") if isinstance(meta, dict) else None),
                        "action": r["action"],
                        "amount": r["amount"],
                        "equity": r["equity"],
                        "pot_odds": r["pot_odds"],
                        "reason": r["reason"],
                        "opp_tier": r["opp_tier"],
                        "made_hand": r["made_hand"],
                        "made_hand_ko": r["made_hand_ko"],
                        "your_cards": _safe_json(r["your_cards_json"]),
                        "community_cards": _safe_json(r["community_cards_json"]),
                        "to_call": r["to_call"],
                        "pot": r["pot"],
                        "my_stack": r["my_stack"],
                        "seat": r["seat"],
                        "room_id": int(room_id),
                        "meta": meta,
                    }
                )
            return out

    def latest_room_context(self, room_id: int) -> dict[str, Any]:
        """가장 최근의 hand_start 또는 action_request 에서 게임 컨텍스트 스냅샷.

        Returns: {hand_number, phase, pot, to_call, my_stack, your_cards, your_seat,
                  community_cards, blind, stack}
        """
        ctx: dict[str, Any] = {}
        keys = (
            "hand_number",
            "phase",
            "pot",
            "to_call",
            "my_stack",
            "your_stack",
            "blind",
            "your_cards",
            "your_seat",
            "seat",
            "community_cards",
        )
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM events"
                " WHERE room_id = ? AND direction = 'in'"
                " AND event_type IN ('action_request', 'hand_start')"
                " ORDER BY id DESC LIMIT 30",
                (int(room_id),),
            )
            for r in cur:
                payload = _safe_json(r["payload_json"]) if r["payload_json"] else None
                if not isinstance(payload, dict):
                    continue
                for k in keys:
                    if k in payload and k not in ctx:
                        ctx[k] = payload[k]
                if {"pot", "blind"}.issubset(ctx.keys()) and (
                    "my_stack" in ctx or "your_stack" in ctx
                ):
                    break
        if "stack" not in ctx:
            ctx["stack"] = ctx.get("my_stack") or ctx.get("your_stack")
        return ctx

    def latest_players_snapshot(self, room_id: int) -> list[dict[str, Any]]:
        """가장 최근 inbound 이벤트의 players[] 배열."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT json_extract(payload_json, '$.players') AS players_json"
                " FROM events"
                " WHERE room_id = ? AND direction = 'in'"
                " AND json_extract(payload_json, '$.players') IS NOT NULL"
                " ORDER BY id DESC LIMIT 1",
                (int(room_id),),
            )
            row = cur.fetchone()
            if not row:
                return []
            arr = _safe_json(row[0])
            return arr if isinstance(arr, list) else []

    def fetch_room_summary(
        self, room_id: int, my_name: str | None
    ) -> dict[str, Any]:
        """방 단위 통계: hands_played / VPIP / PFR / SD / SD wins / 손익 / 최종 순위.

        한 번의 호출로 모든 핵심 통계를 SQL 로 계산한다 (Python 루프 X).
        my_name 이 None 이면 통계 0 반환.
        """
        out: dict[str, Any] = {
            "hands_played": 0,
            "participated_hands": 0,
            "vpip_pct": 0.0,
            "pfr_pct": 0.0,
            "showdown_count": 0,
            "showdown_win_pct": 0.0,
            "total_winnings": 0,
            "final_rank": None,
            "alive": True,
            "max_stack": None,
            "min_stack": None,
            "last_stack": None,
            "last_blind": None,
        }
        with self._lock:
            # hands_played = distinct hand_starts
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT hand_number) FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start'"
                " AND hand_number IS NOT NULL",
                (int(room_id),),
            ).fetchone()
            hands_played = int(row[0] or 0) if row else 0
            out["hands_played"] = hands_played

            if my_name and hands_played:
                # VPIP/PFR: 내 첫 preflop outbound action 기준
                rows = self._conn.execute(
                    "SELECT hand_number, action, to_call, rn FROM ("
                    "  SELECT hand_number,"
                    "         json_extract(payload_json, '$.action') AS action,"
                    "         json_extract(meta_json, '$.to_call') AS to_call,"
                    "         ROW_NUMBER() OVER (PARTITION BY hand_number ORDER BY id) AS rn"
                    "  FROM events"
                    "  WHERE room_id = ? AND direction = 'out' AND kind = 'action'"
                    "    AND phase = 'preflop' AND hand_number IS NOT NULL"
                    ") WHERE rn = 1",
                    (int(room_id),),
                ).fetchall()
                vpip_n = 0
                pfr_n = 0
                participated = 0
                for r in rows:
                    act = r["action"]
                    tc = r["to_call"] or 0
                    voluntary = act in ("call", "raise", "allin") and (
                        (tc and float(tc) > 0) or act in ("raise", "allin")
                    )
                    if voluntary:
                        vpip_n += 1
                        participated += 1
                    if act in ("raise", "allin"):
                        pfr_n += 1
                out["participated_hands"] = participated
                out["vpip_pct"] = (vpip_n / hands_played * 100.0) if hands_played else 0.0
                out["pfr_pct"] = (pfr_n / hands_played * 100.0) if hands_played else 0.0

                # SD count: hand_result 에서 showdown[] 안에 my_name
                # json_type 으로 array 인 row 만 필터 (null/scalar 면 json_each 가 실패함).
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT e.hand_number FROM events e,"
                    "         json_each(json_extract(e.payload_json, '$.showdown')) s"
                    "  WHERE e.room_id = ? AND e.event_type = 'hand_result'"
                    "    AND json_type(e.payload_json, '$.showdown') = 'array'"
                    "    AND json_extract(s.value, '$.name') = ?"
                    "  GROUP BY e.hand_number"
                    ")",
                    (int(room_id), my_name),
                ).fetchone()
                sd_count = int(row[0] or 0) if row else 0
                out["showdown_count"] = sd_count

                # SD wins: my_name 이 winners[] 에도 들어간 SD 핸드
                if sd_count:
                    row = self._conn.execute(
                        "SELECT COUNT(*) FROM ("
                        "  SELECT e.hand_number FROM events e"
                        "  WHERE e.room_id = ? AND e.event_type = 'hand_result'"
                        "    AND json_type(e.payload_json, '$.showdown') = 'array'"
                        "    AND json_type(e.payload_json, '$.winners') = 'array'"
                        "    AND EXISTS ("
                        "      SELECT 1"
                        "      FROM json_each(json_extract(e.payload_json, '$.showdown')) s"
                        "      WHERE json_extract(s.value, '$.name') = ?"
                        "    )"
                        "    AND EXISTS ("
                        "      SELECT 1"
                        "      FROM json_each(json_extract(e.payload_json, '$.winners')) w"
                        "      WHERE json_extract(w.value, '$.name') = ?"
                        "    )"
                        "  GROUP BY e.hand_number"
                        ")",
                        (int(room_id), my_name, my_name),
                    ).fetchone()
                    sd_wins = int(row[0] or 0) if row else 0
                    out["showdown_win_pct"] = (
                        sd_wins / sd_count * 100.0
                    ) if sd_count else 0.0

                # 최종 순위: game_end 의 rankings 에서 my_name
                row = self._conn.execute(
                    "SELECT json_extract(r.value, '$.rank') AS rank,"
                    " json_extract(r.value, '$.chips') AS chips"
                    " FROM events e,"
                    "      json_each(json_extract(e.payload_json, '$.rankings')) r"
                    " WHERE e.room_id = ? AND e.event_type = 'game_end'"
                    " AND json_type(e.payload_json, '$.rankings') = 'array'"
                    " AND json_extract(r.value, '$.name') = ?"
                    " ORDER BY e.id DESC LIMIT 1",
                    (int(room_id), my_name),
                ).fetchone()
                if row:
                    out["final_rank"] = (
                        int(row["rank"]) if row["rank"] is not None else None
                    )
                    chips = row["chips"]
                    if chips is not None:
                        try:
                            out["alive"] = int(chips) > 0
                        except (TypeError, ValueError):
                            pass

                # 탈락 여부: 내 이름이 eliminated[] 에 들어간 적 있는지
                row = self._conn.execute(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM events e,"
                    "         json_each(json_extract(e.payload_json, '$.eliminated')) x"
                    "  WHERE e.room_id = ? AND e.event_type = 'hand_result'"
                    "    AND json_type(e.payload_json, '$.eliminated') = 'array'"
                    "    AND x.value = ?"
                    ")",
                    (int(room_id), my_name),
                ).fetchone()
                if row and int(row[0] or 0) == 1:
                    out["alive"] = False

            # 마지막 blind / stack — most recent action_request
            row = self._conn.execute(
                "SELECT json_extract(payload_json, '$.blind') AS blind_json,"
                " json_extract(payload_json, '$.my_stack') AS my_stack,"
                " json_extract(payload_json, '$.your_stack') AS your_stack"
                " FROM events"
                " WHERE room_id = ? AND direction = 'in'"
                " AND event_type IN ('action_request', 'hand_start')"
                " ORDER BY id DESC LIMIT 1",
                (int(room_id),),
            ).fetchone()
            if row:
                out["last_blind"] = _safe_json(row["blind_json"])
                ls = row["my_stack"] or row["your_stack"]
                if ls is not None:
                    try:
                        out["last_stack"] = float(ls)
                    except (TypeError, ValueError):
                        pass

            # max/min stack — across hand_starts
            row = self._conn.execute(
                "SELECT MAX(CAST(json_extract(payload_json, '$.your_stack') AS INTEGER)),"
                " MIN(CAST(json_extract(payload_json, '$.your_stack') AS INTEGER))"
                " FROM events WHERE room_id = ? AND event_type = 'hand_start'",
                (int(room_id),),
            ).fetchone()
            if row and row[0] is not None:
                out["max_stack"] = float(row[0])
            if row and row[1] is not None:
                out["min_stack"] = float(row[1])

            # total_winnings — 마지막 stack - 첫 stack
            row = self._conn.execute(
                "SELECT json_extract(payload_json, '$.your_stack')"
                " FROM events"
                " WHERE room_id = ? AND event_type = 'hand_start'"
                " ORDER BY id ASC LIMIT 1",
                (int(room_id),),
            ).fetchone()
            first_stack = None
            if row and row[0] is not None:
                try:
                    first_stack = float(row[0])
                except (TypeError, ValueError):
                    pass
            if first_stack is not None and out.get("last_stack") is not None:
                out["total_winnings"] = int(out["last_stack"] - first_stack)

        return out

    def fetch_game_end_rankings(
        self, room_id: int
    ) -> list[dict[str, Any]]:
        """game_end 의 rankings 배열."""
        with self._lock:
            row = self._conn.execute(
                "SELECT json_extract(payload_json, '$.rankings') AS r"
                " FROM events WHERE room_id = ? AND event_type = 'game_end'"
                " ORDER BY id DESC LIMIT 1",
                (int(room_id),),
            ).fetchone()
        if not row or not row[0]:
            return []
        arr = _safe_json(row[0])
        return arr if isinstance(arr, list) else []


# ── helpers ─────────────────────────────────────────────────────────────────


def _safe_json(text: Any) -> Any:
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    """events row → JSONL record 호환 dict."""
    direction = row["direction"]
    payload = None
    if row["payload_json"]:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = None

    if direction == "marker":
        rec: dict[str, Any] = {
            "ts": row["ts"],
            "run_id": row["run_id"],
            "_run_started": row["ts"],
        }
        if isinstance(payload, dict):
            for k, v in payload.items():
                if k not in rec:
                    rec[k] = v
        return rec

    if direction == "in":
        return {
            "ts": row["ts"],
            "run_id": row["run_id"],
            "dir": "in",
            "type": row["event_type"],
            "room_id": row["room_id"],
            "raw": row["raw_text"],
            "event": payload,
        }

    # outbound
    meta = None
    if row["meta_json"]:
        try:
            meta = json.loads(row["meta_json"])
        except json.JSONDecodeError:
            meta = None
    rec_out: dict[str, Any] = {
        "ts": row["ts"],
        "run_id": row["run_id"],
        "dir": "out",
        "kind": row["kind"],
        "room_id": row["room_id"],
        "payload": payload,
    }
    if meta is not None:
        rec_out["meta"] = meta
    return rec_out


def jsonl_writes_enabled() -> bool:
    """`HOLDEM_DEBUG_JSONL` 환경 변수 — 기본 꺼짐 ('0').

    SQLite 가 단일 진실 원천. JSONL/JSON 파일 백업이 필요하면 '1' 로 명시 켠다.
    리더(loader/dashboard)는 DB 가 없을 때만 기존 `.debug/backup/*.jsonl` 를 읽는다.
    """
    val = os.environ.get("HOLDEM_DEBUG_JSONL", "0").strip().lower()
    return val in ("1", "true", "yes", "on")
