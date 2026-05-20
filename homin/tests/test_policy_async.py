from __future__ import annotations

from dataclasses import dataclass

import pytest

from holdem.decide.ev import EVCandidate
from holdem.decide.policy import (
    build_default_deps,
    candidate_to_action,
    decide_async,
    postflop_candidates,
)
from holdem.meta.llm_client import LLMResult
from holdem.meta.llm_coordinator import Coordinator
from holdem.transport.protocol import ActionRequest, PlayerState


def _req(*, phase="flop", my_cards, community, my_stack, sb, bb, to_call, min_raise,
         pot, seat="btn"):
    return ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=my_cards,
        community_cards=community,
        phase=phase,
        pot=pot,
        my_stack=my_stack,
        to_call=to_call,
        min_raise=min_raise,
        blind=[sb, bb],
        seat=seat,
        players=[
            PlayerState(name="my-bot", stack=my_stack, position=seat, status="active"),
            PlayerState(name="opp", stack=my_stack, position="bb", status="active"),
        ],
        action_history=[],
    )


def test_postflop_candidates_includes_fold_and_check_when_no_to_call():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 0
    cands = postflop_candidates(_req(
        my_cards=["As", "Kd"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=0, min_raise=2, pot=4,
    ), deps)
    actions = {c.action for c in cands}
    assert "fold" in actions
    assert "check" in actions


def test_postflop_candidates_empty_on_equity_failure(monkeypatch):
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    # equity_from_cards 가 예외를 던지게
    import holdem.decide.policy as policy_mod

    def _raise(*a, **kw):
        raise RuntimeError("mc failure")
    monkeypatch.setattr(policy_mod, "equity_from_cards", _raise)
    cands = postflop_candidates(_req(
        my_cards=["As", "Ac"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=4, min_raise=8, pot=10,
    ), deps)
    assert cands == []


def test_candidate_to_action_respects_min_raise():
    cand = EVCandidate(action="raise", amount=3, chip_ev=1.0, log_util=0.5, variance=0.0)
    req = _req(
        my_cards=["As", "Ac"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=4, min_raise=8, pot=10,
    )
    act = candidate_to_action(cand, req, my_bet=0)
    assert act.action == "raise"
    assert act.amount == 8   # bumped to min_raise


def test_candidate_to_action_caps_at_stack():
    cand = EVCandidate(action="raise", amount=1000, chip_ev=1.0, log_util=0.5, variance=0.0)
    req = _req(
        my_cards=["As", "Ac"], community=["2h", "7c", "2d"],
        my_stack=50, sb=1, bb=2, to_call=4, min_raise=8, pot=10,
    )
    act = candidate_to_action(cand, req, my_bet=10)
    assert act.action == "raise"
    assert act.amount == 60   # my_stack + my_bet


@dataclass
class _MockClient:
    result: LLMResult

    async def complete(self, messages, *, role="default", system=None):
        return self.result


@pytest.mark.asyncio
async def test_decide_async_falls_back_to_sync_without_coordinator():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 1
    req = _req(
        my_cards=["As", "Ac"], community=["2h", "7c", "2d"],
        my_stack=100, sb=1, bb=2, to_call=4, min_raise=8, pot=10,
    )
    action = await decide_async(req, "my-bot", deps, coordinator=None)
    assert action.action in ("call", "raise", "allin")


@pytest.mark.asyncio
async def test_decide_async_preflop_ignores_coordinator():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    coord = Coordinator(client=None, gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []})
    req = _req(
        phase="preflop",
        my_cards=["As", "Ac"], community=[],
        my_stack=200, sb=1, bb=2, to_call=0, min_raise=4, pot=3,
    )
    action = await decide_async(req, "my-bot", deps, coordinator=coord)
    assert action.action == "raise"


@pytest.mark.asyncio
async def test_decide_async_coordinator_with_llm_fallback():
    deps = build_default_deps()
    deps.use_ev_tree_postflop = True
    deps.ev_seed = 0
    # gate 조건에 항상 True 로 걸리도록
    mock = _MockClient(LLMResult(ok=True, text="fold", model="m1", latency_s=0.01))
    coord = Coordinator(client=mock, gate={"default": ["top1_top2_ev_within_5pct"], "standard": [], "critical": []})  # type: ignore[arg-type]
    req = _req(
        my_cards=["7d", "2c"], community=["Jh", "Qh", "Kh"],
        my_stack=100, sb=1, bb=2, to_call=5, min_raise=10, pot=6,
    )
    action = await decide_async(req, "my-bot", deps, coordinator=coord)
    # LLM 이 fold 를 지정하거나, 통계 경로로 수렴 — 유효한 서버 액션이어야 함
    assert action.action in ("fold", "call", "check", "raise", "allin")
