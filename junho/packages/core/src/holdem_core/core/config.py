"""홀덤 봇 공용 Settings.

각 봇 패키지는 자기 `.env` 파일을 `load_settings(env_file=...)` 로 주입한다.
루트의 `.env` 는 사용하지 않음 — 봇별 .env 분리 원칙.

- `HOLDEM_ENV_FILE` 환경변수로 경로 override 가능
- `load_settings` 인자로 주면 그걸 최우선
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "holdem-agent"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    PORT: int = 4000
    SERVER_WS_URL: str = "ws://localhost:5051/ws"
    BOT_API_TOKEN: str = ""
    BOT_NAME: str = "holdem-agent"

    # v5.4: deploy 자동화. WS 인증만으로는 방 배정 안 됨 (BOT_REFERENCE.md §2.2).
    # DASHBOARD_URL + BOT_ID 둘 다 채워져 있으면 부팅 시 한 번 POST 로 deploy.
    # 비어 있으면 사용자가 대시보드에서 수동 deploy 해야 함 (그 경우 ERROR 로그 안내).
    DASHBOARD_URL: str = ""
    BOT_ID: int = 0
    AUTO_DEPLOY: bool = True
    RECONNECT_INITIAL_BACKOFF_S: float = 1.0
    RECONNECT_MAX_BACKOFF_S: float = 30.0
    ACTION_LOG_BUFFER: int = 50
    DEBUG_EVENTS: bool = False
    DEBUG_DIR: str = ".debug"
    DECISION_LOG_PATH: str = "logs/decisions.jsonl"
    VIZ_ENABLED: bool = True
    VIZ_PORT: int = 8501
    # viz dashboard 경로. 기본은 tools 패키지의 dashboard.py — 봇이 자기 전용 대시보드를
    # 쓰고 싶으면 .env 에서 덮어씀. 비어 있으면 VIZ_ENABLED 와 무관하게 viz 기동 안 함.
    VIZ_DASHBOARD_PATH: str = ""

    # 플롭 전략 임계값 — 기본값. 각 봇이 자기 `StrategyConfig` 로 덮어쓸 수 있음.
    MC_SAMPLES: int = 2000
    EQUITY_CALL_MARGIN: float = 0.03
    EQUITY_VALUE_BET_THRESHOLD: float = 0.65
    EQUITY_RAISE_THRESHOLD: float = 0.80
    MAX_BET_FRACTION_OF_POT: float = 0.5
    POSTFLOP_CALL_CAP_FRACTION: float = 1.0


def _resolve_env_file(explicit: str | Path | None) -> Path | None:
    """우선순위: 인자 > HOLDEM_ENV_FILE env > None(세팅 기본값만)."""
    if explicit:
        return Path(explicit).resolve()
    from_env = os.environ.get("HOLDEM_ENV_FILE")
    if from_env:
        return Path(from_env).resolve()
    return None


def load_settings(env_file: str | Path | None = None) -> Settings:
    """봇별 `.env` 를 명시적으로 읽어 Settings 생성.

    cache 는 `env_file` 경로 기준. 같은 경로로 재호출하면 같은 인스턴스.
    """
    path = _resolve_env_file(env_file)
    return _cached(path if path else None)


@lru_cache(maxsize=8)
def _cached(env_path: Path | None) -> Settings:
    if env_path and env_path.exists():
        # pydantic-settings 는 env_file 을 BaseSettings 레벨에서 읽음.
        return Settings(_env_file=str(env_path))  # type: ignore[call-arg]
    return Settings()
