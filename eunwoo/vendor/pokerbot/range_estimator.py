"""상대 레인지 추정 모듈 — 액션 기반 레인지 축소

상대의 프리플롭/포스트플롭 액션 히스토리를 분석하여
현재 핸드에서 상대가 가질 수 있는 핸드 레인지(상위 %)를 추정.

사용법:
    from range_estimator import RangeEstimator
    est = RangeEstimator()
    est.update("preflop", "raise", bet_size_bb=3.0)
    est.update("flop", "bet", bet_pct_pot=0.65)
    top_pct, polarization = est.get_range()
"""

from __future__ import annotations
from profiler import PlayerType, PlayerStats


class RangeEstimator:
    """단일 핸드 내 상대 레인지 추적기.

    핸드마다 새로 생성. 액션이 진행될 때마다 update() 호출.
    최종 결과는 (top_pct, polarization) 튜플:
      - top_pct: 상대가 보유 가능한 핸드 범위 (0.0~1.0, 1.0=모든 핸드)
      - polarization: 0=리니어/머지드, 1=양극화(넛 or 에어)
    """

    def __init__(self, opp_stats: PlayerStats | None = None):
        """
        Args:
            opp_stats: 프로파일러에서 얻은 상대 통계 (있으면 VPIP/PFR로 초기 보정)
        """
        self.top_pct = 1.0
        self.polarization = 0.0
        self.opp_stats = opp_stats
        self.actions: list[tuple[str, str]] = []  # (phase, action)

        # 프로파일 기반 초기 레인지 보정
        if opp_stats and opp_stats.hands_seen >= 5:
            # VPIP = 프리플롭 참여율 → 초기 레인지 상한
            self.initial_vpip = opp_stats.vpip
        else:
            self.initial_vpip = 0.70  # 불명 → 넓게 가정

    def update(self, phase: str, action: str,
               bet_size_bb: float = 0, bet_pct_pot: float = 0):
        """액션 기반 레인지 업데이트.

        Args:
            phase: "preflop", "flop", "turn", "river"
            action: "raise", "call", "check", "bet", "allin", "3bet"
            bet_size_bb: 프리플롭 레이즈 크기 (BB 단위)
            bet_pct_pot: 포스트플롭 벳 크기 (팟 대비 비율)
        """
        self.actions.append((phase, action))

        if phase == "preflop":
            self._update_preflop(action, bet_size_bb)
        else:
            self._update_postflop(action, phase, bet_pct_pot)

    def _update_preflop(self, action: str, bet_size_bb: float):
        if action in ("raise", "bet"):
            if bet_size_bb >= 4:
                # 큰 레이즈 → 타이트
                self.top_pct = min(self.top_pct, 0.25)
            elif bet_size_bb >= 3:
                self.top_pct = min(self.top_pct, 0.35)
            else:
                self.top_pct = min(self.top_pct, self.initial_vpip * 0.8)
        elif action == "3bet":
            self.top_pct = min(self.top_pct, 0.12)
            self.polarization = max(self.polarization, 0.5)
        elif action == "call":
            # 콜 = 매우 강하지도 매우 약하지도 않은 핸드
            self.top_pct = min(self.top_pct, self.initial_vpip)
            # 프리미엄은 보통 3벳 → 상위 5% 제거
            self.polarization = max(0, self.polarization - 0.2)
        elif action == "allin":
            self.top_pct = min(self.top_pct, 0.08)
            self.polarization = max(self.polarization, 0.7)
        elif action == "check":
            # 프리플롭 체크 (BB 옵션) → 약한 핸드
            self.top_pct = min(self.top_pct, 0.85)

    def _update_postflop(self, action: str, phase: str, bet_pct_pot: float):
        if action in ("raise", "bet"):
            if bet_pct_pot > 0.75:
                # 큰 벳 → 양극화 (넛 or 블러프)
                self.top_pct *= 0.60
                self.polarization = max(self.polarization, 0.7)
            elif bet_pct_pot > 0.33:
                # 중간 벳 → 미디엄+ 핸드
                self.top_pct *= 0.70
                self.polarization = max(self.polarization, 0.3)
            else:
                # 작은 벳 → 넓은 레인지 (보호/탐색)
                self.top_pct *= 0.85
                self.polarization = max(self.polarization, 0.15)
        elif action == "call":
            # 콜 = 미디엄 (강하면 레이즈, 약하면 폴드)
            self.top_pct *= 0.75
            self.polarization = max(0, self.polarization - 0.3)
        elif action == "check":
            # 체크 = 약하거나 트랩
            # 강한 핸드 제외 (보통 벳했을 것)
            self.top_pct *= 0.90
            self.polarization = max(0, self.polarization - 0.15)
        elif action == "allin":
            self.top_pct *= 0.40
            self.polarization = max(self.polarization, 0.8)

        # 스트리트 진행에 따라 자연 축소
        if phase == "turn":
            self.top_pct *= 0.95
        elif phase == "river":
            self.top_pct *= 0.90

    def get_range(self) -> tuple[float, float]:
        """현재 추정 (top_pct, polarization) 반환"""
        return max(0.02, min(1.0, self.top_pct)), max(0.0, min(1.0, self.polarization))

    def is_likely_bluff(self, threshold: float = 0.5) -> bool:
        """상대가 블러프일 가능성이 높은지"""
        _, pol = self.get_range()
        # 양극화가 높고 레인지가 좁으면 블러프 비율 높음
        # 블러프 추정: 양극화 × (1 - 밸류 비율)
        # 단순화: polarization > threshold이면 블러프 가능성
        return pol > threshold

    def get_opponent_strength_estimate(self) -> str:
        """상대 핸드 강도 추정 (카테고리)"""
        top_pct, pol = self.get_range()
        if top_pct < 0.05:
            return "monster"  # 프리미엄 (AA, KK 급)
        elif top_pct < 0.15:
            return "strong"   # 강한 핸드
        elif top_pct < 0.35:
            return "medium"   # 중간 핸드
        elif top_pct < 0.60:
            return "wide"     # 넓은 레인지
        else:
            return "any"      # 아무 핸드나


def estimate_opponent_range(action_history: list[dict],
                            my_name: str,
                            opp_stats: PlayerStats | None = None) -> RangeEstimator:
    """액션 히스토리에서 상대 레인지 추정기 생성.

    Args:
        action_history: 핸드 액션 기록 [{"phase", "player", "action", "amount"}]
        my_name: 내 이름 (상대 액션만 필터)
        opp_stats: 상대 프로파일 통계

    Returns:
        RangeEstimator 인스턴스
    """
    est = RangeEstimator(opp_stats)
    for rec in action_history:
        if rec.get("player") == my_name:
            continue
        phase = rec.get("phase", "preflop")
        action = rec.get("action", "check")
        amount = rec.get("amount", 0)

        # bet_size_bb / bet_pct_pot은 정확한 값이 없으면 0
        est.update(phase, action)

    return est
