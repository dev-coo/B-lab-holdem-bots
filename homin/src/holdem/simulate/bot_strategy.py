"""실제 봇 의사결정(`holdem.decide.policy.decide`) 을 시뮬레이터의 BaselineStrategy
인터페이스로 노출하는 어댑터.

용도: tournament_sim 에서 다른 baseline 들과 동일 조건에서 실제 봇 전략을
1등% / ITM% / bubble survival 등으로 비교하기 위함. 시뮬레이터를 통한 회귀 측정.

한계:
  - SimState 는 hole/community/pot/to_call/my_stack/my_bet/phase/bb/is_sb/
    n_raises_this_street 만 포함 — 멀티웨이의 경우 dealer/SB/BB idx 와 다른
    플레이어들의 stack 정보가 보이지 않음. 따라서 multi-way 에서 position 분류는
    근사 (HU 만 정확).
  - HU 시: is_sb=True → seat="btn", False → seat="bb" 로 매핑.
  - Multi-way (3+) 에서는 is_sb 가 항상 False (engine_multi 의 단순화) → BLIND 위치
    로 간주. 실제 봇의 multi-way 의사결정 품질을 정확히 측정하려면 engine 측에서
    full PlayerState 정보를 노출해야 함 (별도 PR).

품질 검증 관점에서는 어차피 변경 전/후 BotStrategy 출력이 동일 근사 위에서
비교되므로 *상대* 차이는 의미 있음.
"""
from __future__ import annotations

import random
from typing import Optional

from ..decide.policy import DecideDeps, build_default_deps, decide
from ..transport import protocol as p
from .strategies import BaselineStrategy, Decision, SimState


class BotStrategy(BaselineStrategy):
    """`decide()` 를 호출하는 BaselineStrategy 어댑터.

    Args:
        deps: DecideDeps 또는 None (None 이면 build_default_deps()).
        bot_name: ActionRequest.seat / players 매핑에 사용. 기본 "bot".
        name: BaselineStrategy.name (시뮬 결과 표기). 기본 "bot".
    """

    def __init__(
        self,
        deps: Optional[DecideDeps] = None,
        bot_name: str = "bot",
        name: str = "bot",
    ) -> None:
        self.deps = deps or build_default_deps()
        self.bot_name = bot_name
        self.name = name

    def act(self, s: SimState, rng: random.Random) -> Decision:
        # SimState → ActionRequest
        if s.is_sb:
            my_seat = "btn"   # HU 에서 SB = BTN.
            opp_seat = "bb"
        else:
            my_seat = "bb"
            opp_seat = "btn"

        # 상대 모델 — HU 1명 가정. to_call 에서 상대의 누적 bet 추정.
        # to_call > 0 이면 상대가 (my_bet + to_call) 만큼 투입한 상태.
        opp_bet = s.my_bet + s.to_call
        # 상대 스택 추정: pot 의 절반 정도 또는 my_stack — 정확치 않지만 decide()
        # 가 my_stack 외 villain stack 을 직접 참조하지 않으므로 근사 OK.
        opp_stack_est = max(s.my_stack, 1)

        my_player = p.PlayerState(
            name=self.bot_name,
            position=my_seat,
            stack=s.my_stack,
            bet=s.my_bet,
            status="active",
        )
        opp_player = p.PlayerState(
            name="opp",
            position=opp_seat,
            stack=opp_stack_est,
            bet=opp_bet,
            status="active",
        )
        players = [my_player, opp_player]

        # action_history: preflop 에서 상대가 raise/jam 했는지를 facing_raise 판정에
        # 사용 (decide 가 _is_facing_raise 로 본다). HU 에서 to_call > bb 이면 상대
        # voluntary raise. raise/allin 구분: to_call ≥ opp_stack 면 allin.
        history: list[p.HistoryEntry] = []
        if s.phase == "preflop" and s.n_raises_this_street >= 1 and s.to_call > 0:
            opp_action = "allin" if s.to_call >= opp_stack_est else "raise"
            history.append(
                p.HistoryEntry(
                    phase="preflop",
                    player="opp",
                    action=opp_action,
                    amount=opp_bet,
                )
            )

        # min_raise: 일반적으로 max(bb, to_call*2 - my_bet).
        # decide() 의 hybrid open 경로가 min_raise <= my_stack 을 요구하므로 안전 하한.
        min_raise = max(s.bb, s.to_call * 2)
        if min_raise <= 0:
            min_raise = max(1, s.bb)

        sb = max(1, s.bb // 2)
        req = p.ActionRequest(
            type="action_request",
            room_id=0,
            hand_number=1,
            your_cards=list(s.hole),
            community_cards=list(s.community),
            phase=s.phase,    # type: ignore[arg-type]
            pot=s.pot,
            my_stack=s.my_stack,
            to_call=s.to_call,
            min_raise=min_raise,
            blind=[sb, s.bb],
            seat=my_seat,
            players=players,
            action_history=history,
        )

        try:
            action = decide(req, self.bot_name, self.deps)
        except Exception:
            # 어댑터 변환 실패 시 안전 fold/check.
            return Decision("fold" if s.to_call > 0 else "check")

        # Action → Decision (시뮬 엔진 형식).
        amt = int(action.amount or 0)
        return Decision(action.action, amt)


def make_bot_strategy(
    name: str = "bot",
    use_ev_tree: bool = False,
    bot_name: str = "bot",
) -> BotStrategy:
    """tournament_sim 에서 바로 사용할 수 있는 BotStrategy 팩토리.

    Args:
        name: 결과 표 표기용 이름 ("bot", "bot-ev", "bot-full" 등).
        use_ev_tree: True 면 D6 postflop EV tree 활성.
        bot_name: ActionRequest.seat 와 무관한 봇 식별자.
    """
    deps = build_default_deps()
    deps.use_ev_tree_postflop = use_ev_tree
    return BotStrategy(deps=deps, bot_name=bot_name, name=name)
