"""게임 상태 — 방(room_id) 별 휘발성 상태.

scope: 한 테이블(room) 의 한 핸드 진행 정보를 보관. 핸드 종료 시 대부분 reset,
       쇼다운·eliminated 요약만 영속 프로필 계층(별도 모듈)으로 넘긴다.

근거:
  - BOT_GUIDE §5 이벤트 시리즈.
  - 평가 B2 — phase_change 이벤트에서 community_cards 싱크.
  - 평가 B3 — joined_room.snapshot 복원 시 my_stack/seat 은 players[] 에서 찾음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..transport import protocol as p

log = logging.getLogger(__name__)


@dataclass
class HandState:
    room_id: int
    hand_number: int
    phase: p.Phase = "preflop"
    my_cards: list[str] = field(default_factory=list)
    my_stack: int = 0
    my_seat: str = ""
    community_cards: list[str] = field(default_factory=list)
    pot: int = 0
    blind_sb: int = 0
    blind_bb: int = 0
    players: list[p.PlayerState] = field(default_factory=list)
    action_history: list[p.HistoryEntry] = field(default_factory=list)

    def find_me(self, bot_name: str) -> p.PlayerState | None:
        for pl in self.players:
            if pl.name == bot_name:
                return pl
        return None


class GameState:
    """room_id → HandState 멀티룸 저장소."""

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self._hands: dict[int, HandState] = {}
        # P5-2: 토너먼트 시작 시점의 인원수 (5-max vs 9-max 구분).
        self._starting_size: dict[int, int] = {}

    def get(self, room_id: int) -> HandState | None:
        return self._hands.get(room_id)

    def starting_table_size(self, room_id: int) -> int | None:
        """토너먼트 시작 시점의 등록 인원. GameStart 미관측 시 None."""
        return self._starting_size.get(room_id)

    def require(self, room_id: int) -> HandState:
        state = self._hands.get(room_id)
        if state is None:
            raise KeyError(f"no hand state for room_id={room_id}")
        return state

    def handle(self, event) -> None:
        """단일 엔트리포인트. 이벤트 종류별로 dispatch."""
        if isinstance(event, p.HandStart):
            self._on_hand_start(event)
        elif isinstance(event, p.PhaseChange):
            self._on_phase_change(event)
        elif isinstance(event, p.ActionPerformed):
            self._on_action_performed(event)
        elif isinstance(event, p.ActionRequest):
            self._on_action_request(event)
        elif isinstance(event, p.HandResult):
            self._on_hand_result(event)
        elif isinstance(event, p.JoinedRoom):
            self._on_joined_room(event)
        elif isinstance(event, p.GameStart):
            self._on_game_start(event)
        elif isinstance(event, p.GameEnd):
            self._on_game_end(event)
        # 그 외 이벤트는 상태 변경 없음

    def _on_game_start(self, ev: p.GameStart) -> None:
        # players 는 list[dict] (스키마 미세 차이 흡수).
        n = len(ev.players)
        if n > 0:
            self._starting_size[ev.room_id] = n

    # --- handlers ---

    def _on_hand_start(self, ev: p.HandStart) -> None:
        sb = ev.blind[0] if len(ev.blind) >= 1 else 0
        bb = ev.blind[1] if len(ev.blind) >= 2 else 0
        # P5-2 fallback: GameStart 미수신 / 빈 players 시 첫 hand_start 의 players 길이로
        # starting_table_size 보충. 이후 hand 들에서는 max(observed) 로 보존 (탈락자
        # 진행 시 최대 인원 유지).
        prior = self._starting_size.get(ev.room_id, 0)
        live = len(ev.players)
        if live > prior:
            self._starting_size[ev.room_id] = live
        state = HandState(
            room_id=ev.room_id,
            hand_number=ev.hand_number,
            phase="preflop",
            my_cards=list(ev.your_cards),
            my_stack=ev.your_stack,
            my_seat=ev.your_seat,
            community_cards=[],
            pot=sb + bb,  # blinds 선입 (server 가 포트 갱신 전까지의 근사)
            blind_sb=sb,
            blind_bb=bb,
            players=list(ev.players),
            action_history=[],
        )
        self._hands[ev.room_id] = state

    def _on_phase_change(self, ev: p.PhaseChange) -> None:
        state = self._hands.get(ev.room_id)
        if state is None:
            return
        state.phase = ev.phase
        state.community_cards = list(ev.community_cards)

    def _on_action_performed(self, ev: p.ActionPerformed) -> None:
        state = self._hands.get(ev.room_id)
        if state is None:
            return
        state.pot = ev.pot or state.pot
        if ev.players:
            state.players = list(ev.players)
        state.action_history.append(p.HistoryEntry(
            phase=state.phase,
            player=ev.player,
            action=ev.action,
            amount=ev.amount,
        ))
        if ev.player == self.bot_name:
            me = state.find_me(self.bot_name)
            if me is not None:
                state.my_stack = me.stack

    def _on_action_request(self, ev: p.ActionRequest) -> None:
        # P-Stage2: starting_size 보강 — ActionRequest 의 active player 수가 기존
        # 추정치보다 크면 갱신. mid-game join 시점에는 이미 일부 탈락됐을 수 있어
        # 정확하지 않지만, 9-max default 보다는 정확. max(observed) 패턴.
        live = sum(1 for pl in ev.players if (pl.name or "").strip())
        prior = self._starting_size.get(ev.room_id, 0)
        if live > prior:
            self._starting_size[ev.room_id] = live
        state = self._hands.get(ev.room_id)
        if state is None:
            state = HandState(
                room_id=ev.room_id,
                hand_number=ev.hand_number,
                phase=ev.phase,
                my_cards=list(ev.your_cards),
                my_stack=ev.my_stack,
                my_seat=ev.seat,
                community_cards=list(ev.community_cards),
                pot=ev.pot,
                blind_sb=ev.blind[0] if len(ev.blind) >= 1 else 0,
                blind_bb=ev.blind[1] if len(ev.blind) >= 2 else 0,
                players=list(ev.players),
                action_history=list(ev.action_history),
            )
            self._hands[ev.room_id] = state
            return
        state.phase = ev.phase
        state.my_cards = list(ev.your_cards)
        state.my_stack = ev.my_stack
        state.my_seat = ev.seat
        state.community_cards = list(ev.community_cards)
        state.pot = ev.pot
        state.players = list(ev.players)
        state.action_history = list(ev.action_history)
        if len(ev.blind) >= 2:
            state.blind_sb, state.blind_bb = ev.blind[0], ev.blind[1]

    def _on_hand_result(self, ev: p.HandResult) -> None:
        state = self._hands.get(ev.room_id)
        if state is None:
            return
        if ev.community_cards:
            state.community_cards = list(ev.community_cards)
        state.pot = ev.pot or state.pot

    def _on_joined_room(self, ev: p.JoinedRoom) -> None:
        # P-Stage2: joined 시 players 길이로도 starting_size 보강.
        if ev.players:
            live = sum(1 for nm in ev.players if (nm or "").strip())
            prior = self._starting_size.get(ev.room_id, 0)
            if live > prior:
                self._starting_size[ev.room_id] = live
        snap = ev.snapshot
        if snap is None:
            self._hands.pop(ev.room_id, None)
            return
        sb = snap.blind[0] if len(snap.blind) >= 1 else 0
        bb = snap.blind[1] if len(snap.blind) >= 2 else 0
        me = next((pl for pl in snap.players if pl.name == self.bot_name), None)
        state = HandState(
            room_id=ev.room_id,
            hand_number=snap.hand_number or 0,
            phase=snap.phase or "preflop",
            my_cards=list(snap.your_cards),
            my_stack=me.stack if me else 0,
            my_seat=(me.position or "") if me else "",
            community_cards=list(snap.community_cards),
            pot=snap.pot,
            blind_sb=sb,
            blind_bb=bb,
            players=list(snap.players),
            action_history=list(snap.action_history),
        )
        self._hands[ev.room_id] = state

    def _on_game_end(self, ev: p.GameEnd) -> None:
        self._hands.pop(ev.room_id, None)
        self._starting_size.pop(ev.room_id, None)
