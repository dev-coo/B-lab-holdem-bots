"""Equity 계산 — treys Monte Carlo.

근거: plan Section D2 (Equity 엔진), H.5 (board_texture 는 별도 모듈).

인터페이스:
  - `equity(hole, community, n_opp, samples)` — 일반.
  - `preflop_equity_vs_random(hand_code, n_opp, samples)` — 169 canonical 기반 LUT 캐시.
  - `equity_vs_range(hole, community, villain_range, n_opp, samples)` — 상대 range 지정.

성능 타깃: 단일 호출 < 80ms (turn/river MC 기준). BOT_GUIDE §6.3 의 30s 하드 제약 대비 충분.
"""
from __future__ import annotations

import random
from functools import lru_cache

from treys import Card, Evaluator

from ..decide.hand_notation import RANKS, canonicalize_hand, expand_range

_EVAL = Evaluator()
_SUITS = ("s", "h", "d", "c")


def _build_deck() -> list[int]:
    return [Card.new(r + s) for r in RANKS for s in _SUITS]


_FULL_DECK = _build_deck()


def _card_ints(cards: list[str]) -> list[int]:
    return [Card.new(c) for c in cards]


def equity(
    hole: list[str],
    community: list[str] | None = None,
    n_opp: int = 1,
    samples: int = 1000,
    *,
    seed: int | None = None,
) -> float:
    """순수 MC: 내 홀 vs n_opp 랜덤 상대. 승률 + 0.5·tie / samples.

    - 커뮤니티 카드가 주어지면 그 보드에 나머지만 채움.
    - n_opp=0 이면 1.0 반환.
    - samples ≤ 0 이면 0.5 (기본값) 반환.
    """
    if n_opp <= 0:
        return 1.0
    if samples <= 0:
        return 0.5

    hole_ints = _card_ints(hole)
    board_ints = _card_ints(community or [])
    used = set(hole_ints) | set(board_ints)
    if len(used) != len(hole_ints) + len(board_ints):
        raise ValueError(f"duplicate cards in hole/community: {hole}, {community}")

    deck_pool = [c for c in _FULL_DECK if c not in used]
    need_board = 5 - len(board_ints)
    need_opp = 2 * n_opp
    if need_board < 0 or need_opp + need_board > len(deck_pool):
        raise ValueError("not enough cards in deck")

    rng = random.Random(seed)
    wins = 0
    ties = 0
    for _ in range(samples):
        sample = rng.sample(deck_pool, need_opp + need_board)
        opp_holes = [sample[i:i + 2] for i in range(0, need_opp, 2)]
        extra_board = sample[need_opp:need_opp + need_board]
        full_board = board_ints + extra_board

        my_score = _EVAL.evaluate(full_board, hole_ints)
        best_opp = min(_EVAL.evaluate(full_board, h) for h in opp_holes)

        if my_score < best_opp:       # treys: 낮을수록 강함
            wins += 1
        elif my_score == best_opp:
            ties += 1

    return (wins + 0.5 * ties) / samples


def _representative_combo(code: str) -> list[str]:
    """canonical hand code → 1 개 구체 조합."""
    if len(code) == 2:   # pair
        r = code[0]
        return [r + "s", r + "h"]
    r1, r2, suffix = code[0], code[1], code[2]
    if suffix == "s":
        return [r1 + "s", r2 + "s"]
    return [r1 + "s", r2 + "h"]


@lru_cache(maxsize=169 * 8)
def preflop_equity_vs_random(
    hand_code: str,
    n_opp: int = 1,
    samples: int = 2000,
    seed: int = 42,
) -> float:
    """Canonical 코드(AA / AKs / 72o) vs 랜덤 n_opp 의 프리플롭 equity.

    결정론적: seed 고정. LRU 캐시 적용 — 동일 인자 재호출 즉시 반환.
    """
    hole = _representative_combo(hand_code)
    return equity(hole, [], n_opp=n_opp, samples=samples, seed=seed)


def equity_from_cards(
    c1: str,
    c2: str,
    community: list[str] | None = None,
    n_opp: int = 1,
    samples: int = 1000,
    *,
    seed: int | None = None,
) -> float:
    """두 장 카드 + (커뮤니티) → equity. 프리플롭이면 LUT 경로로 수렴."""
    if not community:
        code = canonicalize_hand(c1, c2)
        return preflop_equity_vs_random(code, n_opp=n_opp, samples=samples)
    return equity([c1, c2], community, n_opp=n_opp, samples=samples, seed=seed)


def equity_vs_range(
    hole: list[str],
    community: list[str] | None,
    villain_range_spec: str,
    n_opp: int = 1,
    samples: int = 1000,
    *,
    seed: int | None = None,
) -> float:
    """상대 range (shorthand) 에 대한 가중 MC.

    각 샘플에서 range 내 조합을 uniform 추출 후 블로킹 카드 충돌 시 재뽑기.
    range 에서 유효 조합이 없으면 0.5 반환 (알 수 없음).
    """
    if n_opp <= 0:
        return 1.0
    villain_codes = expand_range(villain_range_spec)
    if not villain_codes:
        return 0.5

    hole_ints = _card_ints(hole)
    board_ints = _card_ints(community or [])
    used = set(hole_ints) | set(board_ints)

    # 가능한 모든 구체 combo 를 villain_codes 로부터 확장
    combos: list[list[int]] = []
    for code in villain_codes:
        combos.extend(_expand_combos_for_code(code))
    # hole/board 와 충돌하지 않는 combo 만 유지
    valid_combos = [c for c in combos if not (set(c) & used)]
    if not valid_combos:
        return 0.5

    need_board = 5 - len(board_ints)
    rng = random.Random(seed)
    wins = ties = 0
    for _ in range(samples):
        # 상대 combo 추출
        for _retry in range(20):
            opp = rng.choice(valid_combos)
            if not (set(opp) & used):
                break
        else:
            continue
        local_used = used | set(opp)
        pool = [c for c in _FULL_DECK if c not in local_used]
        if need_board > len(pool):
            continue
        extra = rng.sample(pool, need_board) if need_board > 0 else []
        full_board = board_ints + extra

        my_score = _EVAL.evaluate(full_board, hole_ints)
        opp_score = _EVAL.evaluate(full_board, opp)
        if my_score < opp_score:
            wins += 1
        elif my_score == opp_score:
            ties += 1
    return (wins + 0.5 * ties) / samples


def _expand_combos_for_code(code: str) -> list[list[int]]:
    """canonical code → 모든 구체 2-card combo 의 treys int 리스트."""
    if len(code) == 2:   # pair
        r = code[0]
        cards = [r + s for s in _SUITS]
        out = []
        for i in range(len(cards)):
            for j in range(i + 1, len(cards)):
                out.append([Card.new(cards[i]), Card.new(cards[j])])
        return out
    r1, r2, suffix = code[0], code[1], code[2]
    out = []
    if suffix == "s":
        for s in _SUITS:
            out.append([Card.new(r1 + s), Card.new(r2 + s)])
    else:   # 'o'
        for s1 in _SUITS:
            for s2 in _SUITS:
                if s1 == s2:
                    continue
                out.append([Card.new(r1 + s1), Card.new(r2 + s2)])
    return out
