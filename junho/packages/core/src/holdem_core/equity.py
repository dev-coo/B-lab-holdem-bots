"""Monte-Carlo equity 추정.

주어진 홀카드 2장 + 커뮤니티 보드(0~5장)에 대해 상대 1명의 홀카드와 남은
런아웃을 무작위 샘플링해 승률을 추정한다.

`opp_combos` 를 주면 상대를 해당 combo 리스트에서 균등 샘플링 (레인지 가정).
주지 않으면 덱의 남은 47장에서 랜덤 2장 샘플링 (상대 완전 랜덤 가정).

타이는 0.5로 카운트. 반환값은 [0.0, 1.0].
"""

from __future__ import annotations

import random

from holdem_core.hand_eval import rank7

_RANKS = "23456789TJQKA"
_SUITS = "shdc"
_FULL_DECK: tuple[str, ...] = tuple(r + s for r in _RANKS for s in _SUITS)


def equity_mc(
    hole: list[str],
    board: list[str],
    samples: int = 2000,
    opp_combos: list[tuple[str, str]] | None = None,
    rng: random.Random | None = None,
) -> float:
    """hole(2장) + board(0~5장)에서 상대 1명 대비 equity.

    board 가 5장이면 런아웃 없이 상대 카드만 샘플링.
    """
    r = rng if rng is not None else random.Random()
    known = set(hole) | set(board)
    runout_n = 5 - len(board)

    wins = 0
    ties = 0

    if opp_combos is None:
        # 기존 경로: 덱 랜덤
        remaining = [c for c in _FULL_DECK if c not in known]
        draw_n = 2 + runout_n
        for _ in range(samples):
            draw = r.sample(remaining, draw_n)
            opp = draw[:2]
            runout = draw[2:]
            full_board = board + runout
            my = rank7(hole + full_board)
            op = rank7(opp + full_board)
            if my > op:
                wins += 1
            elif my == op:
                ties += 1
        return (wins + 0.5 * ties) / samples

    # 레인지 경로: 상대 combo 리스트에서 추첨, 런아웃은 남은 덱에서
    # combo 는 dead_cards 기준으로 이미 필터되어 있다고 가정 (opp_range.tier_combos).
    for _ in range(samples):
        opp_pair = r.choice(opp_combos)
        opp_set = {opp_pair[0], opp_pair[1]}
        # 런아웃 샘플링 시 상대 카드도 제외
        if runout_n > 0:
            deck_after = [c for c in _FULL_DECK if c not in known and c not in opp_set]
            runout = r.sample(deck_after, runout_n)
        else:
            runout = []
        full_board = board + runout
        my = rank7(hole + full_board)
        op = rank7(list(opp_pair) + full_board)
        if my > op:
            wins += 1
        elif my == op:
            ties += 1

    return (wins + 0.5 * ties) / samples


def equity_mc_multi(
    hole: list[str],
    board: list[str],
    n_opps: int,
    opp_combos_list: list[list[tuple[str, str]] | None] | None = None,
    samples: int = 2000,
    rng: random.Random | None = None,
) -> float:
    """내가 동시에 n_opps 명 상대와 비교할 때의 equity.

    `opp_combos_list[i]` 가 None 이면 상대 i 는 랜덤 덱에서 샘플링. 리스트 자체가
    None 이거나 길이가 부족하면 나머지 상대는 랜덤.
    각 sample: 상대별로 combo/랜덤 2장 배정 + 런아웃 → 7카드 랭크 비교.
    내가 최고면 +1 승. 최고 공동이 k 명이면 승리 기여 1/k (전체 k 명 중 내가
    포함되어야 함).

    반환: [0.0, 1.0]. 상대 1명 + opp_combos 주어졌을 때 `equity_mc` 와 수치상
    통계적으로 일치해야 한다.
    """
    if n_opps <= 0:
        return 1.0
    r = rng if rng is not None else random.Random()
    known = set(hole) | set(board)
    runout_n = 5 - len(board)

    if opp_combos_list is None:
        opp_combos_list = [None] * n_opps
    # 길이 부족하면 None 으로 패딩
    while len(opp_combos_list) < n_opps:
        opp_combos_list.append(None)

    win_score = 0.0
    for _ in range(samples):
        used = set(known)
        opp_hands: list[list[str]] = []
        failed = False
        # 1) 각 상대의 2장을 뽑음. combos 주어진 경우 dead 와 충돌하면 재시도.
        for i in range(n_opps):
            combos = opp_combos_list[i]
            picked: tuple[str, str] | None = None
            if combos:
                for _try in range(20):
                    cand = r.choice(combos)
                    if cand[0] not in used and cand[1] not in used:
                        picked = cand
                        break
            if picked is None:
                deck = [c for c in _FULL_DECK if c not in used]
                if len(deck) < 2:
                    failed = True
                    break
                deal = r.sample(deck, 2)
                picked = (deal[0], deal[1])
            used.add(picked[0])
            used.add(picked[1])
            opp_hands.append([picked[0], picked[1]])
        if failed:
            continue
        # 2) 런아웃
        if runout_n > 0:
            deck_after = [c for c in _FULL_DECK if c not in used]
            if len(deck_after) < runout_n:
                continue
            runout = r.sample(deck_after, runout_n)
        else:
            runout = []
        full_board = board + runout
        my = rank7(hole + full_board)
        ranks = [rank7(h + full_board) for h in opp_hands]
        best = max([my, *ranks])
        if my < best:
            continue
        # 공동 최고 수
        tied = 1 + sum(1 for rr in ranks if rr == my)
        win_score += 1.0 / tied

    return win_score / samples
