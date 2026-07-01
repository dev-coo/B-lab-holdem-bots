"""7카드 포커 핸드 평가기 (순수 Python).

`ActionRequest`의 홀카드 2장 + 커뮤니티 카드 3~5장을 합쳐
정수 랭크로 변환해 `>` / `==` / `<` 비교가 가능하게 한다.
높을수록 강한 핸드. 외부 의존성 無.

카드 표기: `[2-9TJQKA][shdc]` (BOT_REFERENCE.md §3).
"""

from __future__ import annotations

from collections.abc import Iterable

_RANK_STR = "23456789TJQKA"
_RANK_VAL = {r: i + 2 for i, r in enumerate(_RANK_STR)}  # 2..14

# 카테고리 (클수록 강함)
_HIGH_CARD = 1
_ONE_PAIR = 2
_TWO_PAIR = 3
_TRIPS = 4
_STRAIGHT = 5
_FLUSH = 6
_FULL_HOUSE = 7
_QUADS = 8
_STRAIGHT_FLUSH = 9

CATEGORY_NAMES: dict[int, str] = {
    9: "straight_flush",
    8: "quads",
    7: "full_house",
    6: "flush",
    5: "straight",
    4: "trips",
    3: "two_pair",
    2: "one_pair",
    1: "high_card",
}

CATEGORY_KO: dict[str, str] = {
    "straight_flush": "스트레이트 플러시",
    "quads": "포카드",
    "full_house": "풀하우스",
    "flush": "플러시",
    "straight": "스트레이트",
    "trips": "트립스",
    "two_pair": "투페어",
    "one_pair": "원페어",
    "high_card": "하이카드",
}


def _best_straight_high(uniq_desc: list[int]) -> int:
    """유니크·내림차순 정렬된 랭크 리스트에서 가장 높은 스트레이트의 탑카드를 반환.
    없으면 0.

    주의: 이 서버는 **백스트레이트(A-2-3-4-5)를 스트레이트로 인정하지 않음**.
    A 는 오직 하이(14) 로만 취급 — 휠 검출 로직 없음.
    """
    n = len(uniq_desc)
    for i in range(n - 4):
        if uniq_desc[i] - uniq_desc[i + 4] == 4:
            return uniq_desc[i]
    return 0


def _encode(category: int, tiebreakers: Iterable[int]) -> int:
    """카테고리 + 최대 5개 랭크 타이브레이커를 단일 정수로 인코딩.
    카테고리 간 비교 일관성을 위해 항상 5-슬롯을 쓴다 (부족분은 0 패딩).
    비교는 정수 `>` 로 가능."""
    tb_list = list(tiebreakers)[:5]
    tb_list.extend([0] * (5 - len(tb_list)))
    r = category
    for tb in tb_list:
        r = r * 15 + tb
    return r


def _evaluate(cards: list[str]) -> tuple[int, list[int]]:
    """5~7장에서 최고 5카드 메이드핸드의 (카테고리, 타이브레이커) 반환.

    `rank7` 과 `classify_hand` 가 공유하는 내부 로직.
    """
    ranks = [_RANK_VAL[c[0]] for c in cards]
    suits = [c[1] for c in cards]

    # 슈트별 랭크 모음 (플러시 탐지용)
    by_suit: dict[str, list[int]] = {"s": [], "h": [], "d": [], "c": []}
    for r, s in zip(ranks, suits, strict=True):
        by_suit[s].append(r)

    # 1. 스트레이트 플러시
    flush_suit: str | None = None
    for s, rs in by_suit.items():
        if len(rs) >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        flush_ranks_desc = sorted(by_suit[flush_suit], reverse=True)
        sf_high = _best_straight_high(flush_ranks_desc)
        if sf_high:
            return _STRAIGHT_FLUSH, [sf_high]

    # 랭크 카운트
    rank_count: dict[int, int] = {}
    for r in ranks:
        rank_count[r] = rank_count.get(r, 0) + 1

    by_count = sorted(rank_count.items(), key=lambda x: (-x[1], -x[0]))
    counts = [c for _, c in by_count]

    # 2. 포카드
    if counts[0] == 4:
        quad = by_count[0][0]
        kicker = max(r for r in ranks if r != quad)
        return _QUADS, [quad, kicker]

    # 3. 풀하우스
    if counts[0] == 3 and len(counts) >= 2 and counts[1] >= 2:
        trip = by_count[0][0]
        pair = by_count[1][0]
        return _FULL_HOUSE, [trip, pair]

    # 4. 플러시
    if flush_suit is not None:
        top5 = sorted(by_suit[flush_suit], reverse=True)[:5]
        return _FLUSH, top5

    # 5. 스트레이트
    uniq_desc = sorted(rank_count.keys(), reverse=True)
    straight_high = _best_straight_high(uniq_desc)
    if straight_high:
        return _STRAIGHT, [straight_high]

    # 6. 트립스
    if counts[0] == 3:
        trip = by_count[0][0]
        kickers = sorted((r for r in ranks if r != trip), reverse=True)[:2]
        return _TRIPS, [trip, *kickers]

    # 7. 투페어
    if counts[0] == 2 and len(counts) >= 2 and counts[1] == 2:
        high_pair = by_count[0][0]
        low_pair = by_count[1][0]
        kicker = max(r for r in ranks if r != high_pair and r != low_pair)
        return _TWO_PAIR, [high_pair, low_pair, kicker]

    # 8. 원페어
    if counts[0] == 2:
        pair = by_count[0][0]
        kickers = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return _ONE_PAIR, [pair, *kickers]

    # 9. 하이카드
    top5 = sorted(ranks, reverse=True)[:5]
    return _HIGH_CARD, top5


def rank7(cards: list[str]) -> int:
    """7장(또는 5~7장)의 카드에서 최고 5카드 조합의 정수 랭크를 반환."""
    category, tiebreakers = _evaluate(cards)
    return _encode(category, tiebreakers)


def classify_hand(cards: list[str]) -> dict[str, object]:
    """5~7 카드에서 최고 메이드핸드 카테고리 반환.

    반환: {"category": "two_pair", "category_rank": 3,
           "category_ko": "투페어", "score": <int>}
    """
    category, tiebreakers = _evaluate(cards)
    name = CATEGORY_NAMES[category]
    return {
        "category": name,
        "category_rank": category,
        "category_ko": CATEGORY_KO[name],
        "score": _encode(category, tiebreakers),
    }


def compare(my7: list[str], opp7: list[str]) -> int:
    """1 = 내가 이김, 0 = 타이, -1 = 짐."""
    a = rank7(my7)
    b = rank7(opp7)
    if a > b:
        return 1
    if a == b:
        return 0
    return -1
