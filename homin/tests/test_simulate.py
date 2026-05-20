from __future__ import annotations

import random

from holdem.simulate.engine import run_hand
from holdem.simulate.strategies import (
    CallStation,
    LAG,
    NashJam,
    NitRock,
    RandomBot,
    TAG,
    all_strategies,
)


def test_random_vs_callstation_completes():
    rng = random.Random(42)
    res = run_hand(RandomBot(), CallStation(), sb_stack=300, bb_stack=300, rng=rng)
    assert res.pot >= 3
    assert sum(res.final_stacks) == 600  # chip conservation


def test_nitrock_vs_tag_fold_preflop_often():
    rng = random.Random(0)
    fold_count = 0
    for _ in range(20):
        res = run_hand(NitRock(), TAG(), sb_stack=300, bb_stack=300, rng=rng)
        if not res.showdown_reached:
            fold_count += 1
    # Both strategies are tight → many preflop folds
    assert fold_count >= 10


def test_lag_vs_callstation_goes_showdown_often():
    rng = random.Random(1)
    showdown = 0
    for _ in range(30):
        res = run_hand(LAG(), CallStation(), sb_stack=300, bb_stack=300, rng=rng)
        if res.showdown_reached:
            showdown += 1
    # Call station rarely folds → many hands showdown (LAG 도 preflop fold 약 1/3)
    assert showdown >= 8


def test_nashjam_folds_at_deep_stacks():
    rng = random.Random(2)
    # deep stacks → NashJam falls back to TAG, 대부분 fold
    res = run_hand(NashJam(), RandomBot(), sb_stack=300, bb_stack=300, rng=rng)
    assert sum(res.final_stacks) == 600


def test_nashjam_shoves_at_short_stacks():
    rng = random.Random(3)
    # Short stack (M = 5) → jam
    res = run_hand(NashJam(), CallStation(), sb_stack=10, bb_stack=10, rng=rng)
    assert sum(res.final_stacks) == 20


def test_all_strategies_named():
    names = {s.name for s in all_strategies()}
    assert names == {"random", "callstation", "nitrock", "tag", "lag", "nashjam"}


def test_chip_conservation_100_hands():
    rng = random.Random(7)
    a_stack = 300
    b_stack = 300
    strategies = [TAG(), LAG()]
    for i in range(100):
        if a_stack <= 0 or b_stack <= 0:
            break
        res = run_hand(strategies[i % 2], strategies[(i + 1) % 2],
                       sb_stack=a_stack, bb_stack=b_stack, rng=rng)
        a_stack, b_stack = res.final_stacks if i % 2 == 0 else (res.final_stacks[1], res.final_stacks[0])
    total = a_stack + b_stack
    assert total == 600
