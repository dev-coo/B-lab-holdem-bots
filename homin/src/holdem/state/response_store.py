"""Per-opponent × phase Dirichlet response store.

목적:
    EV tree 의 `ev_raise` 경로에서 sample 하는 `p_fold/p_call/p_raise` 를 개별 상대 ×
    phase 기반으로 학습. 현 coordinator 경로가 Dirichlet(1,1,1) 상수를 쓰는 문제를
    해결 (hand 2 river allin 과적합 회귀의 원인).

키: `(opponent_name, phase)`. phase ∈ {preflop, flop, turn, river}.
업데이트: `observe_from_hand(history)` — action_history 순회하며 각 상대 × phase 의
    fold/call/raise 비율 카운트.

사용 (policy.postflop_candidates):
    response = store.lookup(opp_name, phase)
    ev_raise(amount, response, inputs)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from ..estimate.bayes import DirichletResponse
from ..transport import protocol as p


@dataclass
class ResponseStore:
    table: dict[tuple[str, str], DirichletResponse] = field(
        default_factory=lambda: defaultdict(DirichletResponse)
    )

    def lookup(self, opponent_name: str, phase: str) -> DirichletResponse:
        """이름 × phase 의 response. 없으면 신규 DirichletResponse(1,1,1) 반환."""
        key = (opponent_name, phase)
        if key not in self.table:
            self.table[key] = DirichletResponse()
        return self.table[key]

    def aggregate(self, opponent_names: Iterable[str], phase: str) -> DirichletResponse:
        """여러 상대의 response 를 alpha 합산. 멀티웨이용 coarse 집계.

        관측이 있는 상대만 합산. 전혀 없으면 default (1,1,1) 반환.
        """
        agg = DirichletResponse(alpha_fold=0.0, alpha_call=0.0, alpha_raise=0.0)
        seen = False
        for name in opponent_names:
            key = (name, phase)
            r = self.table.get(key)
            if r is None:
                continue
            agg.merge(r)
            seen = True
        if not seen:
            return DirichletResponse()
        return agg

    def observe_from_hand(self, history: Iterable[p.HistoryEntry]) -> None:
        """완료된 핸드의 action_history → 각 상대 × phase 에 observe.

        blind 자동 투입은 action_history 에 없음 (BOT_GUIDE §5.4) → 순수 voluntary 행동만.
        """
        for entry in history:
            self.lookup(entry.player, entry.phase).observe(entry.action)

    def n_opponents(self) -> int:
        return len({k[0] for k in self.table.keys()})
