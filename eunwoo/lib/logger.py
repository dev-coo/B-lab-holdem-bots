"""
GameLogger — 핸드 단위 JSON 로거 (멀티룸 지원)

WebSocket으로 수신한 메시지를 room_id별로 분리해 핸드 단위로 묶어 JSON 파일로 저장한다.
저장 경로: logs/{YYYY-MM-DD}/room_{room_id}_{bot_name}.json
중복 파일명은 room_{id}_{bot_name}_1.json 순으로 처리한다.
"""

import json
import os
import tempfile
from datetime import date
from typing import Any


# 현재 핸드의 events 로 분류할 메시지 타입 집합
_HAND_EVENT_TYPES = {
    "action_performed",
    "action_request",
    "phase_change",
    "player_joined",
    "player_left",
}


class _RoomState:
    """방 하나의 로깅 상태."""

    __slots__ = ("game_start", "hands", "cur_hand_start", "cur_events", "cur_hand_result")

    def __init__(self) -> None:
        self.game_start: dict | None = None
        self.hands: list[dict] = []
        self.cur_hand_start: dict | None = None
        self.cur_events: list[dict] = []
        self.cur_hand_result: dict | None = None


class GameLogger:
    def __init__(self, bot_name: str, log_dir: str = "logs") -> None:
        self.bot_name = bot_name
        self.log_dir = log_dir
        self._rooms: dict[Any, _RoomState] = {}

    def _get_room(self, room_id: Any) -> _RoomState:
        if room_id not in self._rooms:
            self._rooms[room_id] = _RoomState()
        return self._rooms[room_id]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, msg: dict) -> None:
        """WS 메시지를 타입에 따라 라우팅해 기록한다."""
        msg_type = msg.get("type", "")
        room_id = msg.get("room_id")

        if msg_type == "game_start":
            room = self._get_room(room_id)
            room.game_start = msg

        elif msg_type == "hand_start":
            room = self._get_room(room_id)
            # 이전 핸드가 finalize 없이 남아있으면 자동 정리
            if room.cur_hand_start is not None:
                self.finalize_hand(room_id)
            room.cur_hand_start = msg
            room.cur_events = []
            room.cur_hand_result = None

        elif msg_type in _HAND_EVENT_TYPES:
            room = self._get_room(room_id)
            # 딕셔너리 복사본을 저장해 나중에 _my_action 추가 시 원본에 영향 없게 함
            room.cur_events.append(dict(msg))

        elif msg_type == "hand_result":
            room = self._get_room(room_id)
            room.cur_hand_result = msg

    def record_my_action(self, action_request: dict, action: str, amount: int) -> None:
        """
        events 목록에서 action_request 이벤트를 찾아 _my_action 필드를 추가한다.

        먼저 동일 객체(id)를 찾고, 없으면 _my_action이 없는 마지막 action_request를
        대상으로 삼는다.
        """
        room_id = action_request.get("room_id")
        room = self._get_room(room_id)
        my_action = {"action": action, "amount": amount}

        # 1순위: 동일 내용 매칭
        target = None
        for event in reversed(room.cur_events):
            if event.get("type") == "action_request" and "_my_action" not in event:
                candidate = {k: v for k, v in event.items() if k != "_my_action"}
                if candidate == action_request:
                    target = event
                    break

        # 2순위: 매칭 실패 시 마지막 미태그 action_request
        if target is None:
            for event in reversed(room.cur_events):
                if event.get("type") == "action_request" and "_my_action" not in event:
                    target = event
                    break

        if target is not None:
            target["_my_action"] = my_action

    def finalize_hand(self, room_id: Any = None) -> None:
        """현재 핸드를 닫고 hands 목록에 추가한다."""
        room = self._rooms.get(room_id)
        if room is None or room.cur_hand_start is None:
            return

        hand_entry: dict[str, Any] = {
            "hand_start": room.cur_hand_start,
            "events": list(room.cur_events),
        }
        if room.cur_hand_result is not None:
            hand_entry["hand_result"] = room.cur_hand_result

        room.hands.append(hand_entry)

        # 상태 초기화
        room.cur_hand_start = None
        room.cur_events = []
        room.cur_hand_result = None

    def finalize_game(self, game_end: dict) -> None:
        """
        게임을 종료하고 JSON 파일을 저장한다.
        저장 후 해당 방 상태를 제거해 같은 인스턴스로 다음 게임을 기록할 수 있다.
        """
        room_id = game_end.get("room_id")
        room = self._rooms.get(room_id)

        # 아직 닫히지 않은 핸드가 있으면 자동 정리
        if room is not None and room.cur_hand_start is not None:
            self.finalize_hand(room_id)

        payload = {
            "bot_name": self.bot_name,
            "game_start": room.game_start if room else None,
            "hands": room.hands if room else [],
            "game_end": game_end,
        }

        file_path = self._resolve_path(room_id)
        dir_path = os.path.dirname(file_path)
        os.makedirs(dir_path, exist_ok=True)
        # atomic write: 임시파일에 쓰고 rename (동시 실행 시 겹쳐쓰기 방지)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, file_path)
        except BaseException:
            os.unlink(tmp_path)
            raise

        # 해당 방 상태 제거
        self._rooms.pop(room_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_path(self, room_id: Any) -> str:
        """중복 없는 저장 경로를 반환한다."""
        today = date.today().isoformat()
        date_dir = os.path.join(self.log_dir, today)
        base = f"room_{room_id}_{self.bot_name}.json"
        path = os.path.join(date_dir, base)

        if not os.path.exists(path):
            return path

        # 같은 봇이 같은 방에 재입장한 경우
        counter = 1
        while True:
            candidate = os.path.join(
                date_dir, f"room_{room_id}_{self.bot_name}_{counter}.json"
            )
            if not os.path.exists(candidate):
                return candidate
            counter += 1
