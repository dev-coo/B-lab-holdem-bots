"""leaderboard_client — HTTP 모킹 테스트 (pytest-httpx).

자가 모니터링 모듈이라 의사결정 영향은 0이지만, 파싱 / 에러 처리는 회귀 보호.
"""
from __future__ import annotations

import httpx
import pytest

from holdem.transport.leaderboard_client import (
    LeaderboardClientError,
    current_season,
    fetch_leaderboard,
    fetch_my_rank,
    fetch_seasons,
)

BASE = "http://test.example.com"
COOKIE = "test-cookie"


@pytest.mark.asyncio
async def test_fetch_seasons_parses_payload(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/seasons",
        json=[
            {"id": 6, "name": "0501-06", "status": "open",
             "created_at": "2026-05-01 11:23:32", "closed_at": None},
            {"id": 5, "name": "0501-05", "status": "closed",
             "created_at": "2026-05-01 09:01:04", "closed_at": "2026-05-01 11:23:32"},
        ],
    )
    async with httpx.AsyncClient() as c:
        seasons = await fetch_seasons(c, BASE, COOKIE)
    assert len(seasons) == 2
    assert seasons[0].id == 6
    assert seasons[0].status == "open"
    assert seasons[1].closed_at == "2026-05-01 11:23:32"


@pytest.mark.asyncio
async def test_fetch_leaderboard_parses_entries(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/leaderboard?season_id=4",
        json=[
            {"player_name": "너구리쿤", "player_type": "bot", "total_score": 1915,
             "games_played": 1543, "wins": 455, "rank": 1},
            {"player_name": "whoareyou", "player_type": "bot", "total_score": 1191,
             "games_played": 1543, "wins": 222, "rank": 2},
        ],
    )
    async with httpx.AsyncClient() as c:
        board = await fetch_leaderboard(c, BASE, COOKIE, 4)
    assert len(board) == 2
    assert board[1].player_name == "whoareyou"
    assert board[1].rank == 2
    assert board[0].wins == 455


@pytest.mark.asyncio
async def test_fetch_seasons_raises_on_4xx(httpx_mock):
    httpx_mock.add_response(method="GET", url=f"{BASE}/results/seasons", status_code=401)
    async with httpx.AsyncClient() as c:
        with pytest.raises(LeaderboardClientError) as excinfo:
            await fetch_seasons(c, BASE, COOKIE)
    assert "401" in str(excinfo.value)


@pytest.mark.asyncio
async def test_fetch_leaderboard_raises_on_5xx(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE}/results/leaderboard?season_id=99", status_code=500,
    )
    async with httpx.AsyncClient() as c:
        with pytest.raises(LeaderboardClientError):
            await fetch_leaderboard(c, BASE, COOKIE, 99)


def test_current_season_picks_open():
    from holdem.transport.leaderboard_client import Season

    seasons = [
        Season(id=5, name="0501-05", status="closed",
               created_at="2026-05-01 09:01:04", closed_at="2026-05-01 11:23:32"),
        Season(id=6, name="0501-06", status="open",
               created_at="2026-05-01 11:23:32", closed_at=None),
    ]
    s = current_season(seasons)
    assert s is not None and s.id == 6


def test_current_season_returns_none_when_all_closed():
    from holdem.transport.leaderboard_client import Season

    seasons = [
        Season(id=5, name="0501-05", status="closed",
               created_at="2026-05-01 09:01:04", closed_at="2026-05-01 11:23:32"),
    ]
    assert current_season(seasons) is None


@pytest.mark.asyncio
async def test_fetch_my_rank_finds_bot(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/seasons",
        json=[
            {"id": 6, "name": "0501-06", "status": "open",
             "created_at": "2026-05-01 11:23:32", "closed_at": None},
        ],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/leaderboard?season_id=6",
        json=[
            {"player_name": "중랩이1", "player_type": "bot", "total_score": 412,
             "games_played": 176, "wins": 54, "rank": 1},
            {"player_name": "whoareyou", "player_type": "bot", "total_score": 100,
             "games_played": 176, "wins": 30, "rank": 2},
        ],
    )
    async with httpx.AsyncClient() as c:
        season, me, total = await fetch_my_rank(c, BASE, COOKIE, "whoareyou")
    assert season is not None and season.id == 6
    assert me is not None and me.rank == 2 and me.wins == 30
    assert total == 2


@pytest.mark.asyncio
async def test_fetch_my_rank_returns_none_when_bot_not_in_board(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/seasons",
        json=[
            {"id": 6, "name": "0501-06", "status": "open",
             "created_at": "2026-05-01 11:23:32", "closed_at": None},
        ],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/results/leaderboard?season_id=6",
        json=[],
    )
    async with httpx.AsyncClient() as c:
        season, me, total = await fetch_my_rank(c, BASE, COOKIE, "whoareyou")
    assert season is not None
    assert me is None
    assert total == 0
