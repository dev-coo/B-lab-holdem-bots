"""room_id별 WS 이벤트 덤프 (`.debug/` 하위 SQLite, 옵션 JSONL).

기본은 SQLite (`{base_dir}/holdem.db`) 단일 적재. `HOLDEM_DEBUG_JSONL=1` 로
켜면 JSONL (`{base_dir}/room_*.jsonl`) 도 함께 쓴다 (긴급 백업/디버그용).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from holdem_core.core.logging import get_logger
from holdem_core.debug.store import DebugStore, jsonl_writes_enabled

logger = get_logger(__name__)

_GLOBAL = "_global"


class DebugDumper:
    def __init__(self, enabled: bool, base_dir: str) -> None:
        self.enabled = enabled
        self.base_dir = Path(base_dir)
        self.run_id: str = ""
        self.bot_name: str = ""
        self._marked: set[str] = set()
        self.store: DebugStore | None = None
        if self.enabled:
            try:
                self.base_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("debug_dump_mkdir_failed", extra={"error": repr(e)})
                self.enabled = False
            if self.enabled:
                try:
                    self.store = DebugStore.open(self.base_dir)
                except Exception as e:  # noqa: BLE001
                    logger.warning("debug_store_open_failed", extra={"error": repr(e)})
                    self.store = None

    def begin_run(self, bot_name: str) -> None:
        if not self.enabled:
            return
        self.run_id = str(uuid.uuid4())
        self.bot_name = bot_name
        self._marked = set()
        if self.store is not None:
            try:
                self.store.record_marker(run_id=self.run_id, bot_name=bot_name)
            except Exception as e:  # noqa: BLE001
                logger.warning("debug_store_marker_failed", extra={"error": repr(e)})
        if jsonl_writes_enabled():
            self._write(
                _GLOBAL,
                {
                    "_run_started": time.time(),
                    "run_id": self.run_id,
                    "bot_name": bot_name,
                },
            )

    def inbound(self, raw: str | bytes, evt: object | None) -> None:
        if not self.enabled:
            return
        if isinstance(raw, bytes):
            raw_str = raw.decode("utf-8", errors="replace")
        else:
            raw_str = raw
        room_id = getattr(evt, "room_id", None) if evt is not None else None
        evt_type = getattr(evt, "type", None) if evt is not None else None
        event_dump: Any = None
        if evt is not None and hasattr(evt, "model_dump"):
            try:
                event_dump = evt.model_dump()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                event_dump = None
        ts = time.time()
        if self.store is not None:
            try:
                self.store.record_inbound(
                    run_id=self.run_id or None,
                    room_id=room_id,
                    evt_type=evt_type,
                    raw_text=raw_str,
                    payload=event_dump if isinstance(event_dump, dict) else None,
                    bot_name=self.bot_name or None,
                    ts=ts,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("debug_store_inbound_failed", extra={"error": repr(e)})
        if jsonl_writes_enabled():
            record: dict[str, Any] = {
                "ts": ts,
                "run_id": self.run_id,
                "dir": "in",
                "type": evt_type,
                "room_id": room_id,
                "raw": raw_str,
                "event": event_dump,
            }
            self._write(self._key(room_id), record)

    def outbound(
        self,
        payload: str,
        kind: str,
        room_id: int | None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """송신 메시지 + (옵션) 결정 근거 meta 를 함께 기록.

        `meta` 는 `Action.meta` 에서 꺼낸 값으로, 네트워크 payload 에는 포함되지 않고
        이 로그에만 병합된다. 대시보드/분석기가 outbound action 레코드만 봐도 결정
        근거(equity, pot_odds, reason 등) 를 파악할 수 있게 된다.
        """
        if not self.enabled:
            return
        try:
            parsed: Any = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None
        ts = time.time()
        if self.store is not None:
            try:
                self.store.record_outbound(
                    run_id=self.run_id or None,
                    room_id=room_id,
                    kind=kind,
                    payload=parsed if parsed is not None else payload,
                    meta=meta,
                    bot_name=self.bot_name or None,
                    ts=ts,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("debug_store_outbound_failed", extra={"error": repr(e)})
        if jsonl_writes_enabled():
            record: dict[str, Any] = {
                "ts": ts,
                "run_id": self.run_id,
                "dir": "out",
                "kind": kind,
                "room_id": room_id,
                "payload": parsed if parsed is not None else payload,
            }
            if meta is not None:
                record["meta"] = meta
            self._write(self._key(room_id), record)

    def close(self) -> None:
        """SQLite store 핸들 정리 (WAL checkpoint + connection close)."""
        if self.store is not None:
            try:
                self.store.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("debug_store_close_failed", extra={"error": repr(e)})
            self.store = None

    def _key(self, room_id: int | None) -> str:
        return _GLOBAL if room_id is None else f"room_{room_id}"

    def _path(self, key: str) -> Path:
        return self.base_dir / f"{key}.jsonl"

    def _write(self, key: str, record: dict[str, Any]) -> None:
        path = self._path(key)
        try:
            need_marker = (
                key != _GLOBAL and key not in self._marked and "_run_started" not in record
            )
            with path.open("a", encoding="utf-8") as f:
                if need_marker:
                    marker = {
                        "_run_started": time.time(),
                        "run_id": self.run_id,
                    }
                    f.write(json.dumps(marker, ensure_ascii=False, default=str) + "\n")
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._marked.add(key)
        except OSError as e:
            logger.warning("debug_dump_write_failed", extra={"error": repr(e), "key": key})
