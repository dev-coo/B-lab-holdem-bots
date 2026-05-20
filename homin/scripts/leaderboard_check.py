"""시즌 리더보드 즉석 조회 — 자가 모니터링 도구.

사용:
  uv run python scripts/leaderboard_check.py            # 현재 open 시즌 + 우리 봇
  uv run python scripts/leaderboard_check.py --all      # top-N 모두
  uv run python scripts/leaderboard_check.py --season 4

`.env` 의 `HOLDEM_SESSION_COOKIE`, `HOLDEM_RESULTS_BASE_URL`, `HOLDEM_BOT_NAME` 사용.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

# .env 로드 (load_bot_config 호출 없이 _env.load_dotenv 만 사용 — bot config 검증 회피).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from holdem._env import load_dotenv  # noqa: E402
from holdem.transport.leaderboard_client import (  # noqa: E402
    LeaderboardClientError,
    current_season,
    fetch_leaderboard,
    fetch_seasons,
)


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()
    base_url = os.environ.get("HOLDEM_RESULTS_BASE_URL", "http://59.28.196.50:5051")
    cookie = os.environ.get("HOLDEM_SESSION_COOKIE")
    bot_name = os.environ.get("HOLDEM_BOT_NAME", "")
    if not cookie:
        print("ERROR: HOLDEM_SESSION_COOKIE 미설정 (.env 확인)", file=sys.stderr)
        return 2

    async with httpx.AsyncClient() as client:
        try:
            seasons = await fetch_seasons(client, base_url, cookie)
        except LeaderboardClientError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3

        if args.season is not None:
            target = next((s for s in seasons if s.id == args.season), None)
            if target is None:
                print(f"season_id={args.season} 없음", file=sys.stderr)
                return 4
        else:
            target = current_season(seasons)
            if target is None:
                print("현재 open 시즌 없음 — 모두 closed", file=sys.stderr)
                return 5

        try:
            board = await fetch_leaderboard(client, base_url, cookie, target.id)
        except LeaderboardClientError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3

    print(f"시즌: {target.id} ({target.name}, {target.status}, {target.created_at})")
    if not board:
        print("  (리더보드 비어있음)")
        return 0

    if args.all:
        rows = board
    else:
        rows = [e for e in board if e.player_name == bot_name]
        if not rows:
            print(f"  {bot_name!r} 미참여 — 전체 리더보드:")
            rows = board

    for e in rows:
        wr = (e.wins / e.games_played * 100) if e.games_played else 0.0
        print(
            f"  rank={e.rank:>2}  {e.player_name:<22} {e.player_type:<6} "
            f"score={e.total_score:>+6}  games={e.games_played:>5}  "
            f"wins={e.wins:>4} ({wr:.1f}%)"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="시즌 리더보드 조회 (자가 모니터링)")
    ap.add_argument("--season", type=int, default=None, help="조회할 season_id (생략 시 open)")
    ap.add_argument("--all", action="store_true", help="우리 봇 외 전체 출력")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
