"""FastAPI 앱 팩토리 + uvicorn 실행 헬퍼.

각 봇 패키지는 자기 Strategy 를 만들어서 `create_app(strategy, settings)` 로 주입하고,
자기 `__main__.py` 에서 `run(settings=..., strategy=...)` 를 호출한다.

core 는 특정 봇 구현에 의존하지 않음.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from holdem_core.core.config import Settings, load_settings
from holdem_core.core.logging import get_logger, reattach_decision_loggers
from holdem_core.routers import bot as bot_router
from holdem_core.routers import health
from holdem_core.strategy.base import Strategy
from holdem_core.ws.runner import BotRunner

logger = get_logger(__name__)


def _deploy_bot(cfg: Settings) -> None:
    """봇을 대시보드에 deploy. WS 인증만으로 방 배정 안 됨 (BOT_REFERENCE §2.2).

    DASHBOARD_URL/BOT_ID 미설정이면 ERROR 로 사용자에게 수동 deploy 안내.
    네트워크 실패는 WARN — WS 연결은 일단 시도하고 이미 deploy 된 상태일 수 있음.
    """
    if not cfg.AUTO_DEPLOY:
        logger.info("auto_deploy_disabled")
        return
    if not cfg.DASHBOARD_URL or not cfg.BOT_ID:
        logger.error(
            "auto_deploy_skipped_missing_config",
            extra={
                "hint": (
                    "WS 인증만으로는 방에 배정되지 않습니다. 둘 중 하나를 하세요: "
                    "(a) 대시보드에서 봇을 수동으로 deploy 클릭, "
                    "(b) .env 에 DASHBOARD_URL + BOT_ID 설정해서 부팅 시 auto-deploy."
                ),
            },
        )
        return
    url = cfg.DASHBOARD_URL.rstrip("/") + f"/bots/{cfg.BOT_ID}/deploy"
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg.BOT_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
        logger.info("auto_deploy_ok", extra={"status": status, "bot_id": cfg.BOT_ID})
    except urllib.error.HTTPError as e:
        logger.warning(
            "auto_deploy_http_error",
            extra={"status": e.code, "url": url, "reason": e.reason},
        )
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning("auto_deploy_network_error", extra={"url": url, "error": str(e)})


async def _start_viz(cfg: Settings) -> asyncio.subprocess.Process | None:
    if not cfg.VIZ_ENABLED or not cfg.VIZ_DASHBOARD_PATH:
        return None
    dashboard_path = Path(cfg.VIZ_DASHBOARD_PATH)
    if not dashboard_path.exists():
        logger.warning(
            "viz_dashboard_missing",
            extra={"path": str(dashboard_path)},
        )
        return None
    try:
        env = {
            **os.environ,
            "DECISION_LOG_PATH": cfg.DECISION_LOG_PATH,
            "DEBUG_DIR": cfg.DEBUG_DIR,
        }
        proc = await asyncio.create_subprocess_exec(
            "streamlit",
            "run",
            str(dashboard_path),
            "--server.port",
            str(cfg.VIZ_PORT),
            "--server.headless",
            "true",
            env=env,
        )
        logger.info("viz_started", extra={"pid": proc.pid, "port": cfg.VIZ_PORT})
        return proc
    except Exception as exc:  # noqa: BLE001
        logger.warning("viz_start_failed", extra={"error": str(exc)})
        return None


async def _stop_viz(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except TimeoutError:
            proc.kill()
            await proc.wait()
        logger.info("viz_stopped", extra={"pid": proc.pid, "returncode": proc.returncode})
    except Exception as exc:  # noqa: BLE001
        logger.warning("viz_stop_failed", extra={"error": str(exc)})


def create_app(strategy: Strategy, settings: Settings) -> FastAPI:
    """봇 Strategy + Settings 로 FastAPI 앱 생성."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runner = BotRunner(settings, strategy)
        app.state.bot_runner = runner
        viz_proc = await _start_viz(settings)
        app.state.viz_proc = viz_proc
        await runner.start()
        try:
            yield
        finally:
            await runner.stop()
            await _stop_viz(viz_proc)

    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)
    app.include_router(health.router, prefix=settings.API_PREFIX)
    app.include_router(bot_router.router, prefix=settings.API_PREFIX)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"app": settings.APP_NAME}

    return app


def parse_runner_args(argv: list[str] | None = None) -> argparse.Namespace:
    """공용 CLI 파서. 각 봇 `__main__.py` 에서 사용."""
    parser = argparse.ArgumentParser(prog="holdem-bot")
    parser.add_argument(
        "--env-file",
        default=None,
        help="봇 패키지의 .env 경로. 없으면 HOLDEM_ENV_FILE 환경변수.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG_EVENTS: dump WS events to .debug/room_*.jsonl",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args(argv)


def run(
    *,
    strategy_factory,
    default_env_file: str | Path | None = None,
    argv: list[str] | None = None,
) -> None:
    """봇 실행 진입점.

    `strategy_factory(settings)` 가 Strategy 인스턴스를 반환해야 함.
    `default_env_file` 은 봇 패키지 root 의 .env. CLI `--env-file` 이 더 우선.
    """
    import uvicorn

    args = parse_runner_args(argv)

    # DEBUG_EVENTS 는 .env 로딩 전에 env var 로 세팅 (pydantic-settings 는 env > env_file).
    os.environ["DEBUG_EVENTS"] = "true" if args.debug else "false"

    env_file = args.env_file or default_env_file
    settings = load_settings(env_file)
    # 봇 전용 .env 의 DECISION_LOG_PATH 로 logger 재연결 (strategy import 타이밍에
    # 기본값으로 붙은 핸들러를 제거하고 봇별 경로로 교체).
    reattach_decision_loggers(settings)
    # v5.4: WS 연결 전에 dashboard 에 deploy. 미설정/실패 시 안내 로그 후 계속.
    _deploy_bot(settings)
    port = args.port if args.port is not None else settings.PORT
    strategy = strategy_factory(settings)
    app = create_app(strategy, settings)
    uvicorn.run(app, host=args.host, port=port, reload=False)
    # reload 모드는 팩토리 패턴과 호환 안 되어 당분간 비활성
