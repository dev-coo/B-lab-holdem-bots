"""봇 실행 환경 설정 — 환경변수 기반.

.env 파일이 있으면 자동 로드 (python-dotenv 사용).
Env:
  HOLDEM_WS_URL        (default: ws://snn.it.kr:5051/ws)
  HOLDEM_API_TOKEN     (required)
  HOLDEM_BOT_NAME      (required)
  HOLDEM_LOG_LEVEL     (default: INFO)
"""
from __future__ import annotations

import os

from .._env import load_dotenv
from .ws_client import BotConfig

DEFAULT_WS_URL = "ws://snn.it.kr:5051/ws"


def load_bot_config() -> BotConfig:
    load_dotenv()
    token = os.environ.get("HOLDEM_API_TOKEN")
    name = os.environ.get("HOLDEM_BOT_NAME")
    if not token:
        raise SystemExit("HOLDEM_API_TOKEN 환경변수 필요")
    if not name:
        raise SystemExit("HOLDEM_BOT_NAME 환경변수 필요")
    return BotConfig(
        ws_url=os.environ.get("HOLDEM_WS_URL", DEFAULT_WS_URL),
        api_token=token,
        bot_name=name,
    )
