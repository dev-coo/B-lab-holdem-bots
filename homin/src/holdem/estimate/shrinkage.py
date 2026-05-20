"""Empirical Bayes shrinkage — 3-layer BetaCounter blend.

근거: plan H.1 (Layer 0 math + Layer 1 population + Layer 2 class + personal posterior).

공식:
    α_eff = α_personal + (τ_class / ESS_class) · α_class
                        + (τ_pop   / ESS_pop  ) · α_pop
    β_eff 동일.

의도:
    - class/pop prior 를 τ-효과 샘플 크기로 rescale → 개인 관측 n 이 커질수록
      상대적 영향력이 자연 감소.
    - 관측 초기(n=0) 에는 (τ_class + τ_pop) ≈ 48 관측이 주입되어 균형잡힌 posterior.
    - n ≈ 50~100 에 이르면 personal 이 priors 를 압도.

주의:
    - 클래스 prior 는 soft class membership 으로 가중 혼합해서 전달해야 한다.
    - class_prior, pop_prior 의 ESS 는 yaml 에서 이미 정규화(≈ 100) 되어 있음.
"""
from __future__ import annotations

from ..state.player_profile import BetaCounter
from .priors import ShrinkageHyperparams


def shrink(
    personal: BetaCounter,
    class_prior: BetaCounter,
    pop_prior: BetaCounter,
    hp: ShrinkageHyperparams,
) -> BetaCounter:
    """3-layer Empirical Bayes blend → 유효 BetaCounter."""
    class_scaled = class_prior.scaled(hp.tau_class)
    pop_scaled = pop_prior.scaled(hp.tau_population)
    return BetaCounter(
        alpha=personal.alpha + class_scaled.alpha + pop_scaled.alpha,
        beta=personal.beta + class_scaled.beta + pop_scaled.beta,
    )


def soft_class_prior(
    class_priors: dict[str, BetaCounter],
    class_weights: dict[str, float],
) -> BetaCounter:
    """soft assignment 의 클래스 확률 가중합 → 단일 BetaCounter.

    class_weights: {cls: prob, ...} — 합 1.0 이어야 (정규화는 호출자 책임).
    """
    alpha = 0.0
    beta = 0.0
    for cls, weight in class_weights.items():
        if weight <= 0:
            continue
        bc = class_priors.get(cls)
        if bc is None:
            continue
        alpha += bc.alpha * weight
        beta += bc.beta * weight
    return BetaCounter(alpha=alpha, beta=beta)


def effective_rate(
    personal: BetaCounter,
    class_prior: BetaCounter,
    pop_prior: BetaCounter,
    hp: ShrinkageHyperparams,
    default: float = 0.5,
) -> float:
    """shrink() 적용한 posterior 의 rate (α/(α+β))."""
    return shrink(personal, class_prior, pop_prior, hp).rate(default=default)
