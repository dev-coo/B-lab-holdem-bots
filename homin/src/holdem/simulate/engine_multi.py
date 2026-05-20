"""멀티웨이(N=2~9) NLHE 엔진 — side pot 처리 포함.

근거:
    - plan H.8 (multi-way), §6.2 raise 의미, §4 action order.
    - r4/r10 dev_log limitations — HU only 한계 해소.

주요 차이점 (HU 엔진 대비):
    - players 는 배열. dealer/SB/BB idx 명시.
    - Preflop first to act = (BB+1) % n (UTG). HU 에서는 SB.
    - Postflop first to act = SB (첫 non-folded, 시계 방향). HU 특수 규칙 (BB first) 없음.
    - Raise cap 제거 — 멀티웨이에서는 일반적. 대신 action 종료 조건만으로 제어.
    - Side pots: total_bet ceiling 별 pot 분리.

미지원:
    - Rake, antes.
    - 블라인드 자동 교대 (호출자가 관리).
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
    idx: int                     # 0..n-1
    strategy: BaselineStrategy
    stack: int
    hole: tuple[str, str] = ("", "")
    bet_this_street: int = 0
    total_bet: int = 0
    folded: bool = False
    allin: bool = False


@dataclass
class SidePot:
    amount: int
    eligible_idx: list[int]      # 이 pot 자격 플레이어 (non-folded)


@dataclass
class MultiHandResult:
    n_players: int
    winner_idx_per_pot: list[list[int]]   # 각 pot 별 승자 idx 리스트 (split 가능)
    pots: list[SidePot]
    final_stacks: list[int]
    community: list[str]
    history: list[dict] = field(default_factory=list)
    showdown_reached: bool = False


def _is_active(p: PlayerState) -> bool:
    return not p.folded


def _live_for_betting(p: PlayerState) -> bool:
    """아직 이번 스트리트에서 행동 가능한가."""
    return not p.folded and not p.allin


def _compute_side_pots(players: list[PlayerState]) -> list[SidePot]:
    """total_bet ceiling 별 side pot 분할.

    각 고유 `total_bet` 값을 ceiling 으로, 그 사이 구간의 기여금을 한 pot 으로.
    pot 의 참가 자격 = contribution 한 **non-folded** 플레이어.

    Folded 플레이어의 투입액은 pot 에 포함되지만 자격은 없음.
    """
    ceilings = sorted({p.total_bet for p in players if p.total_bet > 0})
    pots: list[SidePot] = []
    last = 0
    for cap in ceilings:
        amount = 0
        eligible: list[int] = []
        for p in players:
            contrib = min(p.total_bet, cap) - last
            if contrib > 0:
                amount += contrib
                if _is_active(p):
                    eligible.append(p.idx)
        if amount > 0 and eligible:
            pots.append(SidePot(amount=amount, eligible_idx=eligible))
        last = cap
    return pots


def _next_actor(players: list[PlayerState], start: int) -> int | None:
    """start 에서부터 시계방향으로 _live_for_betting 인 첫 idx. 없으면 None."""
    n = len(players)
    for off in range(n):
        idx = (start + off) % n
        if _live_for_betting(players[idx]):
            return idx
    return None


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
    """한 스트리트 베팅. pot 의 최신값 반환.

    종료 조건:
      - 활성(non-fold) 1명 이하.
      - 모든 활성이 allin 이거나 bet 동일 + acted.
    """
    n = len(players)
    n_raises = 0
    acted_since_raise = [False] * n
    turn = _next_actor(players, first_to_act)
    if turn is None:
        return pot

    # safety: max iterations (multi-way는 이론상 연쇄 raise 가능하나 n*10 면 충분)
    max_iter = n * 50
    iters = 0

    while True:
        iters += 1
        if iters > max_iter:
            # 안전망 — 실제 작동시 도달 금지.
            break

        # 1. 종료 조건 — 활성 1명 이하
        active_idx = [i for i, p in enumerate(players) if _is_active(p)]
        if len(active_idx) <= 1:
            break
        # 2. 모두 allin
        if all(players[i].allin for i in active_idx):
            break

        # 3. 베팅 완료: 모든 live_for_betting 이 acted, 그들의 bet 동일
        live_idx = [i for i in active_idx if _live_for_betting(players[i])]
        if live_idx and all(acted_since_raise[i] for i in live_idx):
            bets_live = {players[i].bet_this_street for i in live_idx}
            if len(bets_live) <= 1:
                # allin 플레이어가 live 보다 더 큰 bet 올려도, 그들은 이미 행동 완료 — 종료 가능.
                break

        p = players[turn]
        if not _live_for_betting(p):
            nxt = _next_actor(players, (turn + 1) % n)
            if nxt is None or nxt == turn:
                break
            turn = nxt
            continue

        max_other_bet = max(
            (players[i].bet_this_street for i in range(n) if i != turn),
            default=0,
        )
        to_call = max(0, max_other_bet - p.bet_this_street)

        state = SimState(
            hole=p.hole,
            community=list(community),
            phase=phase,
            pot=pot,
            to_call=to_call,
            my_stack=p.stack,
            my_bet=p.bet_this_street,
            bb=bb,
            n_raises_this_street=n_raises,
            is_sb=False,   # 멀티웨이에서 이 플래그는 단순화 — 전략이 판단하게.
        )
        dec: Decision = p.strategy.act(state, rng)
        history.append({
            "phase": phase, "player": turn, "action": dec.action, "amount": dec.amount,
        })

        if dec.action == "fold":
            p.folded = True
        elif dec.action == "check":
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
            target = dec.amount or 0
            delta = max(0, target - p.bet_this_street)
            delta = min(delta, p.stack)
            if delta <= to_call:
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
                acted_since_raise = [False] * n
                acted_since_raise[turn] = True
            else:
                acted_since_raise[turn] = True
        elif dec.action == "allin":
            pay = p.stack
            p.stack = 0
            p.bet_this_street += pay
            p.total_bet += pay
            pot += pay
            p.allin = True
            if p.bet_this_street > max_other_bet:
                n_raises += 1
                acted_since_raise = [False] * n
            acted_since_raise[turn] = True

        # 다음 actor
        nxt = _next_actor(players, (turn + 1) % n)
        if nxt is None:
            break
        turn = nxt

    # 스트리트 종료 — bet_this_street 리셋
    for pl in players:
        pl.bet_this_street = 0
    return pot


def _evaluate_scores(players: list[PlayerState], community: list[str]) -> dict[int, int]:
    """non-folded 플레이어 idx → treys score (lower better)."""
    board = [Card.new(c) for c in community]
    scores: dict[int, int] = {}
    for p in players:
        if p.folded:
            continue
        hand = [Card.new(p.hole[0]), Card.new(p.hole[1])]
        scores[p.idx] = _EVAL.evaluate(board, hand)
    return scores


def _award_pot(pot: SidePot, scores: dict[int, int], players: list[PlayerState]) -> list[int]:
    """단일 pot 의 승자 idx 리스트 (split 가능). 스택 업데이트."""
    eligible = [i for i in pot.eligible_idx if i in scores]
    if not eligible:
        # 이론상 발생 X (side pot 은 non-folded 만 eligible), 안전 처리.
        return []
    best = min(scores[i] for i in eligible)
    winners = [i for i in eligible if scores[i] == best]
    share = pot.amount // len(winners)
    remainder = pot.amount - share * len(winners)
    # 여분은 가장 앞 winner 에게 (공정성 편의상 단순화)
    for i, idx in enumerate(winners):
        players[idx].stack += share + (remainder if i == 0 else 0)
    return winners


def run_hand_multi(
    strategies: list[BaselineStrategy],
    stacks: list[int],
    sb_idx: int = 0,
    bb: int = 2,
    sb_amount: int = 1,
    rng: random.Random | None = None,
) -> MultiHandResult:
    """N-player 한 핸드. strategies, stacks 길이는 동일.

    Action order:
      - Preflop: first_to_act = (bb_idx + 1) % n = (sb_idx + 2) % n. n=2 → SB.
      - Postflop: first_to_act = SB (또는 first non-folded 시계 방향).
    """
    rng = rng or random.Random()
    n = len(strategies)
    if n < 2:
        raise ValueError("need at least 2 players")
    if len(stacks) != n:
        raise ValueError("strategies/stacks length mismatch")

    deck = make_deck(rng)
    players = [
        PlayerState(idx=i, strategy=s, stack=st, hole=(deck.pop(), deck.pop()))
        for i, (s, st) in enumerate(zip(strategies, stacks))
    ]

    # Blinds
    bb_idx = (sb_idx + 1) % n
    sb_pay = min(players[sb_idx].stack, sb_amount)
    players[sb_idx].stack -= sb_pay
    players[sb_idx].bet_this_street = sb_pay
    players[sb_idx].total_bet = sb_pay
    if players[sb_idx].stack == 0:
        players[sb_idx].allin = True

    bb_pay = min(players[bb_idx].stack, bb)
    players[bb_idx].stack -= bb_pay
    players[bb_idx].bet_this_street = bb_pay
    players[bb_idx].total_bet = bb_pay
    if players[bb_idx].stack == 0:
        players[bb_idx].allin = True
    pot = sb_pay + bb_pay

    community: list[str] = []
    history: list[dict] = []

    # Preflop: UTG first (= BB+1). n=2 → UTG == SB.
    preflop_first = sb_idx if n == 2 else (bb_idx + 1) % n
    pot = _run_street(players, "preflop", community, pot, bb, preflop_first, rng, history)

    for phase, n_new in (("flop", 3), ("turn", 1), ("river", 1)):
        if sum(1 for p in players if _is_active(p)) <= 1:
            break
        for _ in range(n_new):
            community.append(deck.pop())
        # 모든 활성이 allin → 베팅 없이 카드만 분배.
        active = [p for p in players if _is_active(p)]
        live = [p for p in active if _live_for_betting(p)]
        if len(live) <= 1:
            continue
        postflop_first = _next_actor(players, sb_idx) or sb_idx
        pot = _run_street(players, phase, community, pot, bb, postflop_first, rng, history)

    # Showdown 필요 여부
    active_idx = [p.idx for p in players if _is_active(p)]
    pots = _compute_side_pots(players)

    winners_per_pot: list[list[int]] = []
    showdown = False

    if len(active_idx) == 1:
        # 유일 생존 — 모든 pot 가져감.
        sole = active_idx[0]
        for po in pots:
            if sole in po.eligible_idx:
                players[sole].stack += po.amount
                winners_per_pot.append([sole])
            else:
                # 이론상 sole 은 모든 pot 에 eligible (non-folded 유일).
                # 안전: 남은 자격자에게 분배.
                remaining = po.eligible_idx
                if remaining:
                    share = po.amount // len(remaining)
                    for i, ridx in enumerate(remaining):
                        players[ridx].stack += share + (po.amount - share * len(remaining) if i == 0 else 0)
                    winners_per_pot.append(list(remaining))
                else:
                    winners_per_pot.append([])
    else:
        # showdown
        while len(community) < 5:
            community.append(deck.pop())
        scores = _evaluate_scores(players, community)
        for po in pots:
            winners_per_pot.append(_award_pot(po, scores, players))
        showdown = True

    return MultiHandResult(
        n_players=n,
        winner_idx_per_pot=winners_per_pot,
        pots=pots,
        final_stacks=[p.stack for p in players],
        community=community,
        history=history,
        showdown_reached=showdown,
    )
