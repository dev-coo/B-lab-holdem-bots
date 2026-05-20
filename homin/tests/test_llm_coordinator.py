from __future__ import annotations

from dataclasses import dataclass

import pytest

from holdem.decide.ev import EVCandidate
from holdem.meta.llm_client import LLMResult
from holdem.meta.llm_coordinator import (
    Coordinator,
    EscalationTriggers,
    build_prompt,
    parse_llm_action,
    pick_tier,
)


def _cand(action, amount, chip_ev, log_util, variance=0.0) -> EVCandidate:
    return EVCandidate(action=action, amount=amount, chip_ev=chip_ev,
                       log_util=log_util, variance=variance)


def test_pick_tier_none_when_clear_winner():
    ranked = [
        _cand("raise", 20, 5.0, 2.0),
        _cand("call", None, 1.0, 0.5),
    ]
    gate = {"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []}
    assert pick_tier(ranked, EscalationTriggers(), gate) == "none"


def test_pick_tier_default_on_close_ev():
    # log_util 차이가 rel_tol 이내
    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    gate = {"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []}
    assert pick_tier(ranked, EscalationTriggers(), gate) == "default"


def test_pick_tier_critical_on_bubble():
    ranked = [
        _cand("raise", 20, 5.0, 2.0),
        _cand("call", None, 1.0, 0.5),
    ]
    gate = {"default": [], "standard": [], "critical": ["near_bubble"]}
    assert pick_tier(ranked, EscalationTriggers(near_bubble=True), gate) == "critical"


def test_parse_fold():
    cands = [_cand("fold", None, 0, 0), _cand("call", None, 1, 1)]
    picked = parse_llm_action("fold", cands)
    assert picked is not None and picked.action == "fold"


def test_parse_raise_exact_amount():
    cands = [_cand("raise", 20, 5, 2), _cand("raise", 40, 6, 2.5)]
    picked = parse_llm_action("raise@40", cands)
    assert picked is not None and picked.amount == 40


def test_parse_raise_nearest_amount():
    cands = [_cand("raise", 20, 5, 2), _cand("raise", 40, 6, 2.5)]
    picked = parse_llm_action("raise@30", cands)
    # 20 과 40 중 30 에 동일하게 가까움 → 첫 번째 (20)
    assert picked is not None and picked.amount in (20, 40)


def test_parse_empty_returns_none():
    cands = [_cand("fold", None, 0, 0)]
    assert parse_llm_action("", cands) is None


def test_parse_gibberish_returns_none():
    cands = [_cand("fold", None, 0, 0)]
    assert parse_llm_action("I think we should consider the opponent's range...", cands) is None


def test_parse_case_insensitive():
    cands = [_cand("call", None, 1, 1)]
    picked = parse_llm_action("CALL", cands)
    assert picked is not None and picked.action == "call"


def test_build_prompt_includes_candidates():
    ranked = [_cand("fold", None, 0, 0), _cand("raise", 20, 5, 2)]
    msgs = build_prompt(ranked, {"M": 15, "phase": "flop"})
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert "fold" in content
    assert "raise@20" in content
    assert "M: 15" in content


# --- Coordinator integration (with mock client) ---


@dataclass
class _MockClient:
    result: LLMResult

    async def complete(self, messages, *, role="default", system=None):
        return self.result


@pytest.mark.asyncio
async def test_coordinator_statistical_when_no_escalation():
    coord = Coordinator(
        client=None,  # 아무 escalation 이어도 client 없으면 통계
        gate={"default": [], "standard": [], "critical": []},
    )
    ranked = [_cand("fold", None, 0, 0), _cand("call", None, 1, 1)]
    d = await coord.decide(ranked)
    assert d.used_llm is False
    assert d.candidate.action == "call"
    assert d.reason == "statistical"


@pytest.mark.asyncio
async def test_coordinator_uses_llm_on_close_ev():
    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    mock = _MockClient(LLMResult(ok=True, text="raise@20", model="m1", latency_s=0.1))
    coord = Coordinator(
        client=mock,  # type: ignore[arg-type]
        gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []},
    )
    d = await coord.decide(ranked)
    assert d.used_llm is True
    assert d.candidate.action == "raise"
    assert d.reason == "llm_default"


@pytest.mark.asyncio
async def test_coordinator_fallback_on_timeout():
    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    mock = _MockClient(LLMResult(ok=False, model="m1", reason="timeout"))
    coord = Coordinator(
        client=mock,  # type: ignore[arg-type]
        gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []},
    )
    d = await coord.decide(ranked)
    assert d.used_llm is False
    assert d.candidate.action == "raise"   # top1 (log_util 기준)
    assert d.reason.startswith("fallback:")


@pytest.mark.asyncio
async def test_coordinator_budget_gate():
    from holdem.meta.budget import BudgetLimits, BudgetTracker

    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    mock = _MockClient(LLMResult(ok=True, text="raise@20", model="m1", latency_s=0.1))
    budget = BudgetTracker(limits=BudgetLimits(per_hand=1, per_game=10, per_minute=10, per_day=100))
    budget.record_call(room_id=1, hand_number=1)   # 이미 1회 소진
    coord = Coordinator(
        client=mock,  # type: ignore[arg-type]
        gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []},
        budget=budget,
    )
    d = await coord.decide(ranked, room_id=1, hand_number=1)
    assert d.used_llm is False
    assert d.reason.startswith("fallback:budget_")


@pytest.mark.asyncio
async def test_coordinator_records_call_on_llm_use():
    from holdem.meta.budget import BudgetLimits, BudgetTracker

    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    mock = _MockClient(LLMResult(ok=True, text="raise@20", model="m1", latency_s=0.1))
    budget = BudgetTracker(limits=BudgetLimits(per_hand=1, per_game=10, per_minute=10, per_day=100))
    coord = Coordinator(
        client=mock,  # type: ignore[arg-type]
        gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []},
        budget=budget,
    )
    d = await coord.decide(ranked, room_id=1, hand_number=1)
    assert d.used_llm is True
    # 다음 호출은 예산 초과
    d2 = await coord.decide(ranked, room_id=1, hand_number=1)
    assert d2.used_llm is False
    assert d2.reason.startswith("fallback:budget_hand")


@pytest.mark.asyncio
async def test_coordinator_fallback_on_schema_violation():
    ranked = [
        _cand("raise", 20, 5.0, 2.00),
        _cand("call", None, 4.9, 1.99),
    ]
    mock = _MockClient(LLMResult(ok=True, text="I'm not sure.", model="m1"))
    coord = Coordinator(
        client=mock,  # type: ignore[arg-type]
        gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []},
    )
    d = await coord.decide(ranked)
    assert d.used_llm is False
    assert d.reason == "fallback:schema_violation"
    assert d.candidate.action == "raise"
