"""상대 프로파일링 — action_history에서 실시간 지표 추출 및 유형 분류

Phase 9: 크로스게임 프로파일링 + 동적 유형 전환 감지
- stats를 player_name 키로 관리 (게임 간 학습 지속)
- current_type: 최근 10핸드 기반 실시간 유형 (상대 전략 전환 대응)
- style_shift: 전체 유형 vs 최근 유형 불일치 시 True
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from models import ActionRequest, ActionRecord, HandResultRequest


class PlayerType(Enum):
    UNKNOWN = "unknown"       # 데이터 부족 (10핸드 미만)
    LAG = "lag"               # Loose Aggressive — 많이 참여, 세게
    LAP = "lap"               # Loose Passive — 많이 참여, 콜만 (콜링스테이션)
    TAG = "tag"               # Tight Aggressive — 적게 참여, 세게
    TAP = "tap"               # Tight Passive — 적게 참여, 콜만


@dataclass
class PlayerStats:
    """단일 상대의 누적 통계"""
    name: str

    # 핸드 카운트
    hands_seen: int = 0           # 관찰한 총 핸드 수
    hands_voluntarily: int = 0    # 자발적 참여 (BB 체크 제외)
    preflop_raises: int = 0       # 프리플롭 레이즈/3벳
    postflop_bets: int = 0        # 포스트플롭 벳/레이즈
    postflop_calls: int = 0       # 포스트플롭 콜
    postflop_checks: int = 0      # 포스트플롭 체크
    folds: int = 0                # 폴드 횟수
    allins: int = 0               # 올인 횟수
    showdowns: int = 0            # 쇼다운 도달

    # C-bet 관련
    cbet_opportunities: int = 0   # C-bet 기회 (프리플롭 레이저 → 플롭)
    cbet_made: int = 0            # 실제 C-bet
    faced_cbet: int = 0           # C-bet 받은 횟수
    folded_to_cbet: int = 0       # C-bet에 폴드

    # 3bet 관련
    three_bet_opportunities: int = 0
    three_bets: int = 0

    # 최근 10핸드 (동적 전환 감지용)
    recent_actions: list[str] = field(default_factory=list)

    # 베팅 크기 분포 (RL state feature용) — 최근 30개 샘플만 유지
    preflop_raise_bb_samples: list[float] = field(default_factory=list)   # amount/BB
    postflop_bet_pot_samples: list[float] = field(default_factory=list)   # amount/pot_at_bet
    postflop_bet_amount_samples: list[int] = field(default_factory=list)  # raw amount (pot 불명 시 fallback)

    @property
    def vpip(self) -> float:
        """Voluntarily Put money In Pot"""
        if self.hands_seen < 3:
            return 0.5  # 기본값
        return self.hands_voluntarily / self.hands_seen

    @property
    def pfr(self) -> float:
        """Preflop Raise %"""
        if self.hands_seen < 3:
            return 0.3
        return self.preflop_raises / self.hands_seen

    @property
    def af(self) -> float:
        """Aggression Factor = (bet+raise) / call"""
        if self.postflop_calls == 0:
            return 3.0 if self.postflop_bets > 0 else 1.0
        return self.postflop_bets / self.postflop_calls

    @property
    def fold_rate(self) -> float:
        """총 폴드율"""
        total = self.hands_seen
        if total < 3:
            return 0.4
        return self.folds / total

    @property
    def cbet_rate(self) -> float:
        """C-bet 빈도"""
        if self.cbet_opportunities == 0:
            return 0.6
        return self.cbet_made / self.cbet_opportunities

    @property
    def fold_to_cbet_rate(self) -> float:
        """C-bet에 폴드하는 비율"""
        if self.faced_cbet == 0:
            return 0.5
        return self.folded_to_cbet / self.faced_cbet

    @property
    def three_bet_rate(self) -> float:
        """3bet 빈도"""
        if self.three_bet_opportunities == 0:
            return 0.1
        return self.three_bets / self.three_bet_opportunities

    @property
    def wtsd(self) -> float:
        """Went To Showdown %"""
        if self.hands_voluntarily == 0:
            return 0.3
        return self.showdowns / self.hands_voluntarily

    @property
    def recent_vpip(self) -> float:
        """최근 10핸드 VPIP (전략 전환 감지)"""
        recent = self.recent_actions[-10:]
        if len(recent) < 5:
            return self.vpip
        voluntary = sum(1 for a in recent if a in ("call", "raise", "allin"))
        return voluntary / len(recent)

    @property
    def player_type(self) -> PlayerType:
        """상대 유형 자동 분류 — 전체 누적 기반 (5핸드부터)"""
        if self.hands_seen < 5:
            return PlayerType.UNKNOWN

        loose = self.vpip > 0.35
        aggressive = self.af > 1.5

        if loose and aggressive:
            return PlayerType.LAG
        if loose and not aggressive:
            return PlayerType.LAP
        if not loose and aggressive:
            return PlayerType.TAG
        return PlayerType.TAP

    @property
    def current_type(self) -> PlayerType:
        """최근 10핸드 기반 실시간 유형 — 상대 전략 전환 대응

        상대가 LAG→TAG로 전환하면 전체 누적은 여전히 LAG이지만
        current_type은 TAG로 즉시 반영됨.
        """
        recent = self.recent_actions[-10:]
        if len(recent) < 5:
            return self.player_type  # 데이터 부족 시 전체 유형 사용

        # 최근 VPIP
        voluntary = sum(1 for a in recent if a in ("call", "raise", "allin"))
        recent_vpip_val = voluntary / len(recent)
        loose = recent_vpip_val > 0.35

        # 최근 AF (raise vs call)
        raises = sum(1 for a in recent if a in ("raise", "allin"))
        calls = sum(1 for a in recent if a == "call")
        recent_af = raises / calls if calls > 0 else (3.0 if raises > 0 else 1.0)
        aggressive = recent_af > 1.5

        if loose and aggressive:
            return PlayerType.LAG
        if loose and not aggressive:
            return PlayerType.LAP
        if not loose and aggressive:
            return PlayerType.TAG
        return PlayerType.TAP

    @property
    def style_shift(self) -> bool:
        """전략 전환 감지 — 전체 유형과 최근 유형이 다르면 True

        True일 때: current_type을 우선 사용해야 함 (상대가 기어 변경함)
        """
        if self.hands_seen < 10:
            return False
        return self.player_type != self.current_type

    @property
    def effective_type(self) -> PlayerType:
        """전략에서 사용할 최종 유형 — 전환 감지 시 최근 유형 우선"""
        if self.style_shift:
            return self.current_type
        return self.player_type

    @property
    def is_tilting(self) -> bool:
        """틸트 감지 — 최근 플레이가 평소보다 극단적"""
        if self.hands_seen < 15:
            return False
        diff = abs(self.recent_vpip - self.vpip)
        return diff > 0.25  # 25%p 이상 차이

    @property
    def avg_preflop_raise_bb(self) -> float:
        """평균 프리플롭 레이즈 크기 (BB 단위). 기본 3BB."""
        s = self.preflop_raise_bb_samples
        return sum(s) / len(s) if s else 3.0

    @property
    def avg_postflop_bet_pot_ratio(self) -> float:
        """평균 포스트플롭 벳 크기 (pot 대비 비율). 기본 0.66."""
        s = self.postflop_bet_pot_samples
        return sum(s) / len(s) if s else 0.66

    def bet_size_features(self) -> dict[str, float]:
        """RL state용 베팅 크기 피처 묶음."""
        pre = self.preflop_raise_bb_samples
        post = self.postflop_bet_pot_samples
        return {
            "avg_pre_raise_bb": self.avg_preflop_raise_bb,
            "max_pre_raise_bb": max(pre) if pre else 3.0,
            "avg_post_bet_pct": self.avg_postflop_bet_pot_ratio,
            "overbet_rate": (sum(1 for x in post if x > 1.0) / len(post)) if post else 0.0,
            "small_bet_rate": (sum(1 for x in post if x < 0.4) / len(post)) if post else 0.0,
            "sample_count": len(pre) + len(post),
        }


@dataclass
class AdaptiveParams:
    """게임 결과 기반 적응형 파라미터 (Go 포팅)"""
    steal_freq: float = 0.70
    bluff_freq: float = 0.15
    defend_width: float = 1.0
    aggression_mod: float = 1.0


@dataclass
class GameResult:
    """게임 결과 기록"""
    game_id: str
    rank: int
    total_players: int
    timestamp: float = 0.0  # time.time()


class Profiler:
    """크로스게임 상대 프로파일 관리 + 적응형 파라미터

    Phase 9: stats를 player_name 키로 관리.
    게임이 끝나도 상대 통계가 유지되어 재대결 시 즉시 활용.
    """

    def __init__(self):
        self._stats: dict[str, PlayerStats] = {}  # name → stats (크로스게임)
        self._game_players: dict[str, list[str]] = {}  # game_id → [names] (게임별 참가자 추적)
        self._results: list[GameResult] = []  # 최근 50게임 결과
        self._adaptive_cache: AdaptiveParams | None = None

    def get_stats(self, game_id: str, name: str) -> PlayerStats:
        """상대 통계 조회 (game_id는 호환성 유지용 — 무시됨)"""
        return self._stats.get(name, PlayerStats(name=name))

    def get_all(self, game_id: str) -> dict[str, PlayerStats]:
        """게임 참가자 전체 통계"""
        names = self._game_players.get(game_id, [])
        return {n: self._stats.get(n, PlayerStats(name=n)) for n in names}

    def get_table_vpip(self, player_names: list[str]) -> float:
        """테이블 평균 VPIP (5핸드 이상 관찰된 플레이어만)"""
        vpips = []
        for name in player_names:
            stats = self._stats.get(name)
            if stats and stats.hands_seen >= 5:
                vpips.append(stats.vpip)
        return sum(vpips) / len(vpips) if vpips else 0.5

    def record_game_result(self, game_id: str, rank: int, total_players: int):
        """게임 종료 시 결과 기록 (적응형 파라미터용)"""
        import time
        self._results.append(GameResult(game_id, rank, total_players, time.time()))
        if len(self._results) > 50:
            self._results = self._results[-50:]
        self._adaptive_cache = None  # 캐시 무효화

    def get_adaptive_params(self) -> AdaptiveParams:
        """최근 성적 기반 적응 파라미터 (Go 포팅)"""
        if self._adaptive_cache is not None:
            return self._adaptive_cache

        params = AdaptiveParams()
        n = len(self._results)
        if n < 5:
            return params

        # 최근 10게임 평균 순위 (낮을수록 좋음)
        count = min(10, n)
        recent = self._results[-count:]
        avg_rank = sum(r.rank / r.total_players for r in recent) / count
        avg_win_rate = sum(1 for r in recent if r.rank == 1) / count

        if avg_rank < 0.35:
            # 잘 되고 있음 → 약간 더 공격적
            params.steal_freq = 0.75
            params.bluff_freq = 0.18
            params.aggression_mod = 1.1
        elif avg_rank > 0.55:
            # 성적 부진 → 보수적 전환
            params.steal_freq = 0.55
            params.bluff_freq = 0.10
            params.defend_width = 0.85
            params.aggression_mod = 0.85

        if avg_win_rate > 0.3:
            params.aggression_mod = 1.15

        self._adaptive_cache = params
        return params

    def init_game(self, game_id: str, players: list[str]):
        """게임 시작 시 참가자 등록 (기존 통계는 보존)"""
        self._game_players[game_id] = players
        for name in players:
            if name not in self._stats:
                self._stats[name] = PlayerStats(name=name)

    def remove_game(self, game_id: str):
        """게임 참가자 추적만 제거 (통계는 보존 — 크로스게임)"""
        self._game_players.pop(game_id, None)

    def update_from_action(self, req: ActionRequest):
        """action 요청의 action_history에서 상대 지표 업데이트"""
        # 모든 플레이어 등록 (크로스게임)
        for p in req.players:
            if p.name not in self._stats:
                self._stats[p.name] = PlayerStats(name=p.name)

        # action_history 분석
        preflop_raiser = None
        for record in req.action_history:
            if record.player not in self._stats:
                self._stats[record.player] = PlayerStats(name=record.player)
            stats = self._stats[record.player]

            if record.phase == "preflop":
                if record.action in ("raise", "allin"):
                    preflop_raiser = record.player
                    # 3bet 판별: 이미 레이즈가 있었는지
                    prior_raises = sum(
                        1 for r in req.action_history
                        if r.phase == "preflop" and r.action == "raise"
                        and r.player != record.player
                    )
                    if prior_raises > 0:
                        stats.three_bets += 1

            if record.phase == "flop" and record.action in ("raise",):
                # C-bet 판별
                if record.player == preflop_raiser:
                    stats.cbet_made += 1

    def update_hand_end(self, game_id: str, action_history: list,
                        showdown_names: list[str],
                        big_blind: int = 2, final_pot: int = 0):
        """핸드 종료 시 통계 업데이트 (hand_result에서 호출)

        action_history: list[dict] — {"phase", "player", "action", "amount"}
        big_blind: BB 단위 환산용
        final_pot: 핸드 최종 팟 (pot 환산 fallback)
        """
        if not action_history:
            return

        def _get(record, key):
            """ActionRecord 또는 dict 모두 지원"""
            if isinstance(record, dict):
                return record.get(key)
            return getattr(record, key, None)

        # pot 누적 추적 (각 액션 시점 pot)
        running_pot = big_blind + (big_blind // 2)  # SB + BB 기본
        action_pot_map: list[int] = []  # 각 record 시점 pot
        for r in action_history:
            action_pot_map.append(running_pot)
            amt = _get(r, "amount") or 0
            if amt > 0:
                running_pot += amt

        # 각 플레이어별 이번 핸드 행동 집계
        player_actions: dict[str, list[str]] = {}

        for record in action_history:
            player = _get(record, "player")
            action = _get(record, "action")
            player_actions.setdefault(player, []).append(action)

        # 베팅 크기 샘플 기록
        for idx, record in enumerate(action_history):
            player = _get(record, "player")
            phase = _get(record, "phase")
            action = _get(record, "action")
            amount = _get(record, "amount") or 0
            if player not in self._stats or amount <= 0:
                continue
            stats = self._stats[player]
            if phase == "preflop" and action in ("raise", "allin") and big_blind > 0:
                stats.preflop_raise_bb_samples.append(amount / big_blind)
                if len(stats.preflop_raise_bb_samples) > 30:
                    stats.preflop_raise_bb_samples = stats.preflop_raise_bb_samples[-30:]
            elif phase in ("flop", "turn", "river") and action in ("raise", "allin"):
                pot_at_bet = action_pot_map[idx] if idx < len(action_pot_map) else 0
                if pot_at_bet > 0:
                    stats.postflop_bet_pot_samples.append(amount / pot_at_bet)
                    if len(stats.postflop_bet_pot_samples) > 30:
                        stats.postflop_bet_pot_samples = stats.postflop_bet_pot_samples[-30:]
                stats.postflop_bet_amount_samples.append(amount)
                if len(stats.postflop_bet_amount_samples) > 30:
                    stats.postflop_bet_amount_samples = stats.postflop_bet_amount_samples[-30:]

        for name, actions in player_actions.items():
            stats = self._stats.get(name)
            if not stats:
                continue

            stats.hands_seen += 1

            # 자발적 참여 (프리플롭에서 call/raise/allin)
            preflop_acts = [
                _get(r, "action") for r in action_history
                if _get(r, "player") == name and _get(r, "phase") == "preflop"
            ]
            if any(a in ("call", "raise", "allin") for a in preflop_acts):
                stats.hands_voluntarily += 1

            if any(a == "raise" for a in preflop_acts):
                stats.preflop_raises += 1

            # 포스트플롭 집계
            postflop_acts = [
                _get(r, "action") for r in action_history
                if _get(r, "player") == name and _get(r, "phase") != "preflop"
            ]
            for a in postflop_acts:
                if a == "raise":
                    stats.postflop_bets += 1
                elif a == "call":
                    stats.postflop_calls += 1
                elif a == "check":
                    stats.postflop_checks += 1

            if "fold" in actions:
                stats.folds += 1
            if "allin" in actions:
                stats.allins += 1
            if name in showdown_names:
                stats.showdowns += 1

            main_action = actions[-1] if actions else "fold"
            stats.recent_actions.append(main_action)
            if len(stats.recent_actions) > 20:
                stats.recent_actions = stats.recent_actions[-20:]
