"""range_advantage — hero vs opponent range equity on given board (v5 §C).

우리가 가진 한 쌍의 카드 equity 뿐 아니라, **우리 포지션·프리플롭 액션이 강제한
레인지** 가 해당 보드에서 얼마나 강한지를 본다. 같은 70% equity 라도:

- 보드가 우리 레인지에 유리 (RA~0.65) → raise_thr 낮춰 더 공격적.
- 보드가 상대 레인지에 유리 (RA~0.35) → raise_thr 올려 pot control.

Hero range 재구성 규칙 (단순화, v4 프리플롭 테이블 재사용):
- 프리플롭에서 내가 raise/allin 했다면: `open_range(pos)`
- 프리플롭에서 내가 3bet+ 했다면: `three_bet_range(pos, vs_pos)` (이번 구현은 간단히 open_range 교집합 three_bet 사용)
- 프리플롭에서 내가 call 만 했다면: `call_range(pos, vs_pos)` (cold-call 쪽)
- 프리플롭 액션 없음 (BB check): `open_range("BB")` 이 없으니 → `call_range(BB, pos)` 사용

MC: 500 샘플 기본. hero 랜덤 샘플링 × opp 랜덤 샘플링 → rank7 비교로 RA.
"""

from __future__ import annotations

import random
from typing import Any

from holdem_core.hand_eval import rank7

from holdem_main_bot.opp_range import _hand_key
from holdem_main_bot.position import Position
from holdem_main_bot.preflop_ranges import (
    CALL_VS_OPEN_IP,
    CALL_VS_OPEN_OOP,
    OPEN_BB,
    OPEN_EP,
    OPEN_LP,
    OPEN_MP,
    OPEN_SB,
    THREE_BET_IP,
    THREE_BET_OOP,
)

_RANKS = "23456789TJQKA"
_SUITS = "shdc"
_FULL_DECK: tuple[str, ...] = tuple(r + s for r in _RANKS for s in _SUITS)


def _open_keys_for_pos(pos: Position) -> frozenset[str]:
    if pos == "EP":
        return OPEN_EP
    if pos == "MP":
        return OPEN_MP
    if pos == "LP":
        return OPEN_LP
    if pos == "SB":
        return OPEN_SB
    return OPEN_BB


def _hero_class_keys(
    pos: Position,
    my_preflop_actions: list[str],
    vs_pos: Position | None,
) -> frozenset[str]:
    """내 포지션과 프리플롭 액션 시퀀스로 추정한 hero range class keys."""
    raised = any(a in ("raise", "allin") for a in my_preflop_actions)
    called = any(a == "call" for a in my_preflop_actions)

    if raised:
        n_raises = sum(1 for a in my_preflop_actions if a in ("raise", "allin"))
        # v5.4 (WARN1 fix): BB 의 첫 raise 는 항상 3bet (BB 는 OPEN 자체가 없음).
        # 이전에는 OPEN_BB 폴백으로 빈 set 반환 → range_advantage 0.5 (중립) 로 떨어짐.
        is_bb_3bet = pos == "BB"
        if n_raises >= 2 or is_bb_3bet:
            in_position = pos in ("LP",) and (vs_pos not in ("LP",)) if vs_pos else False
            if in_position:
                return THREE_BET_IP
            return THREE_BET_OOP
        return _open_keys_for_pos(pos)

    if called:
        in_position = pos in ("LP",) and (vs_pos not in ("LP",)) if vs_pos else False
        return CALL_VS_OPEN_IP if in_position else CALL_VS_OPEN_OOP

    # 액션 없음 (BB check 등): 방어 레인지로 폴백.
    return CALL_VS_OPEN_OOP


def hero_range_combos(
    pos: Position,
    my_preflop_actions: list[str],
    dead_cards: set[str],
    vs_pos: Position | None = None,
) -> list[tuple[str, str]]:
    """클래스 키 집합을 실제 combo 리스트로 확장. dead cards 는 제외."""
    class_set = _hero_class_keys(pos, my_preflop_actions, vs_pos)
    if not class_set:
        return []
    remaining = [c for c in _FULL_DECK if c not in dead_cards]
    combos: list[tuple[str, str]] = []
    for i in range(len(remaining)):
        for j in range(i + 1, len(remaining)):
            c1, c2 = remaining[i], remaining[j]
            if _hand_key(c1, c2) in class_set:
                combos.append((c1, c2))
    return combos


def range_advantage(
    hero_combos: list[tuple[str, str]],
    opp_combos: list[tuple[str, str]] | None,
    board: list[str],
    samples: int = 500,
    rng: random.Random | None = None,
) -> float:
    """hero 레인지 × opp 레인지 2-player 평균 승률 (tie = 0.5).

    opp_combos 가 None 이면 덱 랜덤 (매우 낮은 정보 가정).
    board 길이 3~5 필수; 미만이면 0.5 반환 (중립).
    hero_combos 비어 있어도 0.5.
    """
    if not hero_combos or len(board) < 3:
        return 0.5
    r = rng if rng is not None else random.Random()
    dead_base = set(board)
    # hero 샘플 → opp 샘플 이후 runout.
    runout_n = 5 - len(board)

    wins = 0
    ties = 0
    valid = 0
    # 작은 for-loop. 500 샘플 기본. rank7 한 번/샘플.
    for _ in range(samples):
        hero = r.choice(hero_combos)
        dead = dead_base | set(hero)

        if opp_combos is None:
            remaining = [c for c in _FULL_DECK if c not in dead]
            if len(remaining) < 2 + runout_n:
                continue
            draw = r.sample(remaining, 2 + runout_n)
            opp = (draw[0], draw[1])
            runout = draw[2:]
        else:
            # combo 샘플링 — 충돌 시 최대 5회 재시도.
            picked = None
            for _try in range(5):
                cand = r.choice(opp_combos)
                if cand[0] not in dead and cand[1] not in dead and cand[0] != cand[1]:
                    picked = cand
                    break
            if picked is None:
                continue
            opp = picked
            dead2 = dead | set(opp)
            remaining = [c for c in _FULL_DECK if c not in dead2]
            if len(remaining) < runout_n:
                continue
            runout = r.sample(remaining, runout_n) if runout_n > 0 else []

        full_board = list(board) + list(runout)
        my = rank7(list(hero) + full_board)
        ot = rank7(list(opp) + full_board)
        if my > ot:
            wins += 1
        elif my == ot:
            ties += 1
        valid += 1

    if valid == 0:
        return 0.5
    return (wins + 0.5 * ties) / valid


def my_preflop_actions(history: list[Any], my_seat_name: str) -> list[str]:
    """history 에서 내 프리플롭 액션 시퀀스(action 문자열 list) 추출.

    my_seat_name: req.players 중 나에 해당하는 name. (seat 은 position 문자열이라
    history 의 player name 과 매핑 불가 — 상위에서 name 주입)
    """
    out: list[str] = []
    for a in history:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("phase") != "preflop":
            continue
        if d.get("player") != my_seat_name:
            continue
        act = d.get("action")
        if isinstance(act, str):
            out.append(act)
    return out
