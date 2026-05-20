"""CLI 엔트리포인트 — Week 2 D1 (Push/Fold 봇).

사용:
  uv run python -m holdem.cli
  uv run python -m holdem.cli --url ws://... --token ... --name bot-x

환경변수 (CLI 미지정 시):
  HOLDEM_WS_URL, HOLDEM_API_TOKEN, HOLDEM_BOT_NAME
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
from pathlib import Path

from .decide.mode_selector import select_mode
from .decide.policy import build_default_deps, decide_async
from .decide.stage import identify_stage
from .math.m_ratio import compute_m
from .meta.budget import BudgetTracker
from .meta.llm_client import LLMClient
from .meta.llm_coordinator import Coordinator
from .persist.db import connect as db_connect, load_store, save_store
from .persist.event_log import EventLogger
from .state.game_state import GameState
from .state.profile_store import ProfileStore
from .transport import protocol as p
from .transport.config import load_bot_config
from .transport.leaderboard_client import (
    LeaderboardClientError,
    fetch_my_rank,
)
from .transport.ws_client import BotConfig, WsClient

log = logging.getLogger(__name__)

# P-Live: ActionRequest 가 N초 동안 안 오면 idle 로 판단해 강제 reconnect.
# server-side dispatch 풀림 (예: dashboard deploy 해제) 후 봇이 묵묵히 idle 인 경우 자동 복구.
LIVENESS_IDLE_THRESHOLD_S = 300.0
LIVENESS_CHECK_INTERVAL_S = 60.0
LEADERBOARD_INTERVAL_S = 300.0   # 5 분 polling — 의사결정 영향 0, 자가 모니터링 전용


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="holdem", description="Holdem bot (Week 2 D1)")
    parser.add_argument("--url", help="WS endpoint, e.g. ws://snn.it.kr:5051/ws")
    parser.add_argument("--token", help="API token (봇 등록 시 발급)")
    parser.add_argument("--name", help="봇 이름 (등록명)")
    parser.add_argument("--log-level", default=os.environ.get("HOLDEM_LOG_LEVEL", "INFO"))
    parser.add_argument("--log-dir", help="JSONL 로그 디렉토리 (기본 data/logs/games)")
    parser.add_argument("--profile-db", default=os.environ.get("HOLDEM_PROFILE_DB"),
                        help="SQLite profile DB 경로 (생략 시 영속 비활성)")
    parser.add_argument("--use-ev-tree", action="store_true",
                        help="(deprecated) EV tree 가 P1 부터 기본 활성. 회귀하려면 --no-ev-tree.")
    parser.add_argument("--no-ev-tree", action="store_true",
                        help="postflop EV tree 비활성 — pot-odds call/fold 만 (P1 회귀용).")
    parser.add_argument("--use-coordinator", action="store_true",
                        help="postflop 에서 LLM coordinator 호출 활성 (ev-tree 필수)")
    parser.add_argument("--once", action="store_true", help="재접속 루프 비활성 (단일 세션)")
    return parser.parse_args()


def _resolve_config(args: argparse.Namespace) -> BotConfig:
    if args.url and args.token and args.name:
        return BotConfig(ws_url=args.url, api_token=args.token, bot_name=args.name)
    cfg = load_bot_config()
    return BotConfig(
        ws_url=args.url or cfg.ws_url,
        api_token=args.token or cfg.api_token,
        bot_name=args.name or cfg.bot_name,
    )


async def run(
    config: BotConfig,
    log_dir: Path | None,
    once: bool,
    profile_db: Path | None = None,
    use_ev_tree: bool = True,
    use_coordinator: bool = False,
) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows / 비메인 스레드

    state = GameState(config.bot_name)
    db_conn = None
    if profile_db is not None:
        db_conn = db_connect(profile_db)
        profile_store = load_store(db_conn)
        log.info("profile DB loaded: %d profiles from %s", len(profile_store.profiles), profile_db)
    else:
        profile_store = ProfileStore()
    deps = build_default_deps()
    deps.profile_store = profile_store
    deps.use_ev_tree_postflop = use_ev_tree
    deps.game_state = state   # P5-2: stage 분류 시 starting_table_size 추출용

    coordinator: Coordinator | None = None
    if use_coordinator:
        if not use_ev_tree:
            log.warning("--use-coordinator requires EV tree (--no-ev-tree 와 충돌); ignoring")
        else:
            coordinator = Coordinator(
                client=LLMClient(),
                budget=BudgetTracker.from_yaml(),
            )

    with EventLogger(base_dir=log_dir) as logger:
        # reconnect_loop 가 매 세션마다 새 WsClient 를 만들기 때문에,
        # 현재 활성 client 는 mutable 컨테이너 [0] 에 담아 handler 가 참조.
        client_ref: list[WsClient | None] = [None]
        # P-Live: 마지막 ActionRequest 도착 시각 (loop.time()). 봇 시작 시 grace period 부여.
        last_action_at: list[float] = [loop.time()]
        force_reconnect = asyncio.Event()

        async def handler(event) -> None:
            logger.log_in(event)
            state.handle(event)
            if isinstance(event, (p.AuthOk, p.ActionRequest)):
                # auth 직후 / 매 ActionRequest 마다 liveness 갱신 — server 가 살아있고
                # dispatch 도 정상이라는 신호.
                last_action_at[0] = loop.time()
            if isinstance(event, p.HandResult):
                profile_store.on_hand_result(event, state)
                if coordinator is not None and coordinator.budget is not None:
                    coordinator.budget.on_hand_end(event.room_id, event.hand_number)
                if db_conn is not None:
                    try:
                        save_store(db_conn, profile_store)
                    except Exception:
                        log.exception("profile DB save failed")
            if isinstance(event, p.SeasonRotated):
                log.info("season_rotated season=%s", event.season_name)
                return
            if isinstance(event, p.GameEnd):
                if coordinator is not None and coordinator.budget is not None:
                    coordinator.budget.on_game_end(event.room_id)
                my = next((r for r in event.rankings if r.name == config.bot_name), None)
                if my is not None:
                    log.info("game_end room=%s my_rank=%d/%d my_chips=%d",
                             event.room_id, my.rank, len(event.rankings), my.chips)
                else:
                    log.info("game_end room=%s ranks=%d (bot not in rankings)",
                             event.room_id, len(event.rankings))
            if isinstance(event, p.ActionRequest):
                action = await decide_async(event, config.bot_name, deps, coordinator=coordinator)
                current = client_ref[0]
                if current is None:
                    log.warning("no active client, dropping action")
                    return
                try:
                    await current.send_action(action)
                    logger.log_out(action)
                    sb = event.blind[0] if len(event.blind) >= 1 else 0
                    bb = event.blind[1] if len(event.blind) >= 2 else 0
                    m = compute_m(event.my_stack, sb, bb)
                    mode = select_mode(m)
                    starting_size = state.starting_table_size(event.room_id)
                    stage = identify_stage(event, original_table_size=starting_size)
                    n_active = sum(
                        1 for pl in event.players
                        if pl.status == "active" and (pl.name or "").strip()
                    )
                    facing = any(
                        e.phase == "preflop" and e.action in ("raise", "allin")
                        for e in event.action_history
                    )
                    log.info(
                        "room=%s hand=%s phase=%s → %s amount=%s | stage=%s m=%.1f mode=%s n_active=%d facing_raise=%s",
                        event.room_id, event.hand_number, event.phase,
                        action.action, action.amount,
                        stage.value, m, mode, n_active, facing,
                    )
                except Exception:
                    log.exception("failed to send action")

        if once:
            client = WsClient(config, handler)
            client_ref[0] = client
            await client.run()
            return

        async def session_loop() -> None:
            delay = 1.0
            while not stop.is_set():
                client = WsClient(config, handler)
                client_ref[0] = client
                force_reconnect.clear()
                try:
                    await client.run()
                    if force_reconnect.is_set():
                        log.info("liveness: forced reconnect after idle close")
                        delay = 1.0
                        client_ref[0] = None
                        continue
                    return  # server_shutdown 정상 종료
                except Exception as e:
                    log.warning("session ended: %s — retry in %.1fs", e, delay)
                client_ref[0] = None
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 30.0)

        async def liveness_watchdog() -> None:
            """LIVENESS_IDLE_THRESHOLD_S 초 동안 ActionRequest 0 이면 ws close → reconnect."""
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=LIVENESS_CHECK_INTERVAL_S)
                    return
                except asyncio.TimeoutError:
                    pass
                idle = loop.time() - last_action_at[0]
                if idle <= LIVENESS_IDLE_THRESHOLD_S:
                    continue
                current = client_ref[0]
                if current is None or current._ws is None:
                    continue
                log.warning("liveness: %.0fs idle — forcing reconnect", idle)
                force_reconnect.set()
                with contextlib.suppress(Exception):
                    await current._ws.close(code=1011, reason="liveness timeout")
                last_action_at[0] = loop.time()   # 재발동 방지 (grace 한 cycle)

        async def leaderboard_logger() -> None:
            """현재 시즌 우리 봇 rank/score 를 5분마다 1줄 log. 실패해도 silent skip.

            의사결정 코드 무영향 (별도 task). HOLDEM_SESSION_COOKIE 미설정 시 즉시 종료.
            """
            cookie = os.environ.get("HOLDEM_SESSION_COOKIE")
            if not cookie:
                return
            base_url = os.environ.get("HOLDEM_RESULTS_BASE_URL", "http://59.28.196.50:5051")
            # httpx 는 lazy import (의존성 강결합 회피).
            try:
                import httpx  # type: ignore[import-not-found]
            except ImportError:
                log.debug("httpx 미설치 — leaderboard polling 비활성")
                return
            warned_once = False
            async with httpx.AsyncClient() as http:
                while not stop.is_set():
                    try:
                        season, me, total = await fetch_my_rank(
                            http, base_url, cookie, config.bot_name,
                        )
                    except LeaderboardClientError as e:
                        if not warned_once:
                            log.warning("leaderboard: %s (이후 동일 에러 suppress)", e)
                            warned_once = True
                    except Exception:
                        log.debug("leaderboard polling 예외", exc_info=True)
                    else:
                        warned_once = False
                        if season is None:
                            log.info("leaderboard: open 시즌 없음")
                        elif me is None:
                            log.info(
                                "leaderboard season=%d (%s) — %r 미참여 (total=%d)",
                                season.id, season.name, config.bot_name, total,
                            )
                        else:
                            wr = (me.wins / me.games_played * 100) if me.games_played else 0.0
                            log.info(
                                "leaderboard season=%d rank=%d/%d score=%+d games=%d wins=%d (%.1f%%)",
                                season.id, me.rank, total,
                                me.total_score, me.games_played, me.wins, wr,
                            )
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=LEADERBOARD_INTERVAL_S)
                        return
                    except asyncio.TimeoutError:
                        continue

        watchdog_task = asyncio.create_task(liveness_watchdog())
        leaderboard_task = asyncio.create_task(leaderboard_logger())
        try:
            await session_loop()
        finally:
            watchdog_task.cancel()
            leaderboard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog_task
            with contextlib.suppress(asyncio.CancelledError):
                await leaderboard_task


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    try:
        config = _resolve_config(args)
    except SystemExit as e:
        log.error("config error: %s", e)
        return 2

    log_dir = Path(args.log_dir) if args.log_dir else None
    profile_db = Path(args.profile_db) if args.profile_db else None
    # P1 부터 EV tree 가 기본 활성. 회귀하려면 --no-ev-tree.
    use_ev_tree = not args.no_ev_tree
    try:
        asyncio.run(run(
            config, log_dir, args.once, profile_db,
            use_ev_tree=use_ev_tree,
            use_coordinator=args.use_coordinator,
        ))
    except KeyboardInterrupt:
        log.info("interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
