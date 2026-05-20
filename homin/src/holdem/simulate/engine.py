"""HU NLHE 핸드 시뮬레이터 — 간이 엔진.

제약:
  - 2-player heads-up.
  - SB = acts first preflop (BTN == SB in HU), BB = acts first postflop.
  - raise cap = 3 per street.
  - Showdown: treys 로 정확 평가.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from treys import Card, Evaluator

from .strategies import BaselineStrategy, Decision, SimState

_EVAL = Evaluator()
_RANKS = "23456789TJQKA"
_SUITS = "shdc"


def make_deck(rng: random.Random) -> list[str]:
    deck = [r + s for r in _RANKS for s in _SUITS]
    rng.shuffle(deck)
    return deck


@dataclass
class PlayerState:
    strategy: BaselineStrategy
    stack: int
    hole: tuple[str, str] = ("", "")
    bet_this_street: int = 0
    total_bet: int = 0
    folded: bool = False
    allin: bool = False


@dataclass
class HandResult:
    winner_idx: int                  # 0 or 1 (or -1 = split)
    winner_names: list[str]
    pot: int
    final_stacks: tuple[int, int]
    community: list[str]
    history: list[dict] = field(default_factory=list)
    showdown_reached: bool = False


def _evaluate_showdown(players: list[PlayerState], community: list[str]) -> tuple[int, int]:
    """Returns (winner_idx, score). −1 → split."""
    board_cards = [Card.new(c) for c in community]
    scores = []
    for pl in players:
        if pl.folded:
            scores.append(None)
            continue
        hand_cards = [Card.new(pl.hole[0]), Card.new(pl.hole[1])]
        score = _EVAL.evaluate(board_cards, hand_cards)   # lower is better
        scores.append(score)
    alive = [(i, s) for i, s in enumerate(scores) if s is not None]
    if len(alive) == 1:
        return alive[0][0], alive[0][1]
    best = min(s for _, s in alive)
    winners = [i for i, s in alive if s == best]
    if len(winners) > 1:
        return -1, best
    return winners[0], best


def _run_street(
    players: list[PlayerState],
    phase: str,
    community: list[str],
    pot: int,
    bb: int,
    first_to_act: int,
    rng: random.Random,
    history: list[dict],
) -> int:
    """한 스트릿 베팅 라운드. pot 의 최신값 반환."""
    max_raises = 3
    n_raises = 0
    acted_since_raise = {0: False, 1: False}
    turn = first_to_act

    while True:
        p = players[turn]
        if p.folded or p.allin:
            # 상대 방향으로 넘김
            nxt = 1 - turn
            if players[nxt].folded or players[nxt].allin:
                break
            turn = nxt
            continue

        to_call = players[1 - turn].bet_this_street - p.bet_this_street
        state = SimState(
            hole=p.hole,
            community=list(community),
            phase=phase,
            pot=pot,
            to_call=max(0, to_call),
            my_stack=p.stack,
            my_bet=p.bet_this_street,
            bb=bb,
            n_raises_this_street=n_raises,
            is_sb=(turn == 0),
        )
        dec = p.strategy.act(state, rng)
        history.append({"phase": phase, "player": turn, "action": dec.action, "amount": dec.amount})

        if dec.action == "fold":
            p.folded = True
            return pot
        if dec.action == "check":
            acted_since_raise[turn] = True
        elif dec.action == "call":
            pay = min(p.stack, to_call)
            p.stack -= pay
            p.bet_this_street += pay
            p.total_bet += pay
            pot += pay
            if p.stack == 0:
                p.allin = True
            acted_since_raise[turn] = True
        elif dec.action == "raise":
            target = dec.amount
            delta = max(0, target - p.bet_this_street)
            delta = min(delta, p.stack)   # 스택 상한
            if delta <= to_call:
                # 무효한 raise → call 로 처리
                pay = min(p.stack, to_call)
            else:
                pay = delta
            p.stack -= pay
            p.bet_this_street += pay
            p.total_bet += pay
            pot += pay
            if p.stack == 0:
                p.allin = True
            if pay > to_call:
                n_raises += 1
                acted_since_raise = {0: False, 1: False}
                acted_since_raise[turn] = True
                if n_raises >= max_raises:
                    # cap: 상대가 call/fold 만 가능
                    pass
            else:
                acted_since_raise[turn] = True
        elif dec.action == "allin":
            pay = p.stack
            p.stack = 0
            p.bet_this_street += pay
            p.total_bet += pay
            pot += pay
            p.allin = True
            if p.bet_this_street > players[1 - turn].bet_this_street:
                n_raises += 1
                acted_since_raise = {0: False, 1: False}
                acted_since_raise[turn] = True
            else:
                acted_since_raise[turn] = True

        # 종료 조건: 두 플레이어 bet 동일 + 양쪽 다 acted_since_raise
        if players[0].folded or players[1].folded:
            break
        if (players[0].bet_this_street == players[1].bet_this_street
                and acted_since_raise[0] and acted_since_raise[1]):
            break
        if players[0].allin and players[1].allin:
            break
        # 한쪽이 부분 allin (bets 불일치) — 남은 한 명이 행동 완료하면 종료.
        # 그렇지 않으면 to_call=0 으로 무한 check 루프.
        if players[0].allin or players[1].allin:
            acting = 1 if players[0].allin else 0
            if acted_since_raise[acting]:
                break
        turn = 1 - turn

    # 스트릿 종료 — bet_this_street 리셋
    for pl in players:
        pl.bet_this_street = 0
    return pot


def run_hand(
    sb_strategy: BaselineStrategy,
    bb_strategy: BaselineStrategy,
    sb_stack: int,
    bb_stack: int,
    bb: int = 2,
    sb_amount: int = 1,
    rng: random.Random | None = None,
) -> HandResult:
    rng = rng or random.Random()
    deck = make_deck(rng)
    players = [
        PlayerState(sb_strategy, sb_stack, (deck.pop(), deck.pop())),
        PlayerState(bb_strategy, bb_stack, (deck.pop(), deck.pop())),
    ]
    # Blind post
    players[0].stack -= sb_amount
    players[0].bet_this_street = sb_amount
    players[0].total_bet = sb_amount
    players[1].stack -= bb
    players[1].bet_this_street = bb
    players[1].total_bet = bb
    pot = sb_amount + bb

    community: list[str] = []
    history: list[dict] = []

    # Preflop: SB acts first
    pot = _run_street(players, "preflop", community, pot, bb, first_to_act=0, rng=rng, history=history)

    # Postflop streets
    for phase, n_new in (("flop", 3), ("turn", 1), ("river", 1)):
        if players[0].folded or players[1].folded:
            break
        for _ in range(n_new):
            community.append(deck.pop())
        if players[0].allin and players[1].allin:
            continue  # just deal remaining, no betting
        pot = _run_street(players, phase, community, pot, bb, first_to_act=1, rng=rng, history=history)

    # 누가 이겼나?
    showdown = False
    if players[0].folded:
        winner_idx = 1
    elif players[1].folded:
        winner_idx = 0
    else:
        # 부족분 보정 (community 5 장 미만이면 남은 카드 뽑기)
        while len(community) < 5:
            community.append(deck.pop())
        winner_idx, _ = _evaluate_showdown(players, community)
        showdown = True

    if winner_idx == -1:
        players[0].stack += pot // 2
        players[1].stack += pot - pot // 2
        winner_names = [players[0].strategy.name, players[1].strategy.name]
    else:
        players[winner_idx].stack += pot
        winner_names = [players[winner_idx].strategy.name]

    return HandResult(
        winner_idx=winner_idx,
        winner_names=winner_names,
        pot=pot,
        final_stacks=(players[0].stack, players[1].stack),
        community=community,
        history=history,
        showdown_reached=showdown,
    )
