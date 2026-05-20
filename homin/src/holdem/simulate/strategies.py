"""6종 baseline 전략 — Bootstrap self-play 용.

근거: plan H.9 — RandomBot, CallStation, NitRock, TAG, LAG, NashJam 대전.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..decide.hand_notation import canonicalize_hand, expand_range


@dataclass
class Decision:
    action: str       # "fold" | "check" | "call" | "raise" | "allin"
    amount: int = 0   # raise 시 총 베팅액


@dataclass
class SimState:
    """현재 플레이어 관점에서의 상태."""
    hole: tuple[str, str]
    community: list[str]
    phase: str                 # preflop|flop|turn|river
    pot: int
    to_call: int
    my_stack: int
    my_bet: int
    bb: int
    n_raises_this_street: int  # voluntary raise 횟수 (post-blind)
    is_sb: bool                # SB (HU 에서 BTN 과 동일)


class BaselineStrategy(ABC):
    name: str

    @abstractmethod
    def act(self, s: SimState, rng: random.Random) -> Decision:
        ...


# --- 구체 전략 ---

class RandomBot(BaselineStrategy):
    name = "random"

    def act(self, s, rng):
        opts = ["fold"] if s.to_call > 0 else ["check"]
        if s.to_call > 0 and s.my_stack > s.to_call:
            opts.append("call")
        if s.n_raises_this_street < 3 and s.my_stack > s.to_call:
            opts.append("raise")
        choice = rng.choice(opts)
        if choice == "raise":
            target = s.my_bet + s.to_call + max(s.bb * 2, int(s.pot * 0.5))
            return Decision("raise", min(target, s.my_bet + s.my_stack))
        return Decision(choice)


class CallStation(BaselineStrategy):
    name = "callstation"

    def act(self, s, rng):
        if s.to_call == 0:
            return Decision("check")
        if s.my_stack <= s.to_call:
            return Decision("allin")
        return Decision("call")


class NitRock(BaselineStrategy):
    name = "nitrock"
    # top 10% 만 플레이
    _RANGE = frozenset(expand_range("77+,ATs+,AJo+,KQs"))

    def act(self, s, rng):
        in_range = canonicalize_hand(s.hole[0], s.hole[1]) in self._RANGE
        if s.phase == "preflop":
            if not in_range:
                return Decision("fold") if s.to_call > 0 else Decision("check")
            if s.n_raises_this_street == 0:
                target = s.my_bet + max(3 * s.bb - s.my_bet, s.bb * 2)
                return Decision("raise", min(target, s.my_bet + s.my_stack))
            # 3bet 마주침: AA/KK/QQ/AK 만 call, 나머지 fold
            strong = frozenset(expand_range("QQ+,AKs,AKo"))
            if canonicalize_hand(s.hole[0], s.hole[1]) in strong:
                return Decision("call") if s.my_stack > s.to_call else Decision("allin")
            return Decision("fold")
        # postflop: strong hand 면 bet/call, 아니면 check/fold
        if in_range:
            if s.to_call == 0:
                target = s.my_bet + max(int(s.pot * 0.66), s.bb * 2)
                return Decision("raise", min(target, s.my_bet + s.my_stack))
            return Decision("call") if s.my_stack > s.to_call else Decision("allin")
        return Decision("check") if s.to_call == 0 else Decision("fold")


class TAG(BaselineStrategy):
    name = "tag"
    _RFI = frozenset(expand_range("22+,A2s+,ATo+,KTs+,KJo+,QTs+,QJo,JTs,T9s,98s"))

    def act(self, s, rng):
        hand = canonicalize_hand(s.hole[0], s.hole[1])
        if s.phase == "preflop":
            if s.n_raises_this_street == 0 and s.to_call <= s.bb:
                if hand in self._RFI:
                    target = s.my_bet + max(int(2.5 * s.bb - s.my_bet), s.bb)
                    return Decision("raise", min(target, s.my_bet + s.my_stack))
                return Decision("fold") if s.to_call > 0 else Decision("check")
            # facing raise: top 10% 만 call, premium 만 3bet
            prem = frozenset(expand_range("TT+,AQs+,AKo"))
            wide = frozenset(expand_range("99+,AJs+,KQs,AQo+"))
            if hand in prem:
                target = s.my_bet + max(int(3 * s.to_call), s.to_call + s.bb * 3)
                return Decision("raise", min(target, s.my_bet + s.my_stack))
            if hand in wide:
                return Decision("call") if s.my_stack > s.to_call else Decision("allin")
            return Decision("fold")
        # postflop: selective aggression.
        strong = hand in frozenset(expand_range("77+,AJs+,AQo+,KQs"))
        if s.to_call == 0:
            if strong:
                target = s.my_bet + max(int(s.pot * 0.66), s.bb * 2)
                return Decision("raise", min(target, s.my_bet + s.my_stack))
            return Decision("check")
        if strong:
            if s.to_call >= s.my_stack:
                return Decision("allin")
            return Decision("call")
        return Decision("fold")


class LAG(BaselineStrategy):
    name = "lag"
    _RFI = frozenset(expand_range("22+,A2s+,A2o+,K2s+,K9o+,Q6s+,Q9o+,J7s+,J9o+,T7s+,T9o,96s+,85s+,75s+,64s+,54s"))

    def act(self, s, rng):
        hand = canonicalize_hand(s.hole[0], s.hole[1])
        if s.phase == "preflop":
            if s.n_raises_this_street == 0 and s.to_call <= s.bb:
                if hand in self._RFI:
                    target = s.my_bet + max(int(3 * s.bb - s.my_bet), s.bb)
                    return Decision("raise", min(target, s.my_bet + s.my_stack))
                return Decision("fold") if s.to_call > 0 else Decision("check")
            # facing raise: 넓게 call, premium/suited 로 3bet
            wide = frozenset(expand_range("55+,A2s+,K9s+,QTs+,JTs,76s,87s,AJo+,KQo"))
            if hand in wide:
                # 50% 3bet, 50% call
                if rng.random() < 0.5:
                    target = s.my_bet + max(int(3 * s.to_call), s.to_call + s.bb * 3)
                    return Decision("raise", min(target, s.my_bet + s.my_stack))
                return Decision("call") if s.my_stack > s.to_call else Decision("allin")
            return Decision("fold")
        # postflop: 자주 bet.
        if s.to_call == 0:
            if rng.random() < 0.7:
                target = s.my_bet + max(int(s.pot * 0.5), s.bb * 2)
                return Decision("raise", min(target, s.my_bet + s.my_stack))
            return Decision("check")
        # facing bet: 60% call
        if rng.random() < 0.6 and s.my_stack > s.to_call:
            return Decision("call")
        return Decision("fold")


class NashJam(BaselineStrategy):
    """M ≤ 15 구간에서만 jam, 그 외엔 TAG 플레이."""
    name = "nashjam"
    _TAG = TAG()
    _JAM = frozenset(expand_range("22+,A2s+,A7o+,KTs+,KJo+,QTs+,QJo,JTs"))

    def act(self, s, rng):
        m = s.my_stack / (max(1, s.bb))
        if m > 15:
            return self._TAG.act(s, rng)
        hand = canonicalize_hand(s.hole[0], s.hole[1])
        if s.phase != "preflop":
            if s.to_call == 0:
                return Decision("check")
            return Decision("call") if s.my_stack > s.to_call else Decision("allin")
        if hand in self._JAM:
            return Decision("allin")
        return Decision("fold") if s.to_call > 0 else Decision("check")


def all_strategies() -> list[BaselineStrategy]:
    return [RandomBot(), CallStation(), NitRock(), TAG(), LAG(), NashJam()]
