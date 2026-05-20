"""Player profile — Beta 카운터 + AF tracker.

근거: plan H.1 (3-layer shrinkage), H.1.c (4-class typing), D3 범위.

모델:
  - Metric 별 독립 `BetaCounter(α, β)` — VPIP / PFR / 3BET / CBET / FOLD_TO_CBET / ...
  - Aggression Factor: `AggressionCounter(bets+raises, calls)` → ratio = aggr / call.
  - `observe_*` 메서드가 이벤트 스트림에서 호출.

이벤트 → metric 변환은 별도 모듈 (D3 후반). 본 모듈은 순수 데이터 구조.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BetaCounter:
    alpha: float = 0.0
    beta: float = 0.0

    def observe(self, success: bool, weight: float = 1.0) -> None:
        if success:
            self.alpha += weight
        else:
            self.beta += weight

    @property
    def n_obs(self) -> float:
        return self.alpha + self.beta

    def rate(self, default: float = 0.5) -> float:
        n = self.n_obs
        if n <= 0:
            return default
        return self.alpha / n

    def decay(self, factor: float) -> None:
        """지수 감쇠 — metagame drift 완화 용."""
        self.alpha *= factor
        self.beta *= factor

    def merge(self, other: "BetaCounter", weight: float = 1.0) -> None:
        self.alpha += other.alpha * weight
        self.beta += other.beta * weight

    def scaled(self, target_ess: float) -> "BetaCounter":
        """ESS 를 target 으로 rescale. 비율 유지."""
        n = self.n_obs
        if n <= 0 or target_ess <= 0:
            return BetaCounter()
        factor = target_ess / n
        return BetaCounter(alpha=self.alpha * factor, beta=self.beta * factor)

    def copy(self) -> "BetaCounter":
        return BetaCounter(alpha=self.alpha, beta=self.beta)


@dataclass
class AggressionCounter:
    """Aggression Factor = (bets + raises) / calls.

    Poker 통상 정의. n_opportunity 별로 별도 가중치 없음.
    """
    aggressive: float = 0.0    # bet + raise
    passive: float = 0.0       # call (fold/check 제외)

    def observe_aggressive(self, weight: float = 1.0) -> None:
        self.aggressive += weight

    def observe_passive(self, weight: float = 1.0) -> None:
        self.passive += weight

    @property
    def n_obs(self) -> float:
        return self.aggressive + self.passive

    # Laplace 보정 & 상한 — passive 표본 희소 시 AF 폭주 방지.
    # 근거: bootstrap r4 §5 — LAG AF=208 같은 비정상치가 class_typer/bluff_factor 왜곡.
    _MAX_AF: float = 10.0
    _LAPLACE_EPS: float = 1.0

    def factor(self, default: float = 1.0) -> float:
        if self.n_obs <= 0:
            return default
        if self.passive < 1.0:
            # passive 가 1 미만(0 또는 fractional decay 잔여) 이면 Laplace 보정.
            af = (self.aggressive + self._LAPLACE_EPS) / (self.passive + self._LAPLACE_EPS)
        else:
            af = self.aggressive / self.passive
        return min(af, self._MAX_AF)

    def decay(self, factor: float) -> None:
        self.aggressive *= factor
        self.passive *= factor


METRIC_KEYS = (
    "VPIP", "PFR", "THREE_BET", "FOLD_TO_THREE_BET",
    "CBET", "FOLD_TO_CBET", "BARREL_TURN", "BARREL_RIVER",
    "BLUFF_AT_SHOWDOWN", "CHECK_RAISE",
)


@dataclass
class PlayerProfile:
    name: str
    hands_seen: int = 0
    metrics: dict[str, BetaCounter] = field(
        default_factory=lambda: {k: BetaCounter() for k in METRIC_KEYS}
    )
    aggression: AggressionCounter = field(default_factory=AggressionCounter)

    def get(self, metric: str) -> BetaCounter:
        return self.metrics.setdefault(metric, BetaCounter())

    def vpip(self) -> float:
        return self.get("VPIP").rate(default=0.0)

    def pfr(self) -> float:
        return self.get("PFR").rate(default=0.0)

    def af(self) -> float:
        return self.aggression.factor(default=1.0)

    def n_total_actions(self) -> float:
        # metric 중 가장 많이 관측된 값 — n_effective 계산에 대용.
        return max((c.n_obs for c in self.metrics.values()), default=0.0)
