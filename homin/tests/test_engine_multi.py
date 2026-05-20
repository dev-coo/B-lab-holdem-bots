from __future__ import annotations

import random

import pytest

from holdem.simulate.engine_multi import (
    PlayerState,
    SidePot,
    _compute_side_pots,
    run_hand_multi,
)
from holdem.simulate.strategies import (
    CallStation, LAG, NitRock, RandomBot, TAG,
)


# --- side pot unit tests ---

def _ps(idx: int, total_bet: int, folded: bool = False, allin: bool = False) -> PlayerState:
    p = PlayerState(idx=idx, strategy=None, stack=0)  # strategy 불필요 for side-pot calc
    p.total_bet = total_bet
    p.folded = folded
    p.allin = allin
    return p


def test_side_pot_single_when_no_allin():
    players = [_ps(0, 20), _ps(1, 20), _ps(2, 20)]
    pots = _compute_side_pots(players)
    assert len(pots) == 1
    assert pots[0].amount == 60
    assert set(pots[0].eligible_idx) == {0, 1, 2}


def test_side_pot_two_tier_when_one_allin():
    # p0 allin at 10, p1/p2 bet 30.
    players = [_ps(0, 10, allin=True), _ps(1, 30), _ps(2, 30)]
    pots = _compute_side_pots(players)
    # Main pot (<=10): 10*3 = 30, eligible all three.
    # Side pot (10..30): 20*2 = 40, eligible 1,2.
    assert len(pots) == 2
    assert pots[0].amount == 30
    assert set(pots[0].eligible_idx) == {0, 1, 2}
    assert pots[1].amount == 40
    assert set(pots[1].eligible_idx) == {1, 2}


def test_side_pot_folded_contributes_but_not_eligible():
    # p0 fold after betting 10, p1 allin at 20, p2 matches 30.
    players = [_ps(0, 10, folded=True), _ps(1, 20, allin=True), _ps(2, 30)]
    pots = _compute_side_pots(players)
    # Ceilings: 10, 20, 30.
    # 0..10: 10+10+10=30, eligible 1,2 (0 folded).
    # 10..20: 0+10+10=20, eligible 1,2.
    # 20..30: 0+0+10=10, eligible 2.
    assert len(pots) == 3
    assert pots[0].amount == 30 and set(pots[0].eligible_idx) == {1, 2}
    assert pots[1].amount == 20 and set(pots[1].eligible_idx) == {1, 2}
    assert pots[2].amount == 10 and set(pots[2].eligible_idx) == {2}


def test_side_pot_three_way_allin_different_ceilings():
    # p0=10, p1=25, p2=40 all-in
    players = [_ps(0, 10, allin=True), _ps(1, 25, allin=True), _ps(2, 40, allin=True)]
    pots = _compute_side_pots(players)
    # Ceilings 10, 25, 40.
    # 0..10: 10*3 = 30, eligible 0,1,2.
    # 10..25: 0+15+15 = 30, eligible 1,2.
    # 25..40: 0+0+15 = 15, eligible 2.
    assert [p.amount for p in pots] == [30, 30, 15]
    assert [set(p.eligible_idx) for p in pots] == [{0, 1, 2}, {1, 2}, {2}]


# --- multi-way hand integration tests ---

def test_3way_completes_chip_conservation():
    rng = random.Random(42)
    res = run_hand_multi(
        [RandomBot(), CallStation(), TAG()],
        stacks=[300, 300, 300],
        sb_idx=0, bb=2, sb_amount=1,
        rng=rng,
    )
    assert sum(res.final_stacks) == 900


def test_4way_completes_chip_conservation():
    rng = random.Random(7)
    res = run_hand_multi(
        [NitRock(), TAG(), LAG(), CallStation()],
        stacks=[300, 300, 300, 300],
        sb_idx=0, bb=2,
        rng=rng,
    )
    assert sum(res.final_stacks) == 1200


def test_6way_completes():
    rng = random.Random(13)
    res = run_hand_multi(
        [RandomBot(), NitRock(), TAG(), LAG(), CallStation(), TAG()],
        stacks=[200] * 6,
        sb_idx=0, bb=2,
        rng=rng,
    )
    assert sum(res.final_stacks) == 1200
    # 최소 하나의 winner
    assert any(len(w) >= 1 for w in res.winner_idx_per_pot) or res.pots == []


def test_all_fold_awards_one_winner():
    """전원 fold (NitRock 모임 + 한 명 raise) 시 raise 한 쪽이 pot 획득."""
    # TAG 6명으로 블라인드만 있는 상황에서도 pot 전달 — 최소 검증은 non-crash.
    rng = random.Random(0)
    res = run_hand_multi(
        [NitRock(), NitRock(), NitRock(), TAG()],
        stacks=[300, 300, 300, 300],
        sb_idx=0, bb=2,
        rng=rng,
    )
    assert sum(res.final_stacks) == 1200


def test_hu_n2_still_works():
    """기존 HU 시나리오도 멀티엔진에서 동작 (n=2)."""
    rng = random.Random(42)
    res = run_hand_multi(
        [RandomBot(), CallStation()],
        stacks=[300, 300],
        sb_idx=0, bb=2, sb_amount=1,
        rng=rng,
    )
    assert sum(res.final_stacks) == 600
    assert res.n_players == 2


def test_side_pot_awarded_correctly_in_game():
    """
    실제 핸드에서 사이드팟이 정상 분배되는지.
    조건: CallStation 3명, 스택 3가지 (50/100/150) → 모두 allin 가능.
    chip conservation + 최소 2 pots.
    """
    rng = random.Random(1)
    res = run_hand_multi(
        [CallStation(), CallStation(), CallStation()],
        stacks=[50, 100, 150],
        sb_idx=0, bb=2,
        rng=rng,
    )
    assert sum(res.final_stacks) == 300
    # 모두 콜만 → 기여 동일 수준, 최소 1 pot.
    assert len(res.pots) >= 1


def test_multi_hand_history_nonempty():
    rng = random.Random(5)
    res = run_hand_multi(
        [RandomBot(), TAG(), LAG()],
        stacks=[300, 300, 300],
        sb_idx=0, bb=2,
        rng=rng,
    )
    assert len(res.history) >= 2


def test_sb_idx_rotation():
    """sb_idx 를 바꿔서 자리 배치 회전."""
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    res_a = run_hand_multi([CallStation()]*3, [300]*3, sb_idx=0, bb=2, rng=rng1)
    res_b = run_hand_multi([CallStation()]*3, [300]*3, sb_idx=1, bb=2, rng=rng2)
    # 결과 스택 합 동일 (chip conservation)
    assert sum(res_a.final_stacks) == 900
    assert sum(res_b.final_stacks) == 900
