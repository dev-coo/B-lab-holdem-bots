from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class SPRAnalysis:
    """Stack-to-pot ratio and commitment guidance."""

    spr: float
    category: str
    commitment_threshold: float
    prefer_push_fold: bool
    draw_call_margin: float


def calculate_spr(stack: int, pot: int) -> float:
    """Calculate Stack-to-Pot Ratio."""

    if pot <= 0:
        return float("inf")
    return max(0.0, stack / pot)


def analyze_spr(stack: int, pot: int) -> SPRAnalysis:
    """Classify SPR for postflop commitment decisions.

    Low SPR favors decisive all-in/fold lines and discourages speculative draw
    calls. High SPR keeps commitment thresholds stricter.
    """

    ratio = calculate_spr(stack, pot)
    if ratio <= 3.0:
        return SPRAnalysis(
            spr=ratio,
            category="low",
            commitment_threshold=0.45,
            prefer_push_fold=True,
            draw_call_margin=0.10,
        )
    if ratio <= 8.0:
        return SPRAnalysis(
            spr=ratio,
            category="medium",
            commitment_threshold=0.58,
            prefer_push_fold=False,
            draw_call_margin=0.00,
        )
    return SPRAnalysis(
        spr=ratio,
        category="high",
        commitment_threshold=0.68,
        prefer_push_fold=False,
        draw_call_margin=-0.03,
    )
