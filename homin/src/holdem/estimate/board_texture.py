"""Board texture heuristics — 보드 카드만으로 wetness/paired/monotone 등 산출.

근거: plan H.5. 상대 모델 없이도 CBET 빈도·barrel 빈도의 기준값 제공.

입력: community cards, 예 ["Jh", "9h", "8h"]. 3/4/5 장.
출력: BoardTexture dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass

_RANKS = "23456789TJQKA"
_RANK_VALUE = {r: i + 2 for i, r in enumerate(_RANKS)}


def _parse(card: str) -> tuple[int, str]:
    rank_char = card[0].upper()
    suit_char = card[1].lower()
    return _RANK_VALUE[rank_char], suit_char


@dataclass(frozen=True)
class BoardTexture:
    n_cards: int
    paired: bool
    trips_on_board: bool
    monotone: bool            # 3+ same suit
    two_tone: bool            # flush draw possible (exactly 2 of same suit max)
    rainbow: bool             # all different suits
    connectedness: float      # 0 (gaps >= 5) .. 1 (connected)
    wetness: float            # 0 (dry) .. 1 (wet)
    high_card: str            # "A" / "K" / ...
    low_card: str
    range_advantage_hint: float  # -1 (caller favor) .. +1 (PFR favor)


def analyze(community: list[str]) -> BoardTexture:
    if not community or len(community) < 3:
        raise ValueError(f"need ≥ 3 cards, got {community!r}")
    if len(community) > 5:
        raise ValueError(f"max 5 cards, got {len(community)}")

    parsed = [_parse(c) for c in community]
    ranks = sorted((r for r, _ in parsed), reverse=True)
    suits = [s for _, s in parsed]

    # pair / trips
    n_by_rank: dict[int, int] = {}
    for r in ranks:
        n_by_rank[r] = n_by_rank.get(r, 0) + 1
    paired = any(v >= 2 for v in n_by_rank.values())
    trips = any(v >= 3 for v in n_by_rank.values())

    # flush / monotone
    suit_counts: dict[str, int] = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
    max_suit = max(suit_counts.values())
    monotone = max_suit >= 3
    rainbow = max_suit == 1 and len(suits) >= 3
    two_tone = max_suit == 2

    # connectedness — rank 간 gap 의 tightness.
    distinct_ranks = sorted(set(ranks), reverse=True)
    if len(distinct_ranks) >= 2:
        spans = [distinct_ranks[i] - distinct_ranks[i + 1] for i in range(len(distinct_ranks) - 1)]
        avg_gap = sum(spans) / len(spans)
        # gap 0..1 → 매우 연결, gap >= 4 → 거의 단절
        connectedness = max(0.0, min(1.0, 1.0 - (avg_gap - 1.0) / 4.0))
    else:
        connectedness = 0.0

    # wetness = connectedness × 0.5 + flushdraw 요소 × 0.5
    flush_factor = 1.0 if monotone else (0.6 if two_tone else 0.0)
    wetness = 0.5 * connectedness + 0.5 * flush_factor
    if trips:
        wetness = min(wetness, 0.2)   # 트립스 보드는 액션 자체가 얼어붙음.

    # range advantage hint — 보드의 high card 기반 간이 근사.
    # A/K → PFR 이점. 5~8 low → caller 이점 (SB defend / BB call).
    high = ranks[0]
    if high >= _RANK_VALUE["Q"]:
        range_adv = 0.5 - 0.3 * wetness
    elif high >= _RANK_VALUE["T"]:
        range_adv = 0.25 - 0.25 * wetness
    elif high >= _RANK_VALUE["7"]:
        range_adv = -0.1 - 0.1 * wetness
    else:
        range_adv = -0.3 - 0.1 * wetness

    # paired 보드는 PFR 이점 약간 감쇠 (callers 도 trips 가능).
    if paired:
        range_adv *= 0.7

    inv_rank = {v: k for k, v in _RANK_VALUE.items()}
    return BoardTexture(
        n_cards=len(community),
        paired=paired,
        trips_on_board=trips,
        monotone=monotone,
        two_tone=two_tone,
        rainbow=rainbow,
        connectedness=round(connectedness, 3),
        wetness=round(wetness, 3),
        high_card=inv_rank[ranks[0]],
        low_card=inv_rank[ranks[-1]],
        range_advantage_hint=round(range_adv, 3),
    )
