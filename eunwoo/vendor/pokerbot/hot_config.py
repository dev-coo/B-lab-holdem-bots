"""Hot Reload 설정 — 게임 중 재시작 없이 전략 파라미터 교체

파일 변경 감지 → 자동 리로드. 게임 상태(GameState, Profiler)는 유지.

사용법:
    config = HotConfig("wooz")
    val = config.get("postflop.bluff_prob", 0.3)

외부에서 수정:
    vi ~/pokerbot/strategy_config.json  → 저장하면 10초 내 반영
    또는
    curl -X POST http://localhost:9191/config/reload
"""

import json
import os
import time
import threading
import logging
from pathlib import Path

logger = logging.getLogger("pokerbot.config")

CONFIG_PATH = Path(__file__).parent / "strategy_config.json"


class HotConfig:
    """파일 기반 Hot Reload 설정"""

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self._config: dict = {}
        self._last_mtime: float = 0
        self._lock = threading.Lock()
        self._load()
        self._start_watcher()

    def _load(self):
        """설정 파일 로드"""
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime == self._last_mtime:
                return False

            with open(CONFIG_PATH, "r") as f:
                all_config = json.load(f)

            with self._lock:
                self._config = all_config.get(self.bot_name, {})
                self._last_mtime = mtime

            logger.info(f"설정 리로드 완료: {self.bot_name}")
            return True
        except Exception as e:
            logger.error(f"설정 로드 실패: {e}")
            return False

    def _start_watcher(self):
        """백그라운드 파일 감시 (10초 간격)"""
        def watch():
            while True:
                time.sleep(10)
                self._load()

        t = threading.Thread(target=watch, daemon=True)
        t.start()

    def reload(self) -> bool:
        """수동 리로드 (API 엔드포인트용)"""
        self._last_mtime = 0  # 강제 리로드
        return self._load()

    def get(self, key: str, default=None):
        """점(dot) 표기법으로 중첩 설정 조회.

        예: config.get("postflop.bluff_prob", 0.3)
        """
        with self._lock:
            parts = key.split(".")
            value = self._config
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return default
                if value is None:
                    return default
            return value

    def get_section(self, section: str) -> dict:
        """섹션 전체 반환"""
        with self._lock:
            return self._config.get(section, {})

    @property
    def all(self) -> dict:
        with self._lock:
            return self._config.copy()
