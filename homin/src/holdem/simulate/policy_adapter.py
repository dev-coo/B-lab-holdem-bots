"""Real policy → BaselineStrategy adapter.

목적:
    `src/holdem/decide/policy.py` 의 실봇 의사결정 파이프라인(M-mode switch · EV tree ·
    conservatism · multiway 보수)을 시뮬 환경의 `BaselineStrategy` 인터페이스로 감싸,
    실서버 배포 없이 self-play 로 **실봇 성능 측정** 가능하게 한다.

설계 원칙:
    - 프로토콜 재현: SimState → ActionRequest 변환. 시뮬 컨텍스트가 모르는 필드는 기본값.
    - 스테이트풀: 각 adapter 인스턴스가 자체 ProfileStore 보유. 자기대전 시 각 봇이
      상대의 (동일 adapter) 행동을 관찰해 학습.
    - 결정 호출은 동기 `decide()` 로 — async coordinator 는 self-play 부하 방지 위해 비활성.
    - 이름 고유성: 동일 전략 2회 인스턴스화 시 `name="policy-bot"` 은 같으므로,
      tournament_multi 가 자동으로 `#1`, `#2` suffix 부여.

제약:
    - 상대 이름이 시뮬 환경에서 단순 전략 이름(e.g. "tag") 이라 실서버 `bot_name` 과 다름.
      프로필 키스페이스 공유 원하면 외부에서 별도 관리.
    - action_history 는 SimState 에 간단 포맷만 있어, 일부 hand_result 기반 학습은 미작동.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..decide.policy import DecideDeps, build_default_deps, decide
from ..state.profile_store import ProfileStore
from ..transport import protocol as p
from .strategies import BaselineStrategy, Decision, SimState


@dataclass
class PolicyAdapter(BaselineStrategy):
    """실봇 decide() 를 BaselineStrategy 로 노출.

    Attributes:
        name: 시뮬 이름 (기본 "policy-bot").
        deps: DecideDeps (default: build_default_deps).
        profile_store: 선택. None 이면 기본 stored profile_store 사용.
        my_sim_name: adapter 자신의 플레이어 이름 (시뮬 context — Seat matching용).
        include_self_in_players: Action에 "me" 플레이어를 포함시킬지 (서버 프로토콜에 맞춤).
    """
    name: str = "policy-bot"
    deps: DecideDeps | None = None
    profile_store: ProfileStore | None = None
    my_sim_name: str = "policy-bot"
    use_ev_tree_postflop: bool = True
    _deps_cached: DecideDeps | None = field(default=None, init=False, repr=False)

    def _ensure_deps(self) -> DecideDeps:
        if self._deps_cached is not None:
            return self._deps_cached
        deps = self.deps or build_default_deps()
        deps.use_ev_tree_postflop = self.use_ev_tree_postflop
        if self.profile_store is not None:
            deps.profile_store = self.profile_store
        elif deps.profile_store is None:
            deps.profile_store = ProfileStore()
        self._deps_cached = deps
        return deps

    def act(self, s: SimState, rng: random.Random) -> Decision:
        deps = self._ensure_deps()
        req = _state_to_request(s, self.my_sim_name)
        try:
            action = decide(req, self.my_sim_name, deps)
        except Exception:
            # 결정 실패 → 안전 fold/check
            if s.to_call == 0:
                return Decision("check")
            return Decision("fold")

        return _action_to_decision(action, s)


def _state_to_request(s: SimState, my_name: str) -> p.ActionRequest:
    """SimState → ActionRequest 합성.

    시뮬 엔진은 상대 수·bet·stack 정보를 SimState 로 제공하지 않으므로 근사치 구성:
      - players: HU (SB + BB) 또는 알려진 경우 (엔진이 추가 필드 넣어줘야). 현재는 2 명 기본.
      - seat: my_name.
      - min_raise: BB (서버 min raise 의 간단 근사).
    """
    # HU 기본 2인. multi-way 엔진과의 통합은 후속 확장.
    opponents = [
        p.PlayerState(name="opp", stack=0, position="opp", status="active",
                      bet=max(0, s.to_call + s.my_bet)),
    ]
    players = [
        p.PlayerState(name=my_name, stack=s.my_stack, position=my_name,
                      status="active", bet=s.my_bet),
        *opponents,
    ]
    return p.ActionRequest(
        type="action_request",
        room_id=0,
        hand_number=0,
        your_cards=list(s.hole),
        community_cards=list(s.community),
        phase=s.phase,
        pot=s.pot,
        my_stack=s.my_stack,
        to_call=s.to_call,
        min_raise=max(s.bb, s.my_bet + s.bb),
        blind=[max(1, s.bb // 2), s.bb],
        seat=my_name,
        players=players,
        action_history=[],
    )


def _action_to_decision(action: p.Action, s: SimState) -> Decision:
    """p.Action → Decision. invalid raise 는 engine 이 fold 로 처리."""
    if action.action == "raise":
        amount = action.amount or 0
        # min_raise 미달 또는 stack 초과 → sanitize
        if amount <= s.my_bet:
            return Decision("check" if s.to_call == 0 else "call")
        if amount - s.my_bet >= s.my_stack:
            return Decision("allin")
        return Decision("raise", amount=amount)
    if action.action == "allin":
        return Decision("allin")
    if action.action == "call":
        return Decision("call")
    if action.action == "check":
        return Decision("check")
    if action.action == "fold":
        return Decision("fold")
    return Decision("fold")
