"""핸드 평가 — 홀카드 + 커뮤니티 카드 강도 계산

v2: 드로우 감지, 탑페어/미들페어 구분, 포지션별 implied odds
"""

from collections import Counter
from itertools import combinations

RANK_ORDER = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANK_ORDER)}


def card_rank(card: str) -> int:
    return RANK_VALUE[card[0]]


def card_suit(card: str) -> str:
    return card[1]


# ═══════════════════════════════════════════════════
# 5장 핸드 평가
# ═══════════════════════════════════════════════════

def evaluate_hand(cards: list[str]) -> tuple[int, list[int]]:
    """5장 카드 핸드 평가. (hand_rank, tiebreakers). 낮을수록 강함."""
    ranks = sorted([card_rank(c) for c in cards], reverse=True)
    suits = [card_suit(c) for c in cards]

    is_flush = len(set(suits)) == 1

    is_straight = False
    straight_high = 0
    if len(set(ranks)) == 5:
        if ranks[0] - ranks[4] == 4:
            is_straight = True
            straight_high = ranks[0]
        elif ranks == [12, 3, 2, 1, 0]:
            is_straight = True
            straight_high = 3

    rank_counts = Counter(ranks)
    counts = sorted(rank_counts.values(), reverse=True)
    sorted_by_count = sorted(rank_counts.keys(), key=lambda r: (rank_counts[r], r), reverse=True)

    if is_straight and is_flush:
        if straight_high == 12:
            return (1, [straight_high])
        return (2, [straight_high])
    if counts == [4, 1]:
        return (3, sorted_by_count)
    if counts == [3, 2]:
        return (4, sorted_by_count)
    if is_flush:
        return (5, ranks)
    if is_straight:
        return (6, [straight_high])
    if counts == [3, 1, 1]:
        return (7, sorted_by_count)
    if counts == [2, 2, 1]:
        return (8, sorted_by_count)
    if counts == [2, 1, 1, 1]:
        return (9, sorted_by_count)
    return (10, ranks)


def best_hand(hole: list[str], community: list[str]) -> tuple[int, list[int]]:
    """홀카드 2장 + 커뮤니티에서 가능한 최강 5장 조합 평가"""
    all_cards = hole + community
    if len(all_cards) < 5:
        return _preflop_strength(hole)
    best = (99, [])
    for combo in combinations(all_cards, 5):
        result = evaluate_hand(list(combo))
        if result < best:
            best = result
    return best


def _preflop_strength(hole: list[str]) -> tuple[int, list[int]]:
    r1, r2 = card_rank(hole[0]), card_rank(hole[1])
    high, low = max(r1, r2), min(r1, r2)
    paired = r1 == r2
    suited = card_suit(hole[0]) == card_suit(hole[1])
    if paired:
        return (9, [high, high])
    if suited and high - low <= 4:
        return (10, [high, low])
    return (10, [high, low])


# ═══════════════════════════════════════════════════
# 드로우 감지
# ═══════════════════════════════════════════════════

def detect_draws(hole: list[str], community: list[str]) -> dict:
    """드로우 상태 감지.

    Returns:
        {
            "flush_draw": bool,      # 4장 같은 수트 (1장 더 필요)
            "flush_draw_nut": bool,   # 홀카드에 해당 수트 최고 카드
            "oesd": bool,             # Open-Ended Straight Draw (양방향)
            "gutshot": bool,          # Gutshot (1장 특정 카드 필요)
            "combo_draw": bool,       # 플러시 + 스트레이트 드로우 동시
            "overcards": int,         # 보드보다 높은 홀카드 수 (0-2)
            "top_pair": bool,         # 탑페어 (홀카드가 보드 최고 카드와 페어)
            "overpair": bool,         # 오버페어 (포켓페어 > 보드 최고)
        }
    """
    if not community:
        return {"flush_draw": False, "flush_draw_nut": False, "oesd": False,
                "gutshot": False, "combo_draw": False, "overcards": 0,
                "top_pair": False, "overpair": False}

    all_cards = hole + community
    all_ranks = [card_rank(c) for c in all_cards]
    all_suits = [card_suit(c) for c in all_cards]
    hole_ranks = [card_rank(c) for c in hole]
    hole_suits = [card_suit(c) for c in hole]
    board_ranks = sorted([card_rank(c) for c in community], reverse=True)

    # ── 플러시 드로우 ──
    suit_counts = Counter(all_suits)
    flush_draw = False
    flush_draw_nut = False
    flush_suit = None
    for suit, count in suit_counts.items():
        if count == 4:
            flush_draw = True
            flush_suit = suit
            # 홀카드 중 해당 수트의 카드가 가장 높은지
            suited_cards = [card_rank(c) for c in all_cards if card_suit(c) == suit]
            hole_suited = [card_rank(c) for c in hole if card_suit(c) == suit]
            if hole_suited and max(hole_suited) == max(suited_cards):
                flush_draw_nut = True

    # ── 스트레이트 드로우 ──
    unique_ranks = sorted(set(all_ranks))
    oesd = False
    gutshot = False

    # 연속 4장 체크 (OESD)
    for i in range(len(unique_ranks) - 3):
        window = unique_ranks[i:i + 4]
        if window[-1] - window[0] == 3:
            # 양쪽 열림 확인
            low_open = window[0] > 0  # 2 이상이면 아래쪽 열림
            high_open = window[-1] < 12  # A 미만이면 위쪽 열림
            if low_open and high_open:
                # 홀카드가 이 드로우에 기여하는지
                if any(r in window for r in hole_ranks):
                    oesd = True

    # 거셧 체크 (5장 범위에 1장 빈 곳)
    if not oesd:
        for start in range(max(0, min(unique_ranks) - 1), min(9, max(unique_ranks) + 1)):
            needed = set(range(start, start + 5))
            have = needed & set(unique_ranks)
            if len(have) == 4 and any(r in needed for r in hole_ranks):
                gutshot = True
                break
        # A-2-3-4-5 거셧
        wheel = {0, 1, 2, 3, 12}
        have_wheel = wheel & set(unique_ranks)
        if len(have_wheel) == 4 and any(r in wheel for r in hole_ranks):
            gutshot = True

    combo_draw = flush_draw and (oesd or gutshot)

    # ── 오버카드 ──
    if board_ranks:
        board_high = board_ranks[0]
        overcards = sum(1 for r in hole_ranks if r > board_high)
    else:
        overcards = 0

    # ── 탑페어 / 오버페어 ──
    top_pair = False
    overpair = False
    if board_ranks:
        board_high = board_ranks[0]
        if any(r == board_high for r in hole_ranks):
            top_pair = True
        if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] > board_high:
            overpair = True

    return {
        "flush_draw": flush_draw,
        "flush_draw_nut": flush_draw_nut,
        "oesd": oesd,
        "gutshot": gutshot,
        "combo_draw": combo_draw,
        "overcards": overcards,
        "top_pair": top_pair,
        "overpair": overpair,
    }


# ═══════════════════════════════════════════════════
# 통합 핸드 강도 점수 (v2)
# ═══════════════════════════════════════════════════

def hand_strength_score(hole: list[str], community: list[str]) -> float:
    """0.0 ~ 1.0 강도 점수 (높을수록 강함)

    v2: 메이드 핸드 + 드로우 equity + 탑페어 보정
    """
    hand_rank, tiebreakers = best_hand(hole, community)

    # ── 기본 점수 (메이드 핸드) ──
    # 더 세밀한 구간 배정
    made_scores = {
        1: 1.00,   # Royal Flush
        2: 0.97,   # Straight Flush
        3: 0.93,   # Four of a Kind
        4: 0.88,   # Full House
        5: 0.82,   # Flush
        6: 0.78,   # Straight
        7: 0.70,   # Three of a Kind
        8: 0.55,   # Two Pair
        9: 0.38,   # One Pair
        10: 0.15,  # High Card
    }
    base = made_scores.get(hand_rank, 0.1)

    # ── 같은 핸드 등급 내 세분화 ──
    if tiebreakers:
        # 키커 보정 (0 ~ 0.08 범위)
        tb_bonus = tiebreakers[0] / 12.0 * 0.08
        base += tb_bonus

    # ── 프리플롭이면 여기서 반환 ──
    if not community:
        return min(base, 1.0)

    # ── 드로우 보정 ──
    draws = detect_draws(hole, community)
    draw_bonus = 0.0

    cards_to_come = max(0, 5 - len(community))  # 남은 카드 수

    if cards_to_come > 0:
        if draws["combo_draw"]:
            # 콤보 드로우 (플러시 + 스트레이트) — 약 45-55% equity
            draw_bonus = 0.30 if cards_to_come == 2 else 0.18
        elif draws["flush_draw"]:
            # 플러시 드로우 — 약 35% (2장 남음) / 19% (1장 남음)
            draw_bonus = 0.22 if cards_to_come == 2 else 0.12
            if draws["flush_draw_nut"]:
                draw_bonus += 0.05  # 넛 플러시 드로우 보너스
        elif draws["oesd"]:
            # OESD — 약 31% (2장) / 17% (1장)
            draw_bonus = 0.18 if cards_to_come == 2 else 0.10
        elif draws["gutshot"]:
            # 거셧 — 약 17% (2장) / 8% (1장)
            draw_bonus = 0.10 if cards_to_come == 2 else 0.05

        # 오버카드 보너스 (아직 페어 안 됐을 때)
        if hand_rank == 10 and draws["overcards"] >= 1:
            draw_bonus += draws["overcards"] * 0.04

    # ── 탑페어/오버페어 보정 ──
    if hand_rank == 9:  # 원페어
        if draws["overpair"]:
            base += 0.12  # 오버페어 → 투페어급
        elif draws["top_pair"]:
            # 탑페어 키커 보정
            hole_ranks = sorted([card_rank(c) for c in hole], reverse=True)
            kicker = hole_ranks[0] if hole_ranks[0] != card_rank(community[0]) else hole_ranks[1] if len(hole_ranks) > 1 else 0
            base += 0.05 + kicker / 12.0 * 0.05  # 탑페어 + 키커 보정
        # 미들/바텀 페어는 base 그대로

    # 드로우 보너스는 메이드 핸드가 약할 때만 의미있음
    # 이미 강한 핸드(투페어+)는 드로우 보너스 불필요
    if hand_rank >= 9:
        base += draw_bonus

    return min(base, 1.0)


# ═══════════════════════════════════════════════════
# 프리플롭 티어
# ═══════════════════════════════════════════════════

def preflop_tier(hole: list[str]) -> int:
    """프리플롭 핸드 티어 (1=최강 ~ 8=최약)"""
    r1, r2 = card_rank(hole[0]), card_rank(hole[1])
    high, low = max(r1, r2), min(r1, r2)
    paired = r1 == r2
    suited = card_suit(hole[0]) == card_suit(hole[1])
    gap = high - low

    if paired and high >= 10:  # JJ+
        return 1
    if paired and high >= 8:   # 99, TT
        return 2
    if high == 12 and low >= 10:  # AJ+
        return 1 if suited else 2
    if high == 12 and low >= 8:   # AT, A9
        return 3 if suited else 4
    if suited and gap <= 2 and high >= 7:
        return 3
    if paired and high >= 4:
        return 4
    if high == 12 and suited:
        return 4
    if high >= 8 and low >= 8:
        return 4 if suited else 5
    if suited and gap <= 2:
        return 5
    if high == 12:
        return 5
    if suited and gap <= 3:
        return 6
    if paired:
        return 5
    if gap <= 2 and high >= 5:
        return 6
    if high == 11:
        return 6
    if suited:
        return 7
    return 8
