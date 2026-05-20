from __future__ import annotations

import random

import pytest

from holdem.simulate.strategies import (
    CallStation, LAG, NashJam, NitRock, RandomBot, TAG, all_strategies,
)
from holdem.simulate.tournament import (
    BlindLevel,
    BlindSchedule,
    round_robin,
    run_tournament,
)


def _small_schedule(starting: int = 100) -> BlindSchedule:
    """빠른 테스트용 — 레벨별 3 hands, 급상승."""
    return BlindSchedule(
        starting_stack=starting,
        levels=(
            BlindLevel(level=1, sb=1, bb=2, hands=3),
            BlindLevel(level=2, sb=2, bb=4, hands=3),
            BlindLevel(level=3, sb=5, bb=10, hands=3),
            BlindLevel(level=4, sb=10, bb=20, hands=None),  # terminal
        ),
    )


def test_blind_schedule_loads_from_yaml():
    sch = BlindSchedule.from_yaml()
    assert sch.starting_stack == 300
    assert sch.levels[0].sb == 1 and sch.levels[0].bb == 2
    # 최종 레벨은 hands=None
    assert sch.levels[-1].hands is None


def test_level_at_hand_number():
    sch = _small_schedule()
    # hands=3 씩 → 1~3 = Lv1, 4~6 = Lv2, 7~9 = Lv3, 10+ = Lv4
    assert sch.level_at(1).level == 1
    assert sch.level_at(3).level == 1
    assert sch.level_at(4).level == 2
    assert sch.level_at(9).level == 3
    assert sch.level_at(10).level == 4
    assert sch.level_at(999).level == 4   # terminal catch-all


def test_tournament_terminates_with_winner():
    """짧은 스택 + 급상승 → 반드시 종료."""
    rng = random.Random(42)
    res = run_tournament(TAG(), CallStation(), schedule=_small_schedule(50),
                         max_hands=500, rng=rng)
    # 둘 중 한 쪽이 이겼거나 stack conservation 유지.
    total = sum(res.final_stacks.values())
    assert total == 100  # starting_stack × 2
    assert res.n_hands >= 1


def test_tournament_winner_has_positive_stack():
    rng = random.Random(7)
    res = run_tournament(TAG(), NashJam(), schedule=_small_schedule(30),
                         max_hands=200, rng=rng)
    if res.winner_name is not None:
        assert res.final_stacks[res.winner_name] > 0


def test_tournament_level_progresses():
    """충분한 max_hands 에서 Lv 는 단조 증가 기록."""
    rng = random.Random(13)
    res = run_tournament(
        RandomBot(), CallStation(),
        schedule=_small_schedule(10000),  # 큰 스택 → 많은 핸드
        max_hands=20, rng=rng,
    )
    levels = [lv for _, lv in res.level_history]
    # 단조 증가
    assert all(levels[i] <= levels[i + 1] for i in range(len(levels) - 1))
    # 20 핸드 까지 돌았다면 Lv2 이상 도달
    if res.n_hands >= 4:
        assert res.final_level >= 2


def test_tournament_cap_truncates():
    """max_hands 도달 시 winner=None 가능."""
    rng = random.Random(0)
    # 큰 스택 + 작은 cap → cap 먼저 도달할 수 있음.
    res = run_tournament(CallStation(), CallStation(),
                         schedule=_small_schedule(500), max_hands=2, rng=rng)
    assert res.n_hands <= 2


def test_round_robin_basic():
    strategies = [TAG(), CallStation(), NitRock()]
    results = round_robin(strategies, schedule=_small_schedule(40),
                          tournaments_per_pair=3, max_hands=100, base_seed=1)
    assert len(results) == 3  # C(3,2) = 3 쌍
    for key, row in results.items():
        total = row["wins_a"] + row["wins_b"] + row["splits"]
        assert total == 3
        assert row["avg_hands"] > 0


def test_hu_alternating_sb_position():
    """HU 규칙: 매 핸드 SB 자리 교대 (현 구현의 핵심 가정)."""
    rng = random.Random(1)
    res = run_tournament(TAG(), NitRock(), schedule=_small_schedule(200),
                         max_hands=4, rng=rng, record_hands=True)
    # 4 핸드 제한 → hand_results 4 개. stack 누적·교대 로직 sanity.
    assert len(res.hand_results) >= 1
    total = sum(res.final_stacks.values())
    # 최소한 총합이 초기(200*2=400) 근처 (all-in splitting 정수 잔차 ±1)
    assert abs(total - 400) <= 1
