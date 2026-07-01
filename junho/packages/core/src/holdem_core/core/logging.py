"""JSON 로거 설정.

전략 패키지가 `register_decision_logger(name)` 으로 자기 logger 이름을 등록하면
해당 로거에 `DECISION_LOG_PATH` 파일 핸들러가 자동 부착된다. 봇별 `.env` 로
`DECISION_LOG_PATH` 가 바뀌어도 `reattach_decision_loggers(settings)` 를 호출하면
기존 파일 핸들러를 제거하고 새 경로로 재연결한다 (봇별 로그 격리).

`core.app.run()` 이 `.env` 로딩 직후 자동으로 이 재연결을 수행한다.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from holdem_core.core.config import Settings

_CONFIGURED: set[str] = set()
_DECISION_LOGGER_NAMES: set[str] = set()
_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_ATTRS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_decision_path(settings: "Settings | None") -> Path:
    """Settings 가 주어지면 그걸, 아니면 기본 설정에서 DECISION_LOG_PATH 해석."""
    if settings is None:
        from holdem_core.core.config import load_settings

        settings = load_settings()
    path = Path(settings.DECISION_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _attach_decision_file_handler(
    logger: logging.Logger, settings: "Settings | None" = None
) -> None:
    """logger 에 결정 로그 파일 핸들러를 부착. 기존에 다른 경로 핸들러가 있으면 제거 후 교체."""
    target = _resolve_decision_path(settings)

    # 같은 경로면 유지, 다른 경로 FileHandler 는 제거 후 교체.
    keep: list[logging.Handler] = []
    for existing in logger.handlers:
        if isinstance(existing, logging.FileHandler):
            if Path(existing.baseFilename).resolve() == target:
                return  # 이미 올바른 경로에 부착돼 있음
            # 다른 경로의 FileHandler — 제거 대상
            try:
                existing.close()
            except Exception:  # noqa: BLE001
                pass
            continue
        keep.append(existing)
    logger.handlers = keep

    file_handler = logging.FileHandler(target, mode="a", encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)


def register_decision_logger(
    name: str, settings: "Settings | None" = None
) -> None:
    """전략 모듈이 자기 logger name 을 '결정 로거' 로 등록.

    이미 같은 이름의 logger 가 존재하면 즉시 파일 핸들러 부착.
    Settings 가 주어지면 그 경로를, 아니면 현재 로드된 기본 Settings 를 사용.
    """
    _DECISION_LOGGER_NAMES.add(name)
    existing = logging.getLogger(name)
    _attach_decision_file_handler(existing, settings)


def reattach_decision_loggers(settings: "Settings") -> None:
    """봇별 `.env` 로딩 후 모든 decision logger 를 새 `DECISION_LOG_PATH` 로 재연결.

    `core.app.run()` 이 Settings 로드 직후 호출. 기존 핸들러는 제거되고 봇 전용
    경로로 새 핸들러가 부착된다.
    """
    for name in _DECISION_LOGGER_NAMES:
        logger = logging.getLogger(name)
        _attach_decision_file_handler(logger, settings)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if name not in _CONFIGURED:
        if not any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in logger.handlers
        ):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
            logger.propagate = False
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)
        if name in _DECISION_LOGGER_NAMES:
            _attach_decision_file_handler(logger)
        _CONFIGURED.add(name)
    return logger
