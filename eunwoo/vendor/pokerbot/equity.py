"""Monte Carlo Equity 계산 — 실제 승률 추정

내 홀카드 + 커뮤니티 카드가 주어졌을 때,
랜덤 상대 핸드 N개를 시뮬레이션하여 승률을 추정한다.

성능: 1000 시뮬레이션 ≈ 5~15ms (30초 타임아웃 대비 충분)
"""

import random as _random
from itertools import combinations
from collections import Counter

RANK_ORDER = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANK_ORDER)}
SUITS = "shdc"
FULL_DECK = [f"{r}{s}" for r in RANK_ORDER for s in SUITS]


def _eval5(cards: list[str]) -> tuple:
    """5장 핸드 평가 (인라인 최적화)"""
    ranks = sorted([RANK_VALUE[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = suits[0] == suits[1] == suits[2] == suits[3] == suits[4]

    unique = set(ranks)
    straight = False
    high = 0
    if len(unique) == 5:
        if ranks[0] - ranks[4] == 4:
            straight = True
            high = ranks[0]
        elif unique == {12, 3, 2, 1, 0}:
            straight = True
            high = 3

    cnt = Counter(ranks)
    counts = sorted(cnt.values(), reverse=True)
    by_count = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)

    if straight and flush:
        return (8, high)
    if counts[0] == 4:
        return (7, by_count[0], by_count[1])
    if counts[0] == 3 and counts[1] == 2:
        return (6, by_count[0], by_count[1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, high)
    if counts[0] == 3:
        return (3, by_count[0], by_count[1], by_count[2])
    if counts[0] == 2 and counts[1] == 2:
        return (2, by_count[0], by_count[1], by_count[2])
    if counts[0] == 2:
        return (1, *by_count)
    return (0, *ranks)


def _best5(cards: list[str]) -> tuple:
    """7장 이하에서 최강 5장 조합"""
    if len(cards) < 5:
        return (0, 0)
    best = None
    for combo in combinations(cards, 5):
        score = _eval5(list(combo))
        if best is None or score > best:
            best = score
    return best


def calc_equity(hole: list[str], community: list[str],
                num_opponents: int = 1, simulations: int = 1000) -> float:
    """Monte Carlo equity 계산.

    Args:
        hole: 내 홀카드 2장
        community: 현재 커뮤니티 카드 (0~5장)
        num_opponents: 상대 수 (기본 1, 헤즈업)
        simulations: 시뮬레이션 횟수

    Returns:
        0.0 ~ 1.0 승률 (무승부는 0.5로 계산)
    """
    known = set(hole + community)
    remaining = [c for c in FULL_DECK if c not in known]
    cards_to_deal = 5 - len(community)  # 남은 커뮤니티 카드 수
    total_need = cards_to_deal + num_opponents * 2  # 커뮤니티 + 상대 홀카드

    wins = 0.0
    rng = _random.Random()  # 별도 인스턴스 (thread-safe)

    for _ in range(simulations):
        # 남은 카드에서 랜덤 샘플
        sampled = rng.sample(remaining, total_need)

        # 커뮤니티 완성
        full_community = community + sampled[:cards_to_deal]

        # 내 핸드 평가
        my_score = _best5(hole + full_community)

        # 상대 핸드 평가
        beaten_all = True
        tied = False
        idx = cards_to_deal
        for _ in range(num_opponents):
            opp_hole = sampled[idx:idx + 2]
            idx += 2
            opp_score = _best5(opp_hole + full_community)
            if opp_score > my_score:
                beaten_all = False
                break
            elif opp_score == my_score:
                tied = True

        if beaten_all:
            wins += 0.5 if tied else 1.0

    return wins / simulations


def calc_equity_vs_range(hole: list[str], community: list[str],
                         opp_range: list[list[str]] = None,
                         simulations: int = 800) -> float:
    """특정 상대 레인지 대비 equity.

    opp_range가 None이면 랜덤 레인지 (calc_equity와 동일).
    opp_range가 제공되면 해당 레인지에서만 샘플링.
    """
    if opp_range is None:
        return calc_equity(hole, community, simulations=simulations)

    known = set(hole + community)
    valid_range = [h for h in opp_range if h[0] not in known and h[1] not in known]
    if not valid_range:
        return calc_equity(hole, community, simulations=simulations)

    remaining_base = [c for c in FULL_DECK if c not in known]
    cards_to_deal = 5 - len(community)
    wins = 0.0
    rng = _random.Random()

    for _ in range(simulations):
        opp_hole = rng.choice(valid_range)
        remaining = [c for c in remaining_base if c not in opp_hole]
        if len(remaining) < cards_to_deal:
            continue

        sampled = rng.sample(remaining, cards_to_deal)
        full_community = community + sampled

        my_score = _best5(hole + full_community)
        opp_score = _best5(list(opp_hole) + full_community)

        if my_score > opp_score:
            wins += 1.0
        elif my_score == opp_score:
            wins += 0.5

    return wins / simulations


# ── 프리플롭 equity 룩업 (빠른 조회) ──

def preflop_equity_estimate(hole: list[str], num_opponents: int = 1) -> float:
    """프리플롭 equity 빠른 추정 (시뮬레이션 500회)"""
    return calc_equity(hole, [], num_opponents=num_opponents, simulations=500)
