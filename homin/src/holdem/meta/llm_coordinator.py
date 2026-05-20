"""LLM Coordinator — escalation gate + 스키마 검증 + fallback.

근거: plan 4-3 / P5 / P6, Section M, D7.

설계:
    1. EV candidate 목록이 들어오면, top1 vs top2 의 EV 차이로 escalation 판정.
    2. 추가 트리거 (multiway, M<6, 버블) 중 하나라도 True 면 tier 승급.
    3. 적절한 모델 role (default/standard/critical) 선택 후 LLM 호출.
    4. 응답은 "fold|check|call|raise@N|allin" 중 하나로 파싱; 허용 집합 밖이면 fallback.
    5. 모든 실패 경로는 통계 argmax 로 수렴 (P6).

LLM 은 **선택자** 이지 action 생성자가 아님 (P5). 허용 action 집합은 항상 candidate 에서
나온 것들만.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..decide.ev import EVCandidate
from .llm_client import LLMClient, LLMResult

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "llm.yaml"


@dataclass(frozen=True)
class EscalationTriggers:
    multiway_3plus_borderline: bool = False
    fold_equity_uncertain: bool = False
    M_lt_6: bool = False
    near_bubble: bool = False
    stack_gt_100bb_pot_gt_50bb: bool = False


@dataclass(frozen=True)
class CoordinatorDecision:
    candidate: EVCandidate
    used_llm: bool
    reason: str            # "statistical" | "llm_default" | "llm_standard" | "llm_critical" | "fallback:*"
    latency_s: float = 0.0
    model: str = ""


def _load_gate(path: Path = _CONFIG_PATH) -> dict[str, list[str]]:
    with path.open() as f:
        data = yaml.safe_load(f)
    gate = data.get("escalation_gate") or {}
    return {
        "default": list(gate.get("default_triggers", [])),
        "standard": list(gate.get("standard_triggers", [])),
        "critical": list(gate.get("critical_triggers", [])),
    }


def _ev_close(top1: EVCandidate, top2: EVCandidate, *, rel_tol: float = 0.05) -> bool:
    """top1 vs top2 의 log_util 차이가 rel_tol 이하면 borderline."""
    scale = max(1e-9, abs(top1.log_util))
    return abs(top1.log_util - top2.log_util) <= rel_tol * scale


def _variance_high(top1: EVCandidate, threshold: float = 100.0) -> bool:
    return top1.variance > threshold


def pick_tier(
    ranked: list[EVCandidate],
    triggers: EscalationTriggers,
    gate: dict[str, list[str]] | None = None,
) -> str:
    """반환: 'none' | 'default' | 'standard' | 'critical'."""
    gate = gate or _load_gate()
    if len(ranked) < 2:
        return "none"

    flags = {
        "top1_top2_ev_within_5pct": _ev_close(ranked[0], ranked[1]),
        "variance_high": _variance_high(ranked[0]),
        "multiway_3plus_borderline": triggers.multiway_3plus_borderline,
        "fold_equity_uncertain": triggers.fold_equity_uncertain,
        "M_lt_6": triggers.M_lt_6,
        "near_bubble": triggers.near_bubble,
        "stack_gt_100bb_pot_gt_50bb": triggers.stack_gt_100bb_pot_gt_50bb,
    }

    # 높은 tier 부터 평가
    for tier in ("critical", "standard", "default"):
        for key in gate.get(tier, []):
            if flags.get(key):
                return tier
    return "none"


_ACTION_PATTERN = re.compile(
    r"\b(fold|check|call|allin)\b|raise(?:\s*@?\s*(\d+))?",
    re.IGNORECASE,
)


def parse_llm_action(text: str, candidates: list[EVCandidate]) -> EVCandidate | None:
    """LLM 응답 text → candidate 중 하나. 매칭 없으면 None.

    기대 포맷:
        - "fold" / "check" / "call" / "allin"
        - "raise 24" / "raise@24" / "raise amount=24"
    부호·대소문자 관대. 여러 매치 있으면 첫 번째.
    """
    if not text:
        return None
    m = _ACTION_PATTERN.search(text)
    if m is None:
        return None
    token = m.group(0).strip().lower()
    action = None
    amount: int | None = None
    if token.startswith("fold"):
        action = "fold"
    elif token.startswith("check"):
        action = "check"
    elif token.startswith("call"):
        action = "call"
    elif token.startswith("allin"):
        action = "allin"
    elif token.startswith("raise"):
        action = "raise"
        raw_amt = m.group(2)
        if raw_amt:
            try:
                amount = int(raw_amt)
            except ValueError:
                amount = None

    if action is None:
        return None

    # candidates 중 일치 후보 찾기
    for c in candidates:
        if c.action != action:
            continue
        if action == "raise" and amount is not None:
            if c.amount == amount:
                return c
        else:
            return c

    # raise 인데 정확한 amount 매치 없음 → 가장 가까운 amount 의 raise
    if action == "raise" and amount is not None:
        raise_cands = [c for c in candidates if c.action == "raise" and c.amount is not None]
        if raise_cands:
            return min(raise_cands, key=lambda c: abs((c.amount or 0) - amount))
    return None


def build_prompt(
    ranked: list[EVCandidate],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """messages 구성. context 는 hand/street/pot/stack/oppkeys 정보."""
    lines: list[str] = []
    lines.append("You are a poker decision selector. Choose exactly ONE action from the")
    lines.append("candidates below. Respond with only the action name (e.g. 'fold',")
    lines.append("'call', 'raise@24', 'allin'). No explanation.")
    lines.append("")
    lines.append("Context:")
    for k, v in context.items():
        lines.append(f"  - {k}: {v}")
    lines.append("")
    lines.append("Candidates (action, amount, chip_ev, log_util):")
    for c in ranked:
        amt = c.amount if c.amount is not None else "-"
        lines.append(
            f"  - {c.action}@{amt}  chip_ev={c.chip_ev:.3f}  log_util={c.log_util:.3f}"
        )
    lines.append("")
    lines.append("Pick one. Reply format: '<action>' or 'raise@<N>'.")

    return [{"role": "user", "content": "\n".join(lines)}]


class Coordinator:
    def __init__(
        self,
        client: LLMClient | None = None,
        gate: dict[str, list[str]] | None = None,
        budget=None,
    ):
        self.client = client
        self.gate = gate or _load_gate()
        self.budget = budget   # Optional BudgetTracker

    async def decide(
        self,
        ranked: list[EVCandidate],
        triggers: EscalationTriggers | None = None,
        context: dict[str, Any] | None = None,
        *,
        objective: str = "log_util",
        room_id: int | None = None,
        hand_number: int | None = None,
    ) -> CoordinatorDecision:
        if not ranked:
            raise ValueError("no candidates")

        key = (lambda c: c.chip_ev) if objective == "chip_ev" else (lambda c: c.log_util)
        ranked_sorted = sorted(ranked, key=key, reverse=True)
        top1 = ranked_sorted[0]

        triggers = triggers or EscalationTriggers()
        tier = pick_tier(ranked_sorted, triggers, self.gate)

        if tier == "none" or self.client is None:
            return CoordinatorDecision(
                candidate=top1, used_llm=False, reason="statistical",
            )

        # Budget gate — 예산 초과 시 통계 argmax.
        if self.budget is not None:
            ok, reason = self.budget.allow_call(room_id=room_id, hand_number=hand_number)
            if not ok:
                return CoordinatorDecision(
                    candidate=top1, used_llm=False, reason=f"fallback:{reason}",
                )
            self.budget.record_call(room_id=room_id, hand_number=hand_number)

        messages = build_prompt(ranked_sorted, context or {})
        result: LLMResult = await self.client.complete(messages, role=tier)
        if not result.ok:
            return CoordinatorDecision(
                candidate=top1, used_llm=False,
                reason=f"fallback:{result.reason}",
                latency_s=result.latency_s, model=result.model,
            )

        picked = parse_llm_action(result.text, ranked_sorted)
        if picked is None:
            return CoordinatorDecision(
                candidate=top1, used_llm=False,
                reason="fallback:schema_violation",
                latency_s=result.latency_s, model=result.model,
            )
        return CoordinatorDecision(
            candidate=picked, used_llm=True,
            reason=f"llm_{tier}",
            latency_s=result.latency_s, model=result.model,
        )
