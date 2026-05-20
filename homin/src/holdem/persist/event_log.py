"""이벤트 JSONL 로거 — 방(room_id) 별 파일 분리.

파일 경로: data/logs/games/{YYYYMMDD}_room{room_id}.jsonl
각 줄 포맷:
  {"ts":"2026-04-19T14:23:00.123Z","room_id":1,"direction":"in|out","type":"...","payload":{...}}

설계:
  - 스레드 안전 필요 없음 (asyncio 단일 이벤트 루프).
  - 파일 핸들은 lazy open, 프로세스 종료 시 닫힘.
  - room_id 가 없는 이벤트(auth_ok 등) 는 room_id=0 에 기록.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..transport import protocol as p

log = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "logs" / "games"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _extract_room_id(payload: dict[str, Any]) -> int:
    raw = payload.get("room_id")
    if isinstance(raw, int):
        return raw
    return 0


def _model_dump(obj) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return {"repr": repr(obj)}


class EventLogger:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or _DEFAULT_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[int, Any] = {}

    def _file_for(self, room_id: int):
        fh = self._files.get(room_id)
        if fh is not None:
            return fh
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self._base_dir / f"{date}_room{room_id}.jsonl"
        fh = path.open("a", encoding="utf-8")
        self._files[room_id] = fh
        return fh

    def log_in(self, event) -> None:
        payload = _model_dump(event)
        room_id = _extract_room_id(payload)
        self._write(room_id, "in", payload)

    def log_out(self, action) -> None:
        if isinstance(action, p.Action):
            payload = action.to_payload()
        else:
            payload = _model_dump(action)
        room_id = _extract_room_id(payload)
        self._write(room_id, "out", payload)

    def _write(self, room_id: int, direction: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": _iso_now(),
            "room_id": room_id,
            "direction": direction,
            "type": payload.get("type", "unknown"),
            "payload": payload,
        }
        try:
            fh = self._file_for(room_id)
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            fh.flush()
        except Exception:
            log.exception("failed to write event log room=%s", room_id)

    def close(self) -> None:
        for fh in self._files.values():
            try:
                fh.close()
            except Exception:
                pass
        self._files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
