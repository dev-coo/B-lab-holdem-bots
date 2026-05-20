"""시즌 리더보드 HTTP 클라이언트 (자가 모니터링 전용).

서버 endpoint:
  GET /results/seasons → list[Season]
  GET /results/leaderboard?season_id=N → list[LeaderboardEntry]

쿠키 인증 필요 — `holdem_session=...`. 미설정 시 호출 측에서 skip.

본 모듈은 **의사결정 코드 미사용** — 의도적으로 fully isolated 한 모니터링.
실패는 `LeaderboardClientError` 로 surface 되지만 사용처에서 silent ignore 가능.
"""
from __future__ import annotations

from typing import Optional

import httpx
from pydantic import BaseModel


class Season(BaseModel):
    id: int
    name: str
    status: str   # "open" | "closed"
    created_at: str
    closed_at: Optional[str] = None


class LeaderboardEntry(BaseModel):
    player_name: str
    player_type: str   # "bot" | "human"
    total_score: int
    games_played: int
    wins: int
    rank: int


class LeaderboardClientError(Exception):
    """HTTP / 인증 / 파싱 실패."""


def _auth_cookies(cookie_value: str) -> dict[str, str]:
    return {"holdem_session": cookie_value}


async def fetch_seasons(
    client: httpx.AsyncClient, base_url: str, cookie: str
) -> list[Season]:
    try:
        r = await client.get(
            f"{base_url}/results/seasons",
            cookies=_auth_cookies(cookie),
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise LeaderboardClientError(f"seasons fetch failed: {e}") from e
    if r.status_code != 200:
        raise LeaderboardClientError(f"seasons HTTP {r.status_code}")
    return [Season.model_validate(item) for item in r.json()]


async def fetch_leaderboard(
    client: httpx.AsyncClient, base_url: str, cookie: str, season_id: int
) -> list[LeaderboardEntry]:
    try:
        r = await client.get(
            f"{base_url}/results/leaderboard",
            params={"season_id": season_id},
            cookies=_auth_cookies(cookie),
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise LeaderboardClientError(f"leaderboard fetch failed: {e}") from e
    if r.status_code != 200:
        raise LeaderboardClientError(f"leaderboard HTTP {r.status_code}")
    return [LeaderboardEntry.model_validate(item) for item in r.json()]


def current_season(seasons: list[Season]) -> Optional[Season]:
    """status=='open' 인 시즌. 없으면 None (모두 closed)."""
    for s in seasons:
        if s.status == "open":
            return s
    return None


async def fetch_my_rank(
    client: httpx.AsyncClient,
    base_url: str,
    cookie: str,
    bot_name: str,
) -> tuple[Optional[Season], Optional[LeaderboardEntry], int]:
    """현재 open 시즌에서 bot_name 의 entry 조회.

    Returns:
        (season, entry, total_players) — entry 없으면 entry=None.
    """
    seasons = await fetch_seasons(client, base_url, cookie)
    season = current_season(seasons)
    if season is None:
        return (None, None, 0)
    board = await fetch_leaderboard(client, base_url, cookie, season.id)
    me = next((e for e in board if e.player_name == bot_name), None)
    return (season, me, len(board))
