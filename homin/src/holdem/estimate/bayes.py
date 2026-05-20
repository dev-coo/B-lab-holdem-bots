"""Dirichlet 반응 모델 — 상대의 {fold/call/raise} 확률을 상호배타 joint 로.

근거: 평가 C2 — Beta 3개 독립 추출은 `f+c+r = 1` 제약 위반.
      Dirichlet 로 통일하여 Bayesian 일관성 복구.

사용:
    resp = DirichletResponse(alpha_fold=3, alpha_call=2, alpha_raise=1)
    sample = resp.sample()         # {"fold": 0.52, "call": 0.31, "raise": 0.17}
    mean = resp.mean()
    resp.observe("fold")           # alpha_fold += 1
"""
from __future__ import annotations

import random
from dataclasses import dataclass

ACTIONS = ("fold", "call", "raise")


@dataclass
class DirichletResponse:
    alpha_fold: float = 1.0
    alpha_call: float = 1.0
    alpha_raise: float = 1.0

    def total(self) -> float:
        return self.alpha_fold + self.alpha_call + self.alpha_raise

    def mean(self) -> dict[str, float]:
        t = self.total()
        if t <= 0:
            return {a: 1.0 / 3.0 for a in ACTIONS}
        return {
            "fold": self.alpha_fold / t,
            "call": self.alpha_call / t,
            "raise": self.alpha_raise / t,
        }

    def sample(self, rng: random.Random | None = None) -> dict[str, float]:
        """Dirichlet sample via Gamma → normalize.

        한 번의 호출에서 반환되는 세 값은 합 1.0 (Bayesian 일관성).
        """
        if rng is None:
            rng = random.Random()
        alphas = [
            max(1e-6, self.alpha_fold),
            max(1e-6, self.alpha_call),
            max(1e-6, self.alpha_raise),
        ]
        gammas = [rng.gammavariate(a, 1.0) for a in alphas]
        total = sum(gammas)
        if total <= 0:
            return {a: 1.0 / 3.0 for a in ACTIONS}
        return {a: g / total for a, g in zip(ACTIONS, gammas)}

    def observe(self, action: str, weight: float = 1.0) -> None:
        if action == "fold":
            self.alpha_fold += weight
        elif action == "call":
            self.alpha_call += weight
        elif action == "raise" or action == "allin":
            self.alpha_raise += weight
        # check/unknown 은 무시

    def decay(self, factor: float) -> None:
        self.alpha_fold *= factor
        self.alpha_call *= factor
        self.alpha_raise *= factor

    def copy(self) -> "DirichletResponse":
        return DirichletResponse(
            alpha_fold=self.alpha_fold,
            alpha_call=self.alpha_call,
            alpha_raise=self.alpha_raise,
        )

    def merge(self, other: "DirichletResponse", weight: float = 1.0) -> None:
        self.alpha_fold += other.alpha_fold * weight
        self.alpha_call += other.alpha_call * weight
        self.alpha_raise += other.alpha_raise * weight

    @property
    def n_obs(self) -> float:
        # Dirichlet(1,1,1) baseline 을 차감한 관측수
        base = self.alpha_fold + self.alpha_call + self.alpha_raise - 3.0
        return max(0.0, base)


def thompson_action_rates(
    response: DirichletResponse,
    rng: random.Random | None = None,
) -> dict[str, float]:
    """한 decision 호출 내에서 단일 sample → 모든 후보 EV 에 일관 적용.

    plan 부록 B — '같은 의사결정 호출 내에서는 하나의 샘플 경로로 일관 사용'.
    """
    return response.sample(rng=rng)
