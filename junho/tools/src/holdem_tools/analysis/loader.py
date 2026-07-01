"""`.debug/room_*.jsonl` 또는 SQLite (`holdem.db`) 에서 핸드 단위 레코드로 변환.

`_run_started` 마커로 세션 분리, `hand_start` ~ `hand_result` 로 핸드를 묶는다.
outbound `action` 레코드의 `meta` 가 있으면 사용, 없으면 `logs/decisions.jsonl`
폴백 조인으로 결정 근거를 채워준다 (기존 5 룸 로그 소급 분석용).

SQLite 백엔드는 `DebugStore.iter_events()` 가 동일한 dict shape 를 yield 하므로
같은 state machine 을 재사용한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from holdem_core.core.logging import get_logger
from holdem_core.debug.store import DebugStore, default_db_path

logger = get_logger(__name__)


@dataclass
class MyDecision:
    """내 한 번의 결정 스냅샷."""

    hand_number: int
    phase: str
    seat: str | None
    your_cards: list[str]
    community_cards: list[str]
    to_call: int
    pot: int
    my_stack: int
    action: str
    amount: int | None
    meta: dict[str, Any] | None


@dataclass
class HandRecord:
    """한 핸드의 이벤트 + 내 결정 목록."""

    room_id: int
    run_id: str
    hand_number: int
    bot_name: str
    your_cards: list[str]
    your_seat: str
    start_stack: int
    end_stack: int
    blind: list[int]
    board_final: list[str]
    players_start: list[dict[str, Any]]
    my_actions: list[MyDecision] = field(default_factory=list)
    winners: list[dict[str, Any]] = field(default_factory=list)
    showdown: list[dict[str, Any]] = field(default_factory=list)
    eliminated: list[str] = field(default_factory=list)
    pot: int = 0
    ts_start: float | None = None
    ts_end: float | None = None
    opp_actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Session:
    """한 run_id 의 핸드 묶음."""

    room_id: int
    run_id: str
    bot_name: str
    hands: list[HandRecord]
    rankings: list[dict[str, Any]] = field(default_factory=list)
    ended: bool = False


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _consume_events(
    records: Iterable[dict[str, Any]],
    bot_name_hint: str | None = None,
) -> list[Session]:
    """JSONL/Store 공용 state machine. records 는 record dict 의 시퀀스."""
    sessions_by_run: dict[str, Session] = {}
    run_id: str | None = None
    room_id: int | None = None
    current_hand: HandRecord | None = None
    current_phase = "preflop"

    def _finalize_hand() -> None:
        nonlocal current_hand
        if current_hand is None or run_id is None:
            current_hand = None
            return
        sess = sessions_by_run.get(run_id)
        if sess is None:
            sess = Session(
                room_id=current_hand.room_id,
                run_id=run_id,
                bot_name=current_hand.bot_name,
                hands=[],
            )
            sessions_by_run[run_id] = sess
        sess.hands.append(current_hand)
        current_hand = None

    for rec in records:
        if "_run_started" in rec:
            _finalize_hand()
            run_id = rec.get("run_id")
            current_phase = "preflop"
            continue
        if run_id is None:
            continue
        if room_id is None and rec.get("room_id"):
            room_id = int(rec["room_id"])

        dir_ = rec.get("dir")
        t = rec.get("type") if dir_ == "in" else None

        if t == "hand_start":
            _finalize_hand()
            evt = rec.get("event") or {}
            bot_name = _detect_bot_name(evt, bot_name_hint)
            current_hand = HandRecord(
                room_id=int(evt.get("room_id") or rec.get("room_id") or room_id or 0),
                run_id=run_id,
                hand_number=int(evt.get("hand_number") or 0),
                bot_name=bot_name,
                your_cards=list(evt.get("your_cards") or []),
                your_seat=str(evt.get("your_seat") or ""),
                start_stack=int(evt.get("your_stack") or 0),
                end_stack=int(evt.get("your_stack") or 0),
                blind=list(evt.get("blind") or []),
                board_final=[],
                players_start=list(evt.get("players") or []),
                ts_start=rec.get("ts"),
                ts_end=rec.get("ts"),
            )
            current_phase = "preflop"
            continue

        if current_hand is None:
            continue

        current_hand.ts_end = rec.get("ts", current_hand.ts_end)

        if t == "phase_change":
            evt = rec.get("event") or {}
            current_phase = evt.get("phase") or current_phase
            continue

        if t == "action_performed":
            evt = rec.get("event") or {}
            current_hand.opp_actions.append({
                "phase": current_phase,
                "player": evt.get("player"),
                "action": evt.get("action"),
                "amount": evt.get("amount"),
                "pot": evt.get("pot"),
            })
            continue

        if dir_ == "out" and rec.get("kind") == "action":
            payload = rec.get("payload") or {}
            meta = rec.get("meta")
            dec = MyDecision(
                hand_number=current_hand.hand_number,
                phase=(meta or {}).get("phase") or current_phase,
                seat=(meta or {}).get("seat") or current_hand.your_seat,
                your_cards=list(
                    (meta or {}).get("your_cards") or current_hand.your_cards
                ),
                community_cards=list((meta or {}).get("community_cards") or []),
                to_call=int((meta or {}).get("to_call") or 0),
                pot=int((meta or {}).get("pot") or 0),
                my_stack=int((meta or {}).get("my_stack") or 0),
                action=str(payload.get("action") or (meta or {}).get("action") or ""),
                amount=payload.get("amount"),
                meta=meta if isinstance(meta, dict) else None,
            )
            current_hand.my_actions.append(dec)
            continue

        if t == "hand_result":
            evt = rec.get("event") or {}
            current_hand.board_final = list(evt.get("community_cards") or [])
            current_hand.winners = list(evt.get("winners") or [])
            current_hand.showdown = list(evt.get("showdown") or [])
            current_hand.eliminated = list(evt.get("eliminated") or [])
            current_hand.pot = int(evt.get("pot") or 0)
            # end_stack 은 다음 hand_start 에서 덮어쓰이지 않으면 start_stack 유지
            _finalize_hand()
            continue

        if t == "game_end":
            evt = rec.get("event") or {}
            _finalize_hand()
            if run_id in sessions_by_run:
                sessions_by_run[run_id].rankings = list(evt.get("rankings") or [])
                sessions_by_run[run_id].ended = True
            continue

    _finalize_hand()

    # end_stack 보정: 다음 핸드의 hand_start.your_stack 을 이전 hand 의 end_stack 으로
    for sess in sessions_by_run.values():
        for i in range(len(sess.hands) - 1):
            sess.hands[i].end_stack = sess.hands[i + 1].start_stack

    return list(sessions_by_run.values())


def load_sessions(path: Path, bot_name_hint: str | None = None) -> list[Session]:
    """JSONL 파일 하나에서 여러 run_id 세션을 뽑아 반환."""
    return _consume_events(iter_jsonl(path), bot_name_hint=bot_name_hint)


def load_sessions_from_store(
    store: DebugStore,
    room_id: int | None = None,
    bot_name_hint: str | None = None,
) -> list[Session]:
    """SQLite DebugStore 에서 세션 묶음을 반환.

    `room_id` 가 None 이면 store 내 모든 room 의 events 를 시간순으로 한 번에
    먹는다. 단일 room 에 한정하고 싶으면 명시.
    """
    return _consume_events(
        store.iter_events(room_id=room_id, include_markers=True),
        bot_name_hint=bot_name_hint,
    )


def load_sessions_auto(
    spec: str | Path, bot_name_hint: str | None = None
) -> list[Session]:
    """입력 경로를 자동 판정해 sessions 반환.

    - `.jsonl` 파일 → `load_sessions(path)`
    - 디렉토리 → `{dir}/holdem.db` 를 읽어 `load_sessions_from_store`
    - `.db` 파일 → 그 부모 디렉토리를 base_dir 로 `DebugStore.open(read_only=True)`
    """
    p = Path(spec)
    if p.is_file() and p.suffix == ".jsonl":
        return load_sessions(p, bot_name_hint=bot_name_hint)
    if p.is_file() and p.suffix == ".db":
        store = DebugStore.open(p.parent, read_only=True, db_filename=p.name)
        try:
            return load_sessions_from_store(store, bot_name_hint=bot_name_hint)
        finally:
            store.close()
    if p.is_dir():
        store = DebugStore.open(p, read_only=True)
        try:
            return load_sessions_from_store(store, bot_name_hint=bot_name_hint)
        finally:
            store.close()
    # 마지막 시도: spec 에 default_db_path 적용
    db_path = default_db_path(p)
    if db_path.exists():
        store = DebugStore.open(p, read_only=True)
        try:
            return load_sessions_from_store(store, bot_name_hint=bot_name_hint)
        finally:
            store.close()
    raise FileNotFoundError(f"load_sessions_auto: cannot resolve {spec!r}")


def load_session(path: Path, bot_name_hint: str | None = None) -> list[HandRecord]:
    """가장 마지막 세션의 핸드 리스트만 반환 (간단한 진입용)."""
    sessions = load_sessions(path, bot_name_hint=bot_name_hint)
    if not sessions:
        return []
    # 가장 많은 핸드를 가진 세션을 메인으로 취급
    sessions.sort(key=lambda s: len(s.hands), reverse=True)
    return sessions[0].hands


def _detect_bot_name(hs_evt: dict[str, Any], hint: str | None) -> str:
    """hand_start.players 에서 your_seat 과 같은 position 을 가진 플레이어 이름."""
    your_seat = hs_evt.get("your_seat")
    players = hs_evt.get("players") or []
    for p in players:
        if isinstance(p, dict) and p.get("position") == your_seat:
            name = p.get("name")
            if isinstance(name, str):
                return name
    if hint:
        return hint
    return ""


def merge_decisions(records: list[HandRecord], decisions_jsonl_path: Path) -> int:
    """record.my_actions[i].meta 가 None 인 것들에 `logs/decisions.jsonl` 을 폴백 조인.

    키: (room_id, hand_number, phase, tuple(sorted(your_cards)), seat)
    """
    if not decisions_jsonl_path.exists():
        return 0
    index: dict[tuple, dict[str, Any]] = {}
    for rec in iter_jsonl(decisions_jsonl_path):
        extra = rec.get("extra") or {}
        key = (
            extra.get("room_id"),
            extra.get("hand_number"),
            extra.get("phase"),
            tuple(sorted(extra.get("your_cards") or [])),
            extra.get("seat"),
        )
        if key[0] is None or key[1] is None:
            continue
        index[key] = extra

    merged_count = 0
    for hand in records:
        for dec in hand.my_actions:
            if dec.meta is not None:
                continue
            key = (
                hand.room_id,
                dec.hand_number,
                dec.phase,
                tuple(sorted(dec.your_cards)),
                dec.seat,
            )
            hit = index.get(key)
            if hit is None:
                # seat 이 다를 수 있어 seat 제외 키로 재시도
                key2 = (hand.room_id, dec.hand_number, dec.phase, key[3], None)
                for k, v in index.items():
                    if (k[0], k[1], k[2], k[3]) == key2[:4]:
                        hit = v
                        break
            if hit is not None:
                dec.meta = dict(hit)
                merged_count += 1
    return merged_count
