"""Streamlit dashboard for live visualization of decision logs + room events."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# `streamlit run tools/src/holdem_tools/viz/dashboard.py` 로 직접 실행되는 경우를 위해
# workspace root 를 sys.path 에 추가. `uv run` 으로 실행 시는 이미 설치된 패키지라 불필요.
_ROOT = Path(__file__).resolve().parents[4]  # tools/src/holdem_tools/viz/dashboard.py → workspace root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from holdem_core.debug.store import DebugStore  # noqa: E402
from holdem_core.hand_eval import classify_hand  # noqa: E402

from holdem_tools.viz.cards import back_card_html, card_html, cards_html, empty_card_html  # noqa: E402
from holdem_tools.viz.flow import (  # noqa: E402
    PHASE_KO,
    RESULT_COLORS,
    action_badge,
    decision_overlay_html,
    flow_row_html,
    player_row_html,
)

# Optional streamlit import for caching decorators. Functions still work
# as plain callables when streamlit is not installed (e.g. unit testing).
try:  # pragma: no cover - import-time convenience
    import streamlit as _st  # type: ignore

    _HAS_ST = True
except ImportError:  # pragma: no cover
    _st = None  # type: ignore
    _HAS_ST = False


def _cache_data(ttl: int = 5):
    if _HAS_ST and _st is not None:
        return _st.cache_data(ttl=ttl)

    def _noop(fn):
        return fn

    return _noop

DECISION_COLUMNS = [
    "time",
    "hand_number",
    "phase",
    "seat",
    "your_cards",
    "community_cards",
    "to_call",
    "pot",
    "action",
    "amount",
    "equity",
    "pot_odds",
    "made_hand",
    "opp_tier",
    "reason",
]


def parse_decision_line(raw: str) -> dict[str, Any] | None:
    line = raw.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("msg") != "decision":
        return None
    extra = obj.get("extra") or {}
    if not isinstance(extra, dict):
        return None
    flat: dict[str, Any] = {"time": obj.get("time")}
    flat.update(extra)
    return flat


def parse_decision_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in lines:
        row = parse_decision_line(raw)
        if row is not None:
            out.append(row)
    return out


def group_by_room(rows: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        key = row.get("room_id", "unknown")
        grouped.setdefault(key, []).append(row)
    return grouped


@_cache_data(ttl=5)
def load_decisions(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    return parse_decision_lines(text.splitlines())


def load_decisions_for_room(
    path: str | os.PathLike[str], room_id: Any
) -> list[dict[str, Any]]:
    rows = load_decisions(path)
    return [r for r in rows if r.get("room_id") == room_id]


# --- .debug/room_*.jsonl (raw WS event stream) -------------------------------


def parse_event_line(raw: str) -> dict[str, Any] | None:
    """Parse a single line from `.debug/room_X.jsonl`.

    Returns None for blank/invalid/run-marker lines.
    """
    line = raw.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if "_run_started" in obj:  # boundary marker, skip
        return None
    return obj


def _open_store_ro(base_dir: str) -> DebugStore | None:
    """Open SQLite store read-only; None if absent or unopenable.

    스토어 인스턴스는 캐싱하지 않는다 (`st.cache_data` 가 SQLite connection 을
    pickle 못함). 데이터 자체는 호출자(`load_room_events` 등)에서 cache_data 로
    캐싱되므로, 매 호출 open/close 비용은 cache miss 시에만 발생한다.
    """
    try:
        return DebugStore.open(base_dir, read_only=True)
    except FileNotFoundError:
        return None
    except Exception:
        return None


# --- SQL-backed cached helpers (dashboard hot path) -------------------------
#
# 모든 helper 는 `(room_id, debug_dir, db_mtime)` 를 캐시 키로 쓴다. db_mtime
# 은 holdem.db 파일의 mtime — DB 업데이트 시 캐시 자동 무효화. 이렇게 하면 같은
# 렌더 사이클 안의 반복 호출은 1회만 SQL 을 친다.


def _db_mtime(debug_dir: str | os.PathLike[str]) -> float:
    """holdem.db 파일의 mtime — 캐시 키 무효화용. DB 없으면 0.0."""
    p = Path(debug_dir) / "holdem.db"
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


@_cache_data(ttl=5)
def store_list_rooms(debug_dir: str, db_mtime: float) -> list[Any]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    rooms = list(s.list_rooms())
    return sorted(rooms, key=lambda k: (not isinstance(k, int), str(k)))


@_cache_data(ttl=5)
def store_detect_bot_name(
    room_id: int, debug_dir: str, db_mtime: float
) -> str | None:
    s = _open_store_ro(debug_dir)
    if s is None:
        return None
    return s.detect_bot_name(room_id=room_id)


@_cache_data(ttl=5)
def store_room_summary(
    room_id: int, debug_dir: str, db_mtime: float, my_name: str | None
) -> dict[str, Any]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return {}
    return s.fetch_room_summary(room_id, my_name)


@_cache_data(ttl=5)
def store_hand_starts(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.fetch_hand_starts(room_id)


@_cache_data(ttl=5)
def store_hand_results(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.fetch_hand_results(room_id)


@_cache_data(ttl=5)
def store_my_actions(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.fetch_my_actions(room_id)


@_cache_data(ttl=5)
def store_latest_context(
    room_id: int, debug_dir: str, db_mtime: float
) -> dict[str, Any]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return {}
    return s.latest_room_context(room_id)


@_cache_data(ttl=5)
def store_latest_players(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.latest_players_snapshot(room_id)


@_cache_data(ttl=5)
def store_hand_numbers(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[int]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.list_hand_numbers(room_id)


@_cache_data(ttl=5)
def store_hand_events(
    room_id: int, debug_dir: str, db_mtime: float, hand_number: int
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.fetch_hand_events(room_id, hand_number)


@_cache_data(ttl=5)
def store_game_end_rankings(
    room_id: int, debug_dir: str, db_mtime: float
) -> list[dict[str, Any]]:
    s = _open_store_ro(debug_dir)
    if s is None:
        return []
    return s.fetch_game_end_rankings(room_id)


def _build_timeline_from_rows(
    hand_starts: list[dict[str, Any]],
    hand_results: list[dict[str, Any]],
    my_actions: list[dict[str, Any]],
    my_name: str | None,
    last_player_stack: float | None,
) -> list[dict[str, Any]]:
    """SQL 결과(hand_starts, hand_results, my_actions) 를 timeline 으로 빌드.

    `compute_my_timeline` 의 결과와 호환되는 dict 리스트.
    O(hands) 만, 더 이상 events 5000+ 를 풀스캔하지 않는다.
    """
    if not my_name:
        return []
    by_actions: dict[int, list[dict[str, Any]]] = {}
    for a in my_actions:
        hn = a.get("hand_number")
        if isinstance(hn, int):
            by_actions.setdefault(hn, []).append(a)
    by_results = {r.get("hand_number"): r for r in hand_results if r.get("hand_number") is not None}

    timeline: list[dict[str, Any]] = []
    for i, hs in enumerate(hand_starts):
        hn = hs.get("hand_number")
        if not isinstance(hn, int):
            continue
        actions = by_actions.get(hn, [])
        result = by_results.get(hn)

        participated = any(
            a.get("action") in ("call", "raise", "allin", "check") for a in actions
        )
        fold_street = next(
            (a.get("phase") for a in actions if a.get("action") == "fold"),
            None,
        )

        winners = []
        showdown_arr = []
        eliminated_arr = []
        board_final: list[Any] = []
        went_sd = False
        eliminated_here = False
        if result:
            winners = list(result.get("winners") or [])
            showdown_arr = list(result.get("showdown") or [])
            eliminated_arr = list(result.get("eliminated") or [])
            board_final = list(result.get("board_final") or [])
            went_sd = any(
                isinstance(s, dict) and s.get("name") == my_name
                for s in showdown_arr
            )
            eliminated_here = my_name in eliminated_arr

        end_stack: Any = None
        if i + 1 < len(hand_starts):
            end_stack = hand_starts[i + 1].get("start_stack")
        elif last_player_stack is not None:
            end_stack = last_player_stack

        start = hs.get("start_stack")
        try:
            delta_val = (
                float(end_stack) - float(start)
                if (start is not None and end_stack is not None)
                else None
            )
        except (TypeError, ValueError):
            delta_val = None
        my_delta: Any = (
            None
            if delta_val is None
            else (int(delta_val) if float(delta_val).is_integer() else delta_val)
        )

        winner_names = [w.get("name") for w in winners if isinstance(w, dict)]
        i_won = my_name in winner_names

        if eliminated_here:
            classified = "eliminated"
        elif i_won:
            classified = "win"
        elif went_sd:
            classified = "lose_showdown"
        elif fold_street == "preflop":
            classified = "fold_pre"
        elif fold_street in ("flop", "turn", "river"):
            classified = "fold_post"
        elif not participated:
            classified = "skipped"
        else:
            classified = "fold_post"

        timeline.append(
            {
                "hand_number": hn,
                "your_cards": list(hs.get("your_cards") or []),
                "seat": hs.get("seat"),
                "start_stack": start,
                "end_stack": end_stack,
                "participated": participated,
                "fold_street": fold_street,
                "went_to_showdown": went_sd,
                "shown_cards": showdown_arr,
                "winners": winners,
                "eliminated_here": eliminated_here,
                "board_final": board_final,
                "my_delta": my_delta,
                "result": classified,
            }
        )
    return timeline


def _decision_index_from_actions(
    my_actions: list[dict[str, Any]],
) -> dict[tuple, dict[str, Any]]:
    """fetch_my_actions 결과 → decision_key dict (build_hand_flow 가 사용하는 포맷)."""
    index: dict[tuple, dict[str, Any]] = {}
    for a in my_actions:
        hn = a.get("hand_number")
        phase = a.get("phase")
        cards = a.get("your_cards")
        seat = a.get("seat")
        if hn is None or phase is None or not isinstance(cards, list):
            continue
        meta = a.get("meta") if isinstance(a.get("meta"), dict) else None
        snapshot: dict[str, Any] = {}
        if meta:
            snapshot.update(meta)
        else:
            for k in (
                "equity",
                "pot_odds",
                "reason",
                "made_hand",
                "made_hand_ko",
                "opp_tier",
            ):
                if a.get(k) is not None:
                    snapshot[k] = a[k]
        if not snapshot:
            continue
        key = (hn, phase, tuple(sorted(cards)), seat)
        index[key] = snapshot
    return index


@_cache_data(ttl=5)
def load_room_events(
    room_id: Any, base_dir: str | os.PathLike[str]
) -> list[dict[str, Any]]:
    """Load raw WS events for a single room.

    SQLite 가 있으면 거기서, 없으면 `.debug/room_{room_id}.jsonl` 에서 읽는다.
    markers 는 양쪽 경로 모두 제외 (JSONL 경로의 `parse_event_line` 도 동일).
    """
    store = _open_store_ro(str(base_dir))
    if store is not None:
        try:
            rid_int = int(room_id)
        except (TypeError, ValueError):
            return []
        return list(store.iter_events(room_id=rid_int, include_markers=False))

    p = Path(base_dir) / f"room_{room_id}.jsonl"
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        ev = parse_event_line(raw)
        if ev is not None:
            out.append(ev)
    return out


def discover_rooms(debug_dir: str | os.PathLike[str]) -> list[Any]:
    """Room IDs from SQLite store (preferred) or `.debug/room_*.jsonl` glob.

    `logs/decisions.jsonl` 은 의도적으로 제외한다. `.debug` 를 비우면 대시보드도
    비어야 한다는 기대 때문. decisions 는 각 방 내부에서 equity/pot_odds 등 보조 정보로만 사용.
    """
    store = _open_store_ro(str(debug_dir))
    if store is not None:
        rooms_int: list[Any] = list(store.list_rooms())
        return sorted(rooms_int, key=lambda k: (not isinstance(k, int), str(k)))

    rooms: set[Any] = set()
    p = Path(debug_dir)
    if p.exists() and p.is_dir():
        for f in p.glob("room_*.jsonl"):
            suffix = f.stem[len("room_") :]
            try:
                rid = int(suffix)
            except ValueError:
                rid = suffix
            rooms.add(rid)
    return sorted(rooms, key=lambda k: (not isinstance(k, int), str(k)))


def list_hand_numbers(events: list[dict[str, Any]]) -> list[int]:
    """Sorted unique hand_numbers from inbound events (ascending)."""
    seen: set[int] = set()
    for e in events:
        if e.get("dir") != "in":
            continue
        hn = (e.get("event") or {}).get("hand_number")
        if isinstance(hn, int):
            seen.add(hn)
    return sorted(seen)


def events_for_hand(
    events: list[dict[str, Any]], hand_number: int
) -> list[dict[str, Any]]:
    """Return inbound events belonging to a specific hand.

    hand_start 를 경계로 current hand 를 추적. `hand_number` 필드가 없는 이벤트
    (예: phase_change, hand_result 의 일부) 도 현재 hand 에 속한다고 판단.
    """
    result: list[dict[str, Any]] = []
    current: int | None = None
    for e in events:
        if e.get("dir") != "in":
            continue
        p = e.get("event") or {}
        et = e.get("type")
        if et == "hand_start":
            current = p.get("hand_number") if isinstance(p.get("hand_number"), int) else None
        if current == hand_number:
            result.append(e)
    return result


def latest_players_snapshot(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Most recent `players[]` seen in any inbound event."""
    for ev in reversed(events):
        if ev.get("dir") != "in":
            continue
        payload = ev.get("event") or {}
        players = payload.get("players")
        if isinstance(players, list) and players:
            return players
    return []


def latest_hand_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick out stack/seat/blind/cards/community/pot/to_call from most recent events."""
    ctx: dict[str, Any] = {}
    for ev in reversed(events):
        if ev.get("dir") != "in":
            continue
        p = ev.get("event") or {}
        t = ev.get("type")
        if t in ("action_request", "hand_start"):
            for key in (
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
            ):
                if key in p and key not in ctx:
                    ctx[key] = p[key]
            if {"pot", "my_stack", "blind"}.issubset(ctx.keys()):
                break
    if "stack" not in ctx:
        ctx["stack"] = ctx.get("my_stack") or ctx.get("your_stack")
    return ctx


def compute_pot_odds(to_call: Any, pot: Any) -> float | None:
    try:
        tc = float(to_call)
        pt = float(pot)
    except (TypeError, ValueError):
        return None
    if tc <= 0:
        return 0.0
    total = pt + tc
    if total <= 0:
        return None
    return tc / total


def compute_m_ratio(stack: Any, blind: Any) -> float | None:
    try:
        st = float(stack)
    except (TypeError, ValueError):
        return None
    if not isinstance(blind, (list, tuple)) or len(blind) < 2:
        return None
    try:
        sb = float(blind[0])
        bb = float(blind[1])
    except (TypeError, ValueError):
        return None
    denom = sb + bb
    if denom <= 0:
        return None
    return st / denom


def build_hand_flow(
    events: list[dict[str, Any]], hand_number: int | None = None
) -> list[dict[str, Any]]:
    """Chronological rows for a single hand: hand_start, phase, actions, result.

    If `hand_number` is None, picks the most recent hand seen.

    `my_turn` rows carry `decision_key = (hand_number, phase, tuple(sorted(cards)), seat)`
    for joining with `compute_decision_index`. Outbound `action` events are also
    scanned to attach `decision_meta` directly on the preceding `my_turn` row.
    """
    if hand_number is None:
        seen: list[int] = []
        for e in events:
            if e.get("dir") != "in":
                continue
            p = e.get("event") or {}
            hn = p.get("hand_number")
            if isinstance(hn, int):
                seen.append(hn)
        if not seen:
            return []
        hand_number = max(seen)

    rows: list[dict[str, Any]] = []
    current: int | None = None
    closed = False
    pending_my_turn_idx: int | None = None
    for e in events:
        direction = e.get("dir")
        p = e.get("event") or {}
        et = e.get("type")

        if direction == "in":
            if et == "hand_start":
                hn = p.get("hand_number")
                current = hn if hn == hand_number else None
                closed = False
                if current == hand_number:
                    rows.append(
                        {
                            "ts": e.get("ts"),
                            "kind": "hand_start",
                            "detail": f"#{hn} 카드={p.get('your_cards')} 자리={p.get('your_seat')} "
                            f"스택={p.get('your_stack')} 블라인드={p.get('blind')}",
                        }
                    )
                    pending_my_turn_idx = None
                continue
            if current != hand_number or closed:
                continue
            # Skip events whose hand_number is explicitly different (e.g. hand_result for a later hand).
            ev_hn = p.get("hand_number")
            if isinstance(ev_hn, int) and ev_hn != hand_number:
                continue
            if et == "action_performed":
                rows.append(
                    {
                        "ts": e.get("ts"),
                        "kind": "action",
                        "detail": f"{p.get('player')} {p.get('action')} "
                        f"{p.get('amount') or ''} 팟={p.get('pot')}",
                    }
                )
            elif et == "phase_change":
                rows.append(
                    {
                        "ts": e.get("ts"),
                        "kind": f"phase:{p.get('phase')}",
                        "detail": f"보드={p.get('community_cards')}",
                    }
                )
            elif et == "action_request":
                phase_ko = PHASE_KO.get(p.get("phase"), p.get("phase"))
                cards = p.get("your_cards")
                cards_tuple = (
                    tuple(sorted(cards)) if isinstance(cards, list) else ()
                )
                rows.append(
                    {
                        "ts": e.get("ts"),
                        "kind": "my_turn",
                        "detail": f"페이즈={phase_ko} 팟={p.get('pot')} "
                        f"to_call={p.get('to_call')} 스택={p.get('my_stack')}",
                        "decision_key": (
                            p.get("hand_number"),
                            p.get("phase"),
                            cards_tuple,
                            p.get("seat"),
                        ),
                    }
                )
                pending_my_turn_idx = len(rows) - 1
            elif et == "hand_result":
                winners = p.get("winners") or []
                win_str = ", ".join(
                    f"{w.get('name')}:+{w.get('amount')}" for w in winners
                )
                showdown = p.get("showdown") or []
                eliminated = p.get("eliminated") or []
                extra_parts: list[str] = []
                if showdown:
                    sd_parts = []
                    for s in showdown:
                        if not isinstance(s, dict):
                            continue
                        sd_parts.append(
                            f"{s.get('name')}[{' '.join(s.get('cards') or [])}]"
                        )
                    if sd_parts:
                        extra_parts.append("쇼다운: " + "·".join(sd_parts))
                if eliminated:
                    extra_parts.append(f"탈락:[{', '.join(eliminated)}]")
                extra = (" " + " ".join(extra_parts)) if extra_parts else ""
                rows.append(
                    {
                        "ts": e.get("ts"),
                        "kind": "hand_result",
                        "detail": f"승자=[{win_str}] 보드={p.get('community_cards')}{extra}",
                    }
                )
                closed = True
            continue

        if direction == "out" and current == hand_number and not closed and e.get("kind") == "action":
            meta = e.get("meta")
            if (
                isinstance(meta, dict)
                and meta
                and pending_my_turn_idx is not None
                and 0 <= pending_my_turn_idx < len(rows)
            ):
                rows[pending_my_turn_idx]["decision_meta"] = meta
                pending_my_turn_idx = None
    return rows


# --- My-timeline / session stats / decision index --------------------------


def detect_my_name(
    events: list[dict[str, Any]],
    debug_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Determine the bot's display name used by the server.

    순서대로 다음을 시도:
    1) 첫 `hand_start` 의 `your_seat` 과 같은 `position` 을 가진 `players[].name`
    2) `.debug/_global.jsonl` 안의 `_run_started.bot_name`
    3) 환경변수 `MY_BOT_NAME`
    """
    for ev in events:
        if ev.get("dir") != "in":
            continue
        if ev.get("type") != "hand_start":
            continue
        p = ev.get("event") or {}
        your_seat = p.get("your_seat")
        players = p.get("players") or []
        if your_seat and isinstance(players, list):
            for pl in players:
                if pl.get("position") == your_seat and pl.get("name"):
                    return str(pl.get("name"))
        break  # only first hand_start matters

    if debug_dir is not None:
        gp = Path(debug_dir) / "_global.jsonl"
        if gp.exists():
            try:
                for raw in gp.read_text(encoding="utf-8").splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict) and "_run_started" in obj and obj.get("bot_name"):
                        return str(obj["bot_name"])
            except OSError:
                pass

    env = os.environ.get("MY_BOT_NAME")
    if env:
        return env
    return None


def _find_my_player(players: list[dict[str, Any]] | None, my_name: str) -> dict[str, Any] | None:
    if not isinstance(players, list):
        return None
    for p in players:
        if isinstance(p, dict) and p.get("name") == my_name:
            return p
    return None


def compute_my_timeline(
    events: list[dict[str, Any]], my_name: str | None
) -> list[dict[str, Any]]:
    """Per-hand summary from the bot's perspective.

    Output list is ordered by hand_number ascending. See module docstring for
    field reference.
    """
    if not my_name:
        return []

    # Group inbound events by hand_number (derived from context).
    hands: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    # Track next_start_stack (for hand N's end_stack) from next hand_start.your_stack.
    for ev in events:
        if ev.get("dir") != "in":
            continue
        p = ev.get("event") or {}
        et = ev.get("type")

        if et == "hand_start":
            hn = p.get("hand_number")
            if not isinstance(hn, int):
                continue
            if current is not None:
                # Close previous hand: back-fill end_stack from this hand's start.
                if current.get("end_stack") is None:
                    current["end_stack"] = p.get("your_stack")
                hands.append(current)
            current = {
                "hand_number": hn,
                "your_cards": list(p.get("your_cards") or []),
                "seat": p.get("your_seat"),
                "start_stack": p.get("your_stack"),
                "end_stack": None,
                "participated": False,
                "fold_street": None,
                "went_to_showdown": False,
                "shown_cards": [],
                "winners": [],
                "eliminated_here": False,
                "board_final": [],
                "result": "skipped",
                "_my_actions": [],
                "_last_player_snapshot": None,
                "_closed": False,
            }
            # Capture initial player snapshot for stack tracking.
            me = _find_my_player(p.get("players"), my_name)
            if me is not None:
                current["_last_player_snapshot"] = dict(me)
            continue

        if current is None or current.get("_closed"):
            continue

        # Skip events that carry a hand_number different from current.
        ev_hn = p.get("hand_number")
        if isinstance(ev_hn, int) and ev_hn != current["hand_number"]:
            continue

        if et == "action_performed":
            players = p.get("players")
            me = _find_my_player(players, my_name)
            if me is not None:
                current["_last_player_snapshot"] = dict(me)
            if p.get("player") == my_name:
                act = p.get("action")
                current["_my_actions"].append({"action": act, "amount": p.get("amount")})
                if act == "fold":
                    if current["fold_street"] is None:
                        current["fold_street"] = current.get("_last_phase")
                elif act in ("call", "raise", "allin", "check"):
                    current["participated"] = True
            continue

        if et == "action_request":
            current["_last_phase"] = p.get("phase")
            continue

        if et == "phase_change":
            current["_last_phase"] = p.get("phase")
            current["board_final"] = list(p.get("community_cards") or [])
            continue

        if et == "hand_result":
            # Only consume hand_result matching our hand. (ev_hn already filtered.)
            winners = p.get("winners") or []
            showdown = p.get("showdown") or []
            eliminated = p.get("eliminated") or []
            current["winners"] = winners
            current["shown_cards"] = showdown
            current["board_final"] = list(p.get("community_cards") or current.get("board_final") or [])
            current["went_to_showdown"] = any(
                s.get("name") == my_name for s in showdown if isinstance(s, dict)
            )
            current["eliminated_here"] = my_name in eliminated
            current["_closed"] = True
            continue

    if current is not None:
        hands.append(current)

    # Back-fill end_stack for the very last hand from the most recent player snapshot.
    if hands and hands[-1].get("end_stack") is None:
        last = hands[-1]
        snap = last.get("_last_player_snapshot")
        if snap is not None:
            last["end_stack"] = snap.get("stack")

    # Compute my_delta and result classification.
    for h in hands:
        start = h.get("start_stack")
        end = h.get("end_stack")
        try:
            delta = (float(end) - float(start)) if (start is not None and end is not None) else None
        except (TypeError, ValueError):
            delta = None
        h["my_delta"] = None if delta is None else int(delta) if float(delta).is_integer() else delta

        # Classify result.
        winner_names = [w.get("name") for w in (h.get("winners") or []) if isinstance(w, dict)]
        i_won = my_name in winner_names
        went_sd = bool(h.get("went_to_showdown"))
        eliminated = bool(h.get("eliminated_here"))
        fold_street = h.get("fold_street")
        participated = bool(h.get("participated"))

        if eliminated:
            result = "eliminated"
        elif i_won:
            result = "win"
        elif went_sd:
            result = "lose_showdown"
        elif fold_street == "preflop":
            result = "fold_pre"
        elif fold_street in ("flop", "turn", "river"):
            result = "fold_post"
        elif not participated:
            result = "skipped"
        else:
            # Took action, no showdown, not winner — likely folded post or
            # blinds lost; default to skipped when ambiguous.
            result = "skipped" if not participated else "fold_post"
        h["result"] = result

        # Strip helpers.
        h.pop("_my_actions", None)
        h.pop("_last_phase", None)
        h.pop("_last_player_snapshot", None)
        h.pop("_closed", None)

    return hands


def compute_session_stats(
    timeline: list[dict[str, Any]],
    events: list[dict[str, Any]],
    my_name: str | None,
) -> dict[str, Any]:
    """Aggregate stats for the bot across a room."""
    hands_played = len(timeline)
    participated_hands = sum(1 for h in timeline if h.get("participated"))

    # VPIP/PFR: compute from my first preflop action per hand.
    # Walk events again; need per-hand first preflop action.
    my_first_pf_by_hand: dict[int, str] = {}
    my_preflop_raised_by_hand: dict[int, bool] = {}
    current_hn: int | None = None
    current_phase: str | None = None
    for ev in events:
        if ev.get("dir") != "in":
            continue
        p = ev.get("event") or {}
        et = ev.get("type")
        if et == "hand_start":
            current_hn = p.get("hand_number") if isinstance(p.get("hand_number"), int) else None
            current_phase = "preflop"
            continue
        if et == "phase_change":
            current_phase = p.get("phase")
            continue
        if et == "action_request":
            # action_request carries phase explicitly.
            current_phase = p.get("phase")
            continue
        if et == "action_performed" and current_hn is not None:
            if p.get("player") == my_name and current_phase == "preflop":
                act = p.get("action")
                my_first_pf_by_hand.setdefault(current_hn, act)
                if act in ("raise", "allin"):
                    my_preflop_raised_by_hand[current_hn] = True

    vpip_hands = sum(
        1 for a in my_first_pf_by_hand.values() if a in ("call", "raise", "allin")
    )
    pfr_hands = sum(1 for v in my_preflop_raised_by_hand.values() if v)
    vpip_pct = (vpip_hands / hands_played * 100.0) if hands_played else 0.0
    pfr_pct = (pfr_hands / hands_played * 100.0) if hands_played else 0.0

    showdown_hands = [h for h in timeline if h.get("went_to_showdown")]
    showdown_count = len(showdown_hands)
    showdown_wins = sum(1 for h in showdown_hands if h.get("result") == "win")
    showdown_win_pct = (showdown_wins / showdown_count * 100.0) if showdown_count else 0.0

    total_winnings = 0
    for h in timeline:
        d = h.get("my_delta")
        if isinstance(d, (int, float)):
            total_winnings += d

    # Find game_end to get final rank.
    final_rank: int | None = None
    rankings: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("dir") != "in":
            continue
        if ev.get("type") != "game_end":
            continue
        p = ev.get("event") or {}
        rankings = p.get("rankings") or []
        for r in rankings:
            if isinstance(r, dict) and r.get("name") == my_name:
                final_rank = r.get("rank")
                break
        break

    # Determine alive/death.
    death_hand: int | None = None
    death_phase: str | None = None
    death_summary: str | None = None
    alive = True

    eliminated_hand = next(
        (h for h in timeline if h.get("eliminated_here")), None
    )
    if eliminated_hand is not None:
        alive = False
        death_hand = eliminated_hand.get("hand_number")
        death_phase = eliminated_hand.get("fold_street") or (
            "showdown" if eliminated_hand.get("went_to_showdown") else None
        )
        # Build summary: villain + my hand in showdown, or generic blinds text.
        showdowns = eliminated_hand.get("shown_cards") or []
        if showdowns:
            my_cards = None
            vill_parts: list[str] = []
            for s in showdowns:
                if not isinstance(s, dict):
                    continue
                nm = s.get("name")
                cards = s.get("cards")
                if nm == my_name:
                    my_cards = cards
                else:
                    vill_parts.append(
                        f"{nm} [{' '.join(cards or [])}]"
                    )
            my_text = f"내 [{' '.join(my_cards or [])}]" if my_cards else "내 카드 미공개"
            vill_text = " / ".join(vill_parts) if vill_parts else "상대 미공개"
            death_summary = f"{vill_text} > {my_text}"
        else:
            death_summary = "blinds 소진 / 사이드팟 패배"
    else:
        # Not explicitly eliminated but game ended → alive status derives from rankings.
        if final_rank is not None and rankings:
            my_row = next((r for r in rankings if r.get("name") == my_name), None)
            if my_row is not None:
                try:
                    chips = int(my_row.get("chips", 0) or 0)
                except (TypeError, ValueError):
                    chips = 0
                alive = chips > 0

    # Stack/blind tracking.
    max_stack: float | None = None
    min_stack: float | None = None
    last_stack: float | None = None
    last_blind: Any = None
    for h in timeline:
        for k in ("start_stack", "end_stack"):
            v = h.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if max_stack is None or fv > max_stack:
                max_stack = fv
            if min_stack is None or fv < min_stack:
                min_stack = fv
            last_stack = fv
    # Find last blind from events.
    for ev in reversed(events):
        if ev.get("dir") != "in":
            continue
        p = ev.get("event") or {}
        bl = p.get("blind")
        if isinstance(bl, (list, tuple)) and len(bl) >= 2:
            last_blind = bl
            break

    return {
        "hands_played": hands_played,
        "participated_hands": participated_hands,
        "vpip_pct": vpip_pct,
        "pfr_pct": pfr_pct,
        "showdown_count": showdown_count,
        "showdown_win_pct": showdown_win_pct,
        "total_winnings": total_winnings,
        "final_rank": final_rank,
        "alive": alive,
        "death_hand": death_hand,
        "death_phase": death_phase,
        "death_summary": death_summary,
        "max_stack": max_stack,
        "min_stack": min_stack,
        "last_stack": last_stack,
        "last_blind": last_blind,
    }


def compute_decision_index(
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[tuple, dict[str, Any]]:
    """Build a key→meta dict for my decisions.

    Key: (hand_number, phase, tuple(sorted(your_cards)), seat).

    Preferred source: outbound `action` records from `.debug` with a top-level
    `meta` dict (set by Phase A). We approximate (hand_number, phase, cards, seat)
    by looking back at the most recent `action_request` before the outbound action.

    Fallback: rows from `logs/decisions.jsonl` (same key).
    """
    index: dict[tuple, dict[str, Any]] = {}

    # Preferred: walk events in order, remembering last action_request context.
    last_req: dict[str, Any] | None = None
    for ev in events:
        d = ev.get("dir")
        if d == "in":
            if ev.get("type") == "action_request":
                last_req = ev.get("event") or {}
            continue
        if d != "out":
            continue
        if ev.get("kind") != "action":
            continue
        meta = ev.get("meta")
        if not isinstance(meta, dict) or not meta:
            continue
        if last_req is None:
            continue
        hn = last_req.get("hand_number")
        phase = last_req.get("phase")
        cards = last_req.get("your_cards")
        seat = last_req.get("seat")
        if hn is None or phase is None or not isinstance(cards, list):
            continue
        key = (hn, phase, tuple(sorted(cards)), seat)
        index[key] = meta

    # Fallback: merge in decisions (do not overwrite meta entries).
    for r in decisions:
        hn = r.get("hand_number")
        phase = r.get("phase")
        cards = r.get("your_cards")
        seat = r.get("seat")
        if hn is None or phase is None or not isinstance(cards, list):
            continue
        key = (hn, phase, tuple(sorted(cards)), seat)
        if key in index:
            continue
        # Pull only the decision-meta-like fields.
        snapshot = {
            k: r[k]
            for k in (
                "equity",
                "pot_odds",
                "reason",
                "made_hand",
                "made_hand_ko",
                "opp_tier",
            )
            if k in r
        }
        if snapshot:
            index[key] = snapshot

    return index


# --- Rendering ---------------------------------------------------------------


def _render_hero(
    st_mod, ctx: dict[str, Any], latest_decision: dict[str, Any]
) -> None:
    your_cards = ctx.get("your_cards")
    if isinstance(your_cards, list) and your_cards:
        cards_part = cards_html(your_cards)
    else:
        cards_part = empty_card_html() + empty_card_html()

    hand_num = latest_decision.get("hand_number") or ctx.get("hand_number", "?")
    phase_raw = latest_decision.get("phase") or ctx.get("phase", "-")
    phase = PHASE_KO.get(phase_raw, phase_raw) if isinstance(phase_raw, str) else phase_raw
    seat = ctx.get("your_seat") or ctx.get("seat") or latest_decision.get("seat") or "-"

    last_action = latest_decision.get("action")
    last_amount = latest_decision.get("amount")
    badge = (
        action_badge(last_action, last_amount) if last_action else ""
    )
    my_label = (
        '<span style="color:#666; font-size:13px;">내 마지막 액션:</span> '
        f"{badge}"
        if badge
        else '<span style="color:#999; font-size:13px;">아직 액션 없음</span>'
    )

    hero_html = (
        '<div style="display:flex; align-items:center; gap:20px; '
        'padding:12px; background:#f8f9fa; border-radius:8px;">'
        f'<div>{cards_part}</div>'
        '<div style="flex:1;">'
        f'<div style="font-size:18px; font-weight:600;">핸드 #{hand_num} · {phase}</div>'
        f'<div style="color:#666; font-size:13px; margin-top:2px;">자리: {seat}</div>'
        f'<div style="margin-top:6px;">{my_label}</div>'
        "</div>"
        "</div>"
    )
    st_mod.markdown(hero_html, unsafe_allow_html=True)


def _render_board(st_mod, ctx: dict[str, Any]) -> None:
    community = ctx.get("community_cards") or []
    if not isinstance(community, list):
        community = []

    slots: list[str] = []
    for i in range(5):
        if i < len(community):
            slots.append(card_html(community[i]))
        else:
            slots.append(back_card_html())

    board_html = (
        '<div style="padding:8px 0;">'
        '<div style="font-size:13px; color:#666; margin-bottom:4px;">보드</div>'
        f'<div>{"".join(slots)}</div>'
        "</div>"
    )
    st_mod.markdown(board_html, unsafe_allow_html=True)


def _render_players(
    st_mod, ctx: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    players = latest_players_snapshot(events)
    pot = ctx.get("pot", "-")
    blind = ctx.get("blind")
    blind_str = (
        f"{blind[0]}/{blind[1]}" if isinstance(blind, (list, tuple)) and len(blind) >= 2 else "-"
    )
    header_html = (
        f'<div style="font-size:14px; color:#333; margin:8px 0 4px 0;">'
        f"플레이어 (pot={pot}, blind={blind_str})"
        "</div>"
    )
    st_mod.markdown(header_html, unsafe_allow_html=True)

    if not players:
        st_mod.caption("플레이어 스냅샷 없음 (.debug 가 비활성이거나 데이터 없음)")
        return

    my_seat = ctx.get("your_seat") or ctx.get("seat")

    bets = []
    for p in players:
        try:
            bets.append(float(p.get("bet", 0) or 0))
        except (TypeError, ValueError):
            bets.append(0.0)
    max_bet = max(bets) if bets else 1
    if max_bet <= 0:
        max_bet = 1

    rows_html = []
    for p in players:
        p_seat = p.get("position") or p.get("seat")
        is_me = bool(my_seat) and p_seat == my_seat
        rows_html.append(player_row_html(p, max_bet, is_me=is_me))
    st_mod.markdown("".join(rows_html), unsafe_allow_html=True)


def _render_flow(
    st_mod,
    events: list[dict[str, Any]],
    hand_decisions: list[dict[str, Any]] | None = None,
    decision_index: dict[tuple, dict[str, Any]] | None = None,
    hand_number: int | None = None,
) -> None:
    flow = build_hand_flow(events, hand_number=hand_number)
    if not flow:
        st_mod.caption("아직 핸드 이벤트가 없습니다.")
        return

    # Attach decision_meta to my_turn rows that don't already have one,
    # using decision_index first then hand_decisions (phase match).
    if hand_decisions is None:
        hand_decisions = []
    for row in flow:
        if row.get("kind") != "my_turn":
            continue
        if row.get("decision_meta"):
            continue
        key = row.get("decision_key")
        if decision_index and key in decision_index:
            row["decision_meta"] = decision_index[key]
            continue
        phase = None
        if isinstance(key, tuple) and len(key) >= 2:
            phase = key[1]
        if phase is not None and hand_decisions:
            match = next(
                (d for d in hand_decisions if d.get("phase") == phase),
                None,
            )
            if match is not None:
                snapshot = {
                    k: match[k]
                    for k in (
                        "equity",
                        "pot_odds",
                        "reason",
                        "made_hand",
                        "made_hand_ko",
                        "opp_tier",
                    )
                    if k in match
                }
                if snapshot:
                    row["decision_meta"] = snapshot

    rows_html = [flow_row_html(r) for r in reversed(flow)]
    st_mod.markdown("".join(rows_html), unsafe_allow_html=True)


def _render_metrics(
    st_mod, ctx: dict[str, Any], latest_decision: dict[str, Any]
) -> None:
    to_call = latest_decision.get("to_call", ctx.get("to_call"))
    pot = latest_decision.get("pot", ctx.get("pot"))
    stack = ctx.get("stack")
    blind = ctx.get("blind")

    pot_odds = compute_pot_odds(to_call, pot)
    m_ratio = compute_m_ratio(stack, blind)
    equity = latest_decision.get("equity")
    reason = latest_decision.get("reason")
    made_ko = latest_decision.get("made_hand_ko") or latest_decision.get("made_hand")
    opp_tier = latest_decision.get("opp_tier")

    cols = st_mod.columns(6)
    cols[0].metric("to_call", to_call if to_call is not None else "-")
    cols[1].metric("stack", stack if stack is not None else "-")
    cols[2].metric(
        "pot odds",
        "-" if pot_odds is None else f"{pot_odds * 100:.1f}%",
    )
    cols[3].metric(
        "equity",
        "-" if equity is None else f"{float(equity) * 100:.1f}%",
        delta=reason if reason else None,
    )
    cols[4].metric(
        "내 패",
        made_ko if made_ko else "-",
        delta=f"상대 {opp_tier}" if opp_tier and opp_tier != "any" else None,
    )
    cols[5].metric("M", "-" if m_ratio is None else f"{m_ratio:.1f}")


def _render_past_decisions(st_mod, decisions: list[dict[str, Any]]) -> None:
    with st_mod.expander("과거 결정 전체"):
        if not decisions:
            st_mod.caption("아직 decide() 기록이 없습니다.")
            return
        table_rows = []
        for r in reversed(decisions):
            your = r.get("your_cards")
            community = r.get("community_cards")
            table_rows.append(
                {
                    "time": r.get("time"),
                    "hand_number": r.get("hand_number"),
                    "phase": r.get("phase"),
                    "seat": r.get("seat"),
                    "your_cards": " ".join(your) if isinstance(your, list) else your,
                    "community_cards": " ".join(community)
                    if isinstance(community, list)
                    else community,
                    "to_call": r.get("to_call"),
                    "pot": r.get("pot"),
                    "action": r.get("action"),
                    "amount": r.get("amount"),
                    "equity": r.get("equity"),
                    "pot_odds": r.get("pot_odds"),
                    "made_hand": r.get("made_hand_ko") or r.get("made_hand"),
                    "opp_tier": r.get("opp_tier"),
                    "reason": r.get("reason"),
                }
            )
        st_mod.dataframe(table_rows, width="stretch", hide_index=True)


def _render_bot_status_card(
    st_mod,
    timeline: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    """봇의 생존/탈락 상태와 세션 지표 6칸 카드."""
    alive = bool(stats.get("alive"))
    hands_played = stats.get("hands_played", 0)
    if alive:
        last_stack = stats.get("last_stack")
        last_blind = stats.get("last_blind")
        blind_str = (
            f"{last_blind[0]}/{last_blind[1]}"
            if isinstance(last_blind, (list, tuple)) and len(last_blind) >= 2
            else "-"
        )
        stack_txt = (
            f"{int(last_stack)}" if isinstance(last_stack, (int, float)) else "-"
        )
        banner_html = (
            '<div style="background:#eafaf1; border-left:6px solid #27ae60; '
            'padding:12px 16px; border-radius:8px;">'
            '<div style="font-size:20px; font-weight:700; color:#1e7e34;">'
            f"🟢 ALIVE · 스택 {stack_txt} · 블라인드 {blind_str}"
            "</div>"
            f'<div style="font-size:13px; color:#555; margin-top:2px;">'
            f"핸드 {hands_played}개 플레이 중</div>"
            "</div>"
        )
    else:
        death_hand = stats.get("death_hand")
        death_phase = stats.get("death_phase") or "-"
        death_phase_ko = PHASE_KO.get(death_phase, death_phase)
        summary = stats.get("death_summary") or ""
        rank = stats.get("final_rank")
        rank_txt = f" · 최종 {rank}위" if rank else ""
        banner_html = (
            '<div style="background:#fdeaea; border-left:6px solid #c0392b; '
            'padding:12px 16px; border-radius:8px;">'
            '<div style="font-size:20px; font-weight:700; color:#922b21;">'
            f"💀 ELIMINATED · Hand {death_hand} · {death_phase_ko} · {summary}{rank_txt}"
            "</div>"
            f'<div style="font-size:13px; color:#555; margin-top:2px;">'
            f"총 {hands_played}핸드 플레이</div>"
            "</div>"
        )
    st_mod.markdown(banner_html, unsafe_allow_html=True)

    cols = st_mod.columns(6)
    cols[0].metric("핸드수", hands_played)
    cols[1].metric("VPIP", f"{stats.get('vpip_pct', 0):.1f}%")
    cols[2].metric("PFR", f"{stats.get('pfr_pct', 0):.1f}%")
    cols[3].metric("쇼다운", stats.get("showdown_count", 0))
    cols[4].metric("SD승률", f"{stats.get('showdown_win_pct', 0):.1f}%")
    tot = stats.get("total_winnings", 0)
    sign = "+" if (isinstance(tot, (int, float)) and tot > 0) else ""
    cols[5].metric("총손익", f"{sign}{tot}")


def _render_session_timeline(
    st_mod, timeline: list[dict[str, Any]]
) -> None:
    """핸드별 스택 추이 + 결과 색상 dot 레이어."""
    if not timeline:
        st_mod.caption("핸드 이력이 없습니다.")
        return

    # Build rows suitable for charting.
    chart_rows: list[dict[str, Any]] = []
    for h in timeline:
        end_stack = h.get("end_stack")
        if end_stack is None:
            continue
        chart_rows.append(
            {
                "hand_number": h.get("hand_number"),
                "end_stack": end_stack,
                "result": h.get("result", "skipped"),
                "your_cards": " ".join(h.get("your_cards") or []),
                "fold_street": h.get("fold_street") or "-",
                "my_delta": h.get("my_delta"),
                "shown_cards": "; ".join(
                    f"{s.get('name')}[{' '.join(s.get('cards') or [])}]"
                    for s in (h.get("shown_cards") or [])
                    if isinstance(s, dict)
                ),
            }
        )

    if not chart_rows:
        st_mod.caption("차트용 스택 데이터가 없습니다.")
        return

    st_mod.markdown(
        '<div style="font-size:14px; color:#333; margin:8px 0 4px;">세션 타임라인 (핸드별 스택)</div>',
        unsafe_allow_html=True,
    )

    # Try altair first.
    try:
        import altair as alt  # type: ignore
        import pandas as pd  # type: ignore

        df = pd.DataFrame(chart_rows)
        line = (
            alt.Chart(df)
            .mark_line(color="#7f8c8d", strokeWidth=2)
            .encode(x="hand_number:Q", y="end_stack:Q")
        )
        dots = (
            alt.Chart(df)
            .mark_circle(size=90)
            .encode(
                x=alt.X("hand_number:Q", title="핸드"),
                y=alt.Y("end_stack:Q", title="스택"),
                color=alt.Color(
                    "result:N",
                    scale=alt.Scale(
                        domain=list(RESULT_COLORS.keys()),
                        range=list(RESULT_COLORS.values()),
                    ),
                    legend=alt.Legend(title="결과"),
                ),
                tooltip=[
                    "hand_number",
                    "your_cards",
                    "result",
                    "fold_street",
                    "my_delta",
                    "shown_cards",
                ],
            )
        )
        st_mod.altair_chart(line + dots, width="stretch")
        return
    except ImportError:
        pass
    except Exception:  # pragma: no cover - best-effort fallback
        pass

    # Pandas-only fallback.
    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame(chart_rows).set_index("hand_number")[["end_stack"]]
        st_mod.line_chart(df)
        return
    except ImportError:
        pass

    # No charting libs.
    st_mod.caption("altair/pandas 미설치 — 차트 생략")


def _render_showdown(st_mod, hand_events: list[dict[str, Any]]) -> None:
    """마지막 hand_result 의 showdown 표시."""
    last_result: dict[str, Any] | None = None
    for e in hand_events:
        if e.get("dir") != "in":
            continue
        if e.get("type") != "hand_result":
            continue
        last_result = e.get("event") or {}
    if not last_result:
        return
    showdown = last_result.get("showdown") or []
    if not showdown:
        st_mod.caption("쇼다운 아님")
        return

    my_name = st_mod.session_state.get("my_name") if hasattr(st_mod, "session_state") else None

    community = last_result.get("community_cards") or []
    st_mod.markdown(
        '<div style="font-size:14px; color:#333; margin:8px 0 4px;">쇼다운</div>',
        unsafe_allow_html=True,
    )
    rows_html: list[str] = []
    for entry in showdown:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        cards = entry.get("cards") or []
        cls = classify_hand(list(cards) + list(community)) if isinstance(cards, list) else {}
        made_ko = cls.get("category_ko", "-") if isinstance(cls, dict) else "-"
        is_me = bool(my_name) and name == my_name
        row_bg = "#fff7e6" if is_me else "#f8f9fa"
        me_tag = (
            '<span style="color:#e67e22; font-weight:700; margin-right:6px;">&#9654; 나</span>'
            if is_me
            else ""
        )
        row_html = (
            f'<div style="display:flex; align-items:center; gap:10px; '
            f'padding:6px 10px; background:{row_bg}; border-radius:6px; margin:2px 0;">'
            f"{me_tag}"
            f'<span style="font-weight:600;">{name}</span>'
            f"<span>{cards_html(list(cards))}</span>"
            f'<span style="color:#555;">메이드: <b>{made_ko}</b></span>'
            "</div>"
        )
        rows_html.append(row_html)
    st_mod.markdown("".join(rows_html), unsafe_allow_html=True)


def _render_hand_body(
    st_mod,
    hand_events: list[dict[str, Any]],
    hand_decisions: list[dict[str, Any]],
    decision_index: dict[tuple, dict[str, Any]] | None = None,
) -> None:
    """한 핸드의 Hero/Board/Players/Flow 4섹션."""
    hand_ctx = latest_hand_context(hand_events)
    last_dec = hand_decisions[-1] if hand_decisions else {}

    _render_hero(st_mod, hand_ctx, last_dec)
    _render_board(st_mod, hand_ctx)
    st_mod.markdown("")
    _render_players(st_mod, hand_ctx, hand_events)
    st_mod.markdown("")
    _render_flow(st_mod, hand_events, hand_decisions=hand_decisions, decision_index=decision_index)
    _render_showdown(st_mod, hand_events)


def _hand_expander_label(
    hand_number: int,
    hand_events: list[dict[str, Any]],
    hand_decisions: list[dict[str, Any]],
    my_hand_summary: dict[str, Any] | None = None,
) -> str:
    """핸드 expander 제목 — '핸드 #N · cards · my_action · winner · result-tokens'."""
    parts = [f"핸드 #{hand_number}"]

    your_cards: list[str] | None = None
    for e in hand_events:
        if e.get("dir") != "in":
            continue
        if e.get("type") != "hand_start":
            continue
        cards = (e.get("event") or {}).get("your_cards")
        if isinstance(cards, list) and cards:
            your_cards = cards
            break
    if your_cards:
        parts.append(" ".join(your_cards))

    if hand_decisions:
        last = hand_decisions[-1]
        act = last.get("action")
        amt = last.get("amount")
        if act:
            parts.append(f"{act}" + (f" {amt}" if amt else ""))

    winner_str = None
    for e in hand_events:
        if e.get("dir") != "in":
            continue
        if e.get("type") != "hand_result":
            continue
        winners = (e.get("event") or {}).get("winners") or []
        if winners:
            winner_str = "/".join(
                f"{w.get('name')}+{w.get('amount')}" for w in winners
            )
    if winner_str:
        parts.append(f"🏆 {winner_str}")

    if my_hand_summary:
        participated = my_hand_summary.get("participated")
        parts.append("참여" if participated else "미참여")
        fold_street = my_hand_summary.get("fold_street")
        if my_hand_summary.get("went_to_showdown"):
            parts.append("SD")
        elif fold_street:
            parts.append(f"fold@{fold_street}")
        delta = my_hand_summary.get("my_delta")
        result = my_hand_summary.get("result")
        if result == "win":
            parts.append(f"🏆 +{delta}" if isinstance(delta, (int, float)) and delta > 0 else "🏆")
        elif result in ("lose_showdown", "fold_post", "fold_pre"):
            if isinstance(delta, (int, float)) and delta < 0:
                parts.append(f"❌ {int(delta)}")
        if my_hand_summary.get("eliminated_here"):
            parts.append("💀 탈락")

    return "  ·  ".join(parts)


def _render_room_tab(
    st_mod,
    room_id: Any,
    decisions: list[dict[str, Any]],
    debug_dir: str | os.PathLike[str],
) -> None:
    """SQL 우선 — 룸 통계/타임라인을 store 에서 직접 쿼리."""
    debug_dir_str = str(debug_dir)
    mtime = _db_mtime(debug_dir_str)
    try:
        rid_int = int(room_id)
    except (TypeError, ValueError):
        st_mod.info("room_id 가 SQL-backed 룸이 아닙니다.")
        return

    hand_numbers = store_hand_numbers(rid_int, debug_dir_str, mtime)
    if not hand_numbers and not decisions:
        st_mod.info("이 방에는 아직 기록이 없습니다.")
        return

    my_name = store_detect_bot_name(rid_int, debug_dir_str, mtime)
    if hasattr(st_mod, "session_state") and my_name:
        st_mod.session_state["my_name"] = my_name

    hand_starts = store_hand_starts(rid_int, debug_dir_str, mtime)
    hand_results = store_hand_results(rid_int, debug_dir_str, mtime)
    my_actions = store_my_actions(rid_int, debug_dir_str, mtime)

    last_snapshot = store_latest_players(rid_int, debug_dir_str, mtime)
    last_my_stack: float | None = None
    if my_name and last_snapshot:
        for p in last_snapshot:
            if isinstance(p, dict) and p.get("name") == my_name:
                try:
                    last_my_stack = float(p.get("stack")) if p.get("stack") is not None else None
                except (TypeError, ValueError):
                    last_my_stack = None
                break

    timeline = _build_timeline_from_rows(
        hand_starts, hand_results, my_actions, my_name, last_my_stack
    )
    stats = store_room_summary(rid_int, debug_dir_str, mtime, my_name) if my_name else {}
    decision_index = _decision_index_from_actions(my_actions)

    if my_name and timeline:
        _render_bot_status_card(st_mod, timeline, stats)
        _render_session_timeline(st_mod, timeline)
        st_mod.divider()

    overall_ctx = store_latest_context(rid_int, debug_dir_str, mtime)
    latest_decision = my_actions[-1] if my_actions else (
        decisions[-1] if decisions else {}
    )

    _render_metrics(st_mod, overall_ctx, latest_decision)
    st_mod.divider()

    timeline_by_hand = {h.get("hand_number"): h for h in timeline}
    if not hand_numbers:
        st_mod.caption("이벤트에 hand_number 가 없습니다.")
    else:
        st_mod.subheader(f"핸드 목록 ({len(hand_numbers)}개)")
        my_actions_by_hand: dict[int, list[dict[str, Any]]] = {}
        for a in my_actions:
            hn = a.get("hand_number")
            if isinstance(hn, int):
                my_actions_by_hand.setdefault(hn, []).append(a)
        for idx, hn in enumerate(reversed(hand_numbers)):
            hand_events = store_hand_events(rid_int, debug_dir_str, mtime, hn)
            hand_decs = my_actions_by_hand.get(hn, []) or [
                d for d in decisions if d.get("hand_number") == hn
            ]
            label = _hand_expander_label(
                hn, hand_events, hand_decs, my_hand_summary=timeline_by_hand.get(hn)
            )
            with st_mod.expander(label, expanded=(idx == 0)):
                _render_hand_body(
                    st_mod, hand_events, hand_decs, decision_index=decision_index
                )

    st_mod.divider()
    _render_past_decisions(st_mod, my_actions or decisions)


def _render_aggregate_tab(
    st_mod,
    room_ids: list[Any],
    debug_dir: str | os.PathLike[str],
    log_path: str | os.PathLike[str],
) -> None:
    """전체 방 합산 통계 — 룸당 SQL 한 번씩만, 풀 이벤트 스캔 X."""
    debug_dir_str = str(debug_dir)
    mtime = _db_mtime(debug_dir_str)

    all_timelines: list[tuple[Any, str, list[dict[str, Any]]]] = []
    all_decision_indexes: list[tuple[Any, dict[tuple, dict[str, Any]]]] = []
    per_room_game_end: list[tuple[Any, list[dict[str, Any]]]] = []
    per_room_stats: list[tuple[Any, str, dict[str, Any]]] = []

    for rid in room_ids:
        try:
            rid_int = int(rid)
        except (TypeError, ValueError):
            continue
        my_name = store_detect_bot_name(rid_int, debug_dir_str, mtime)
        if not my_name:
            continue
        hand_starts = store_hand_starts(rid_int, debug_dir_str, mtime)
        hand_results = store_hand_results(rid_int, debug_dir_str, mtime)
        my_actions = store_my_actions(rid_int, debug_dir_str, mtime)
        last_snapshot = store_latest_players(rid_int, debug_dir_str, mtime)
        last_my_stack: float | None = None
        for p in last_snapshot:
            if isinstance(p, dict) and p.get("name") == my_name:
                try:
                    last_my_stack = (
                        float(p.get("stack")) if p.get("stack") is not None else None
                    )
                except (TypeError, ValueError):
                    last_my_stack = None
                break
        tl = _build_timeline_from_rows(
            hand_starts, hand_results, my_actions, my_name, last_my_stack
        )
        if not tl:
            continue
        stats = store_room_summary(rid_int, debug_dir_str, mtime, my_name)
        all_timelines.append((rid, my_name, tl))
        per_room_stats.append((rid, my_name, stats))
        all_decision_indexes.append((rid, _decision_index_from_actions(my_actions)))

        rankings = store_game_end_rankings(rid_int, debug_dir_str, mtime)
        if rankings:
            per_room_game_end.append((rid, rankings))

    if not all_timelines:
        st_mod.info("집계할 이력이 없습니다.")
        return

    # --- 0) 상단 요약 카드: 진행 게임 수 + 순위 분포 ---------------------------
    _render_game_summary_card(st_mod, per_room_stats)

    # --- 1) 프리플롭 홀카드 참여율 13x13 히트맵 ------------------------------
    st_mod.subheader("프리플롭 홀카드 참여율")
    _render_preflop_heatmap(st_mod, all_timelines)

    # --- 2) 스트리트별 내 액션 분포 -----------------------------------------
    st_mod.subheader("스트리트별 내 액션 분포")
    _render_street_action_chart(st_mod, all_timelines)

    # --- 3) 방별 최종 순위 --------------------------------------------------
    st_mod.subheader("방별 최종 순위")
    if not per_room_game_end:
        st_mod.caption("game_end 이벤트가 아직 없습니다.")
    else:
        rows: list[dict[str, Any]] = []
        for rid, rankings in per_room_game_end:
            for r in rankings:
                if not isinstance(r, dict):
                    continue
                rows.append(
                    {
                        "room": rid,
                        "rank": r.get("rank"),
                        "name": r.get("name"),
                        "chips": r.get("chips"),
                    }
                )
        if rows:
            st_mod.dataframe(rows, width="stretch", hide_index=True)

    # --- 4) Equity bin × outcome 캘리브레이션 -------------------------------
    st_mod.subheader("결정 근거 캘리브레이션 (equity bin × 결과)")
    _render_equity_calibration(st_mod, all_timelines, all_decision_indexes)


def _render_game_summary_card(
    st_mod,
    per_room_stats: list[tuple[Any, str, dict[str, Any]]],
) -> None:
    """진행 게임 수 + 내 봇 순위별 카운트 요약."""
    total_games = len(per_room_stats)
    # 순위별 카운트. final_rank 없는 방은 "진행중(탈락)" / "진행중(생존)" 로 분리.
    rank_counts: dict[int, int] = {}
    unfinished_alive = 0
    unfinished_dead = 0
    for _rid, _name, stats in per_room_stats:
        rank = stats.get("final_rank")
        alive = bool(stats.get("alive"))
        if isinstance(rank, int):
            rank_counts[rank] = rank_counts.get(rank, 0) + 1
        elif alive:
            unfinished_alive += 1
        else:
            unfinished_dead += 1

    sorted_ranks = sorted(rank_counts.keys())
    first = rank_counts.get(1, 0)
    second = rank_counts.get(2, 0)
    third = rank_counts.get(3, 0)
    fourth_plus = sum(v for r, v in rank_counts.items() if r >= 4)
    finished = sum(rank_counts.values())
    in_progress = unfinished_alive + unfinished_dead

    # 상단 헤더.
    header_html = (
        '<div style="padding:12px; background:#eef3fa; border-radius:8px; '
        'margin-bottom:8px;">'
        '<div style="font-size:16px; font-weight:700; margin-bottom:4px;">📊 전체 게임 요약</div>'
        f'<div style="font-size:13px; color:#555;">총 {total_games}게임</div>'
        '</div>'
    )
    st_mod.markdown(header_html, unsafe_allow_html=True)

    # Row 1: 진행중 / 종료 (크게)
    row1 = st_mod.columns(2)
    row1[0].metric(
        "진행중",
        in_progress,
        delta=f"생존 {unfinished_alive} / 탈락 {unfinished_dead}" if in_progress else None,
        delta_color="off",
    )
    row1[1].metric("종료", finished)

    # Row 2: 종료된 게임의 순위별 카운트
    st_mod.caption(f"종료된 {finished}게임 순위별 횟수" if finished else "아직 종료된 게임 없음")
    row2 = st_mod.columns(4)
    row2[0].metric("🥇 1등", first)
    row2[1].metric("🥈 2등", second)
    row2[2].metric("🥉 3등", third)
    row2[3].metric("4등+", fourth_plus)

    # 순위 전체 분포가 많으면 (>=5위 존재) 테이블로 추가 제공.
    if sorted_ranks and sorted_ranks[-1] > 4:
        st_mod.caption(
            "순위 전체 분포: "
            + " · ".join(f"{r}위 {rank_counts[r]}회" for r in sorted_ranks)
        )


_RANK_ORDER = "AKQJT98765432"


def _hand_bucket(cards: list[str]) -> tuple[str, bool] | None:
    """(row_rank, col_rank, suited?) → 13x13 grid label."""
    if not isinstance(cards, list) or len(cards) != 2:
        return None
    try:
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
    except (IndexError, TypeError):
        return None
    if r1 not in _RANK_ORDER or r2 not in _RANK_ORDER:
        return None
    suited = s1 == s2
    i1 = _RANK_ORDER.index(r1)
    i2 = _RANK_ORDER.index(r2)
    # Higher rank first.
    if i1 > i2:
        r1, r2 = r2, r1
    return (r1, r2, suited)


def _render_preflop_heatmap(
    st_mod,
    all_timelines: list[tuple[Any, str, list[dict[str, Any]]]],
) -> None:
    """13x13: AA 좌상단, offsuit 대각선 아래, suited 위."""
    totals: dict[tuple[str, str, bool], int] = {}
    played: dict[tuple[str, str, bool], int] = {}
    for _rid, _me, tl in all_timelines:
        for h in tl:
            bucket = _hand_bucket(h.get("your_cards") or [])
            if bucket is None:
                continue
            r_hi, r_lo, suited = bucket
            pair = r_hi == r_lo
            # For pairs, both "suited/offsuit" collapse to one bucket.
            key = (r_hi, r_lo, suited if not pair else False)
            totals[key] = totals.get(key, 0) + 1
            if h.get("participated"):
                played[key] = played.get(key, 0) + 1

    rows: list[dict[str, Any]] = []
    for i, row_rank in enumerate(_RANK_ORDER):
        for j, col_rank in enumerate(_RANK_ORDER):
            if i == j:
                key = (row_rank, row_rank, False)
                label = f"{row_rank}{row_rank}"
            elif i < j:
                key = (row_rank, col_rank, True)
                label = f"{row_rank}{col_rank}s"
            else:
                key = (col_rank, row_rank, False)
                label = f"{col_rank}{row_rank}o"
            t = totals.get(key, 0)
            p = played.get(key, 0)
            pct = (p / t * 100.0) if t else None
            rows.append(
                {
                    "row": row_rank,
                    "col": col_rank,
                    "label": label,
                    "total": t,
                    "played": p,
                    "played_pct": pct,
                }
            )

    try:
        import altair as alt  # type: ignore
        import pandas as pd  # type: ignore

        df = pd.DataFrame(rows)
        heat = (
            alt.Chart(df)
            .mark_rect()
            .encode(
                x=alt.X("col:N", sort=list(_RANK_ORDER), title=None),
                y=alt.Y("row:N", sort=list(_RANK_ORDER), title=None),
                color=alt.Color(
                    "played_pct:Q",
                    scale=alt.Scale(scheme="greens"),
                    legend=alt.Legend(title="참여%"),
                ),
                tooltip=["label", "total", "played", "played_pct"],
            )
            .properties(width=520, height=520)
        )
        text = (
            alt.Chart(df)
            .mark_text(fontSize=10)
            .encode(
                x=alt.X("col:N", sort=list(_RANK_ORDER)),
                y=alt.Y("row:N", sort=list(_RANK_ORDER)),
                text="label:N",
            )
        )
        st_mod.altair_chart(heat + text, width="content")
    except ImportError:
        st_mod.dataframe(rows, width="stretch", hide_index=True)
    except Exception:  # pragma: no cover
        st_mod.dataframe(rows, width="stretch", hide_index=True)


def _render_street_action_chart(
    st_mod,
    all_timelines: list[tuple[Any, str, list[dict[str, Any]]]],
) -> None:
    """스트리트별로 내 fold/call/raise/check/allin count 집계. decisions 로 간접 계산."""
    # We don't have per-street action counts directly in timeline; use decisions.
    # Fallback: derive from events directly using my_name per room.
    counts: dict[tuple[str, str], int] = {}
    from collections import Counter

    for _rid, _me, tl in all_timelines:
        # Use timeline-derived fold_street as a coarse proxy for "fold" counts only;
        # skip participated-but-not-shown detail since it's approximate.
        c = Counter()
        for h in tl:
            fold_street = h.get("fold_street")
            if fold_street:
                c[(fold_street, "fold")] += 1
            if h.get("went_to_showdown"):
                c[("showdown", "reached")] += 1
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v

    rows = [
        {"phase": k[0], "action": k[1], "count": v} for k, v in counts.items()
    ]
    if not rows:
        st_mod.caption("액션 집계 없음")
        return
    try:
        import altair as alt  # type: ignore
        import pandas as pd  # type: ignore

        df = pd.DataFrame(rows)
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X("phase:N", title="스트리트"),
                y=alt.Y("count:Q", title="건수"),
                color="action:N",
                tooltip=["phase", "action", "count"],
            )
        )
        st_mod.altair_chart(chart, width="stretch")
    except ImportError:
        st_mod.dataframe(rows, width="stretch", hide_index=True)
    except Exception:  # pragma: no cover
        st_mod.dataframe(rows, width="stretch", hide_index=True)


def _render_equity_calibration(
    st_mod,
    all_timelines: list[tuple[Any, str, list[dict[str, Any]]]],
    all_decision_indexes: list[tuple[Any, dict[tuple, dict[str, Any]]]],
) -> None:
    """Equity bin × 결과 표: 10% 단위로 grouping."""
    # Build per-hand winner indicator.
    win_by_room_hand: dict[tuple[Any, int], str] = {}
    for rid, _me, tl in all_timelines:
        for h in tl:
            win_by_room_hand[(rid, h.get("hand_number"))] = h.get("result", "skipped")

    bin_counter: dict[tuple[int, str], int] = {}
    total_by_bin: dict[int, int] = {}
    for rid, idx in all_decision_indexes:
        for key, meta in idx.items():
            eq = meta.get("equity") if isinstance(meta, dict) else None
            if eq is None:
                continue
            try:
                eq_f = float(eq)
            except (TypeError, ValueError):
                continue
            bin_idx = min(int(eq_f * 10), 9)
            hn = key[0] if isinstance(key, tuple) else None
            outcome = win_by_room_hand.get((rid, hn), "skipped")
            bin_counter[(bin_idx, outcome)] = bin_counter.get((bin_idx, outcome), 0) + 1
            total_by_bin[bin_idx] = total_by_bin.get(bin_idx, 0) + 1

    if not total_by_bin:
        st_mod.caption("equity 기록 있는 결정이 없습니다. (구 로그에는 meta 없음)")
        return

    rows: list[dict[str, Any]] = []
    for b in sorted(total_by_bin):
        lo, hi = b * 10, (b + 1) * 10
        total = total_by_bin[b]
        for outcome in ("win", "lose_showdown", "fold_pre", "fold_post", "eliminated", "skipped"):
            c = bin_counter.get((b, outcome), 0)
            if c == 0:
                continue
            rows.append(
                {
                    "equity_bin": f"{lo}-{hi}%",
                    "outcome": outcome,
                    "count": c,
                    "pct_of_bin": f"{c / total * 100:.1f}%",
                    "bin_total": total,
                }
            )
    st_mod.dataframe(rows, width="stretch", hide_index=True)


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Holdem Agent Dashboard", layout="wide")
    st.title("Holdem Agent — Room Dashboard")

    log_path = os.environ.get("DECISION_LOG_PATH", "logs/decisions.jsonl")
    debug_dir = os.environ.get("DEBUG_DIR", ".debug")
    db_path = Path(debug_dir) / "holdem.db"
    backend = "SQLite" if db_path.exists() else "JSONL fallback"
    st.caption(
        f"backend: **{backend}** · events: `{debug_dir}/holdem.db`"
        f" · decisions: `{log_path}`"
    )

    mtime = _db_mtime(debug_dir)
    room_ids = store_list_rooms(debug_dir, mtime) if db_path.exists() else discover_rooms(debug_dir)

    if not room_ids:
        st.info(
            "아직 기록이 없습니다. 봇이 방에 배정되면 여기에 방이 나타납니다."
        )
        return

    tab_room, tab_agg = st.tabs(["방별 상세", "전체 통계"])

    with tab_room:
        col_sel, col_btn = st.columns([5, 1])
        with col_sel:
            selected = st.radio(
                "방 선택",
                options=room_ids,
                format_func=lambda r: f"room {r}",
                horizontal=True,
                key="selected_room",
            )
        with col_btn:
            st.button("갱신", width="stretch")

        decisions = load_decisions_for_room(log_path, selected)
        _render_room_tab(st, selected, decisions, debug_dir=debug_dir)

    with tab_agg:
        _render_aggregate_tab(st, room_ids, debug_dir, log_path)


if __name__ == "__main__":
    main()
