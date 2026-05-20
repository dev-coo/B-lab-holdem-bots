from __future__ import annotations

import random

import pytest

from holdem.simulate.strategies import (
    CallStation, LAG, NashJam, NitRock, RandomBot, TAG,
)
from holdem.simulate.tournament import (
    BlindLevel,
    BlindSchedule,
    MultiTournamentResult,
    run_tournament_multi,
)


def _fast_schedule(starting: int = 100) -> BlindSchedule:
    return BlindSchedule(
        starting_stack=starting,
        levels=(
            BlindLevel(level=1, sb=1, bb=2, hands=3),
            BlindLevel(level=2, sb=5, bb=10, hands=5),
            BlindLevel(level=3, sb=25, bb=50, hands=None),
        ),
    )


def test_multi_tournament_terminates():
    rng = random.Random(42)
    res = run_tournament_multi(
        [TAG(), CallStation(), NitRock()],
        schedule=_fast_schedule(50),
        max_hands=300, rng=rng,
    )
    assert res.n_hands >= 1
    assert res.n_players == 3
    # chip conservation
    total = sum(res.final_stacks.values())
    assert total == 150


def test_multi_tournament_has_finishing_order():
    rng = random.Random(7)
    res = run_tournament_multi(
        [RandomBot(), NitRock(), TAG(), LAG()],
        schedule=_fast_schedule(40),
        max_hands=400, rng=rng,
    )
    # finishing_order 길이 == 참가자 수
    assert len(res.finishing_order) == 4
    # 중복 없음
    assert len(set(res.finishing_order)) == 4


def test_multi_tournament_winner_has_positive_stack():
    rng = random.Random(13)
    res = run_tournament_multi(
        [TAG(), LAG(), NashJam()],
        schedule=_fast_schedule(30),
        max_hands=500, rng=rng,
    )
    if len(res.finishing_order) >= 1:
        winner = res.finishing_order[0]
        # cap 미도달 + 우승자 있음 → 우승자 스택 > 0
        if res.n_hands < 500:
            assert res.final_stacks[winner] > 0


def test_multi_tournament_level_progresses():
    rng = random.Random(1)
    res = run_tournament_multi(
        [CallStation(), CallStation(), CallStation()],
        schedule=_fast_schedule(1000),
        max_hands=20, rng=rng,
    )
    levels = [lv for _, lv in res.level_history]
    assert all(levels[i] <= levels[i + 1] for i in range(len(levels) - 1))


def test_multi_tournament_duplicate_names_get_suffix():
    """같은 이름 전략이 여러 개면 "#N" suffix 로 구분."""
    rng = random.Random(0)
    res = run_tournament_multi(
        [TAG(), TAG(), CallStation()],
        schedule=_fast_schedule(40),
        max_hands=50, rng=rng,
    )
    keys = set(res.final_stacks.keys())
    # TAG 두 명은 "tag#1", "tag#2" 로 구분
    assert "tag#1" in keys
    assert "tag#2" in keys
    assert "callstation" in keys


def test_multi_tournament_6way_completes():
    rng = random.Random(99)
    res = run_tournament_multi(
        [RandomBot(), NitRock(), TAG(), LAG(), CallStation(), NashJam()],
        schedule=_fast_schedule(200),
        max_hands=1000, rng=rng,
    )
    assert res.n_players == 6
    assert len(res.finishing_order) == 6
    # chip conservation
    assert sum(res.final_stacks.values()) == 1200


def test_multi_tournament_cap_truncates():
    """max_hands 도달 시 finishing_order 는 생존자 포함."""
    rng = random.Random(3)
    res = run_tournament_multi(
        [CallStation(), CallStation(), CallStation(), CallStation()],
        schedule=_fast_schedule(100000),   # 매우 큰 스택 → cap 먼저.
        max_hands=3, rng=rng,
    )
    assert res.n_hands <= 3
    # cap 도달 → 전원 생존 또는 일부만 탈락. finishing_order 는 여전히 4명.
    assert len(res.finishing_order) == 4


def test_multi_tournament_minimum_2_players():
    with pytest.raises(ValueError):
        run_tournament_multi([TAG()], max_hands=10)


def test_chips_at_n_players_records_thresholds_for_6way():
    """6-way 토너먼트가 종료까지 진행되면 alive=4,3,2 시점 스냅샷이 모두 기록."""
    rng = random.Random(42)
    res = run_tournament_multi(
        [RandomBot(), NitRock(), TAG(), LAG(), CallStation(), NashJam()],
        schedule=_fast_schedule(200),
        max_hands=2000, rng=rng,
    )
    # 6-way 시작 → thresholds = {4,3,2} (n=6 보다 작은 것만).
    # 종료까지 갔다면 alive 가 1까지 떨어졌으므로 4,3,2 모두 통과.
    if len(res.finishing_order) == 6 and res.final_stacks:
        for th in (4, 3, 2):
            assert th in res.chips_at_n_players, f"missing snapshot at n={th}"
            snap = res.chips_at_n_players[th]
            # 스냅샷 시점에는 alive 가 정확히 th 이하 (보통 ==th, 동시 탈락 시 더 적을 수도).
            assert len(snap) <= th
            # 스택 합 = 전체 chip 보존 (1200 = 6×200).
            # 단, 탈락자의 chip 은 다른 alive 에게 흡수돼 있어야 함.
            assert sum(snap.values()) == 1200


def test_chips_at_n_players_keys_below_n():
    """3-way 시작 → snapshot 임계치는 n=2 만 (n=4,3 은 시작값 이상이라 제외)."""
    rng = random.Random(7)
    res = run_tournament_multi(
        [TAG(), CallStation(), NitRock()],
        schedule=_fast_schedule(50),
        max_hands=300, rng=rng,
    )
    # n=3 시작 → thresholds = {2}.
    assert 4 not in res.chips_at_n_players
    assert 3 not in res.chips_at_n_players


def test_chips_at_n_players_empty_when_2way():
    """2-way 시작 → thresholds 없음 (alive 가 처음부터 2)."""
    rng = random.Random(11)
    res = run_tournament_multi(
        [TAG(), CallStation()],
        schedule=_fast_schedule(40),
        max_hands=200, rng=rng,
    )
    assert res.chips_at_n_players == {}
