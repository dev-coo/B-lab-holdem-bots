"""몬테카를로 에쿼티 계산기. 9인 테이블 기준 (상대 8명)."""
import random
from collections import Counter
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "hdcs"
DECK = [r + s for r in RANKS for s in SUITS]


def _rank(c):
    return RANKS.index(c[0].upper())


def _eval5(cards):
    ranks = sorted((_rank(c) for c in cards), reverse=True)
    suits = [c[1].lower() for c in cards]
    flush = len(set(suits)) == 1
    unique = sorted(set(ranks), reverse=True)
    straight_hi = None
    if len(unique) == 5:
        if unique[0] - unique[4] == 4:
            straight_hi = unique[0]
        elif unique == [12, 3, 2, 1, 0]:
            straight_hi = 3
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda x: (-x[1], -x[0]))
    counts = tuple(c for _, c in groups)
    rks = tuple(r for r, _ in groups)
    if flush and straight_hi is not None:
        return (8, straight_hi)
    if counts[0] == 4:
        return (7, rks[0], rks[1])
    if counts[0] == 3 and counts[1] == 2:
        return (6, rks[0], rks[1])
    if flush:
        return (5,) + tuple(ranks)
    if straight_hi is not None:
        return (4, straight_hi)
    if counts[0] == 3:
        kickers = [r for r in ranks if r != rks[0]][:2]
        return (3, rks[0]) + tuple(kickers)
    if counts[0] == 2 and counts[1] == 2:
        kicker = next(r for r in ranks if r != rks[0] and r != rks[1])
        return (2, rks[0], rks[1], kicker)
    if counts[0] == 2:
        kickers = [r for r in ranks if r != rks[0]][:3]
        return (1, rks[0]) + tuple(kickers)
    return (0,) + tuple(ranks)


def _eval7(cards):
    return max(_eval5(list(c)) for c in combinations(cards, 5))


def equity(hole, community, num_opponents=8, iters=200):
    """내 에쿼티 (0~1). community는 0/3/4/5장."""
    used = {c.lower() for c in hole + community}
    deck = [c for c in DECK if c.lower() not in used]
    need_board = 5 - len(community)
    total = 0.0
    for _ in range(iters):
        random.shuffle(deck)
        idx = 0
        board = community + deck[idx:idx + need_board]
        idx += need_board
        my_best = _eval7(hole + board)
        beaten = False
        ties = 0
        for _ in range(num_opponents):
            opp = deck[idx:idx + 2]
            idx += 2
            opp_best = _eval7(opp + board)
            if opp_best > my_best:
                beaten = True
                break
            if opp_best == my_best:
                ties += 1
        if not beaten:
            total += 1 / (ties + 1)
    return total / iters
