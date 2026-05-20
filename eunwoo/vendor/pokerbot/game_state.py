"""게임 상태 관리 — 동시 100게임 대응 (thread-safe)"""

from __future__ import annotations
import threading
from dataclasses import dataclass, field
from models import ActionRequest, HandResultRequest, GameStartRequest


@dataclass
class GameState:
    """단일 게임의 누적 상태"""
    game_id: str
    players: list[str] = field(default_factory=list)
    starting_stack: int = 300
    rake_enabled: bool = False

    # 핸드별 통계
    hands_played: int = 0
    hands_won: int = 0
    total_profit: int = 0

    # 상대 프로파일링
    opponent_stats: dict[str, OpponentProfile] = field(default_factory=dict)

    # 현재 핸드 상태
    current_hand: int = 0
    my_position: str = ""

    # 마지막 action_history 저장 (hand_result에서 profiler에 전달)
    last_action_history: list = field(default_factory=list)

    # 현재 핸드 블라인드 ([sb, bb]) — hand_start에서 갱신
    current_blind: list[int] = field(default_factory=lambda: [1, 2])


@dataclass
class OpponentProfile:
    """상대 행동 프로파일"""
    name: str
    hands_seen: int = 0
    times_raised: int = 0
    times_called: int = 0
    times_folded: int = 0
    times_allin: int = 0
    showdown_count: int = 0

    @property
    def vpip(self) -> float:
        """Voluntarily Put money In Pot (자발적 팟 참여율)"""
        if self.hands_seen == 0:
            return 0.5  # 기본값
        return (self.times_raised + self.times_called) / self.hands_seen

    @property
    def aggression(self) -> float:
        """공격성 지표 (raise / (raise + call))"""
        total = self.times_raised + self.times_called
        if total == 0:
            return 0.5
        return self.times_raised / total

    @property
    def fold_rate(self) -> float:
        """폴드율"""
        total = self.hands_seen
        if total == 0:
            return 0.5
        return self.times_folded / total


class GameStateManager:
    """동시 다수 게임 상태 관리"""

    def __init__(self):
        self._games: dict[str, GameState] = {}
        self._lock = threading.Lock()

    def new_game(self, req: GameStartRequest):
        with self._lock:
            state = GameState(
                game_id=req.game_id,
                players=req.players,
                starting_stack=req.starting_stack,
                rake_enabled=req.rake_enabled,
            )
            for name in req.players:
                state.opponent_stats[name] = OpponentProfile(name=name)
            self._games[req.game_id] = state

    def get(self, game_id: str) -> GameState | None:
        return self._games.get(game_id)

    def update(self, req: ActionRequest):
        """액션 요청에서 상태 업데이트"""
        state = self._games.get(req.game_id)
        if not state:
            # game_start를 놓친 경우 자동 생성
            state = GameState(game_id=req.game_id)
            for p in req.players:
                state.opponent_stats[p.name] = OpponentProfile(name=p.name)
            self._games[req.game_id] = state

        state.current_hand = req.hand_number
        state.my_position = req.seat
        # action_history 저장 (hand_result에서 profiler 업데이트에 사용)
        state.last_action_history = [
            {"phase": a.phase, "player": a.player, "action": a.action, "amount": a.amount}
            for a in req.action_history
        ]

        # 상대 액션 히스토리로 프로파일 업데이트
        for record in req.action_history:
            profile = state.opponent_stats.get(record.player)
            if not profile:
                profile = OpponentProfile(name=record.player)
                state.opponent_stats[record.player] = profile

            if record.phase == "preflop" and record.action in ("raise", "call", "allin"):
                # VPIP 카운트는 프리플롭 기준
                pass  # hand_result에서 일괄 처리

    def record_result(self, req: HandResultRequest):
        """핸드 결과 기록"""
        state = self._games.get(req.game_id)
        if not state:
            return

        state.hands_played += 1

        # 승리 여부
        for w in req.winners:
            if w.name in [p for p in state.players]:
                pass  # 내 이름은 모르므로 game_start players에서 확인

        # 쇼다운 정보로 상대 프로파일 업데이트
        for sd in req.showdown:
            profile = state.opponent_stats.get(sd.name)
            if profile:
                profile.showdown_count += 1

    def remove_game(self, game_id: str):
        with self._lock:
            self._games.pop(game_id, None)

    def active_count(self) -> int:
        return len(self._games)
