"""LLM Coordinator snapshot regression — 시나리오 JSONL 고정.

목적:
    - 모델/프롬프트 변경 시 회귀 감지.
    - Coordinator 파이프라인(escalation → budget → client → parse → fallback)의 연결 검증.

입력: tests/snapshots/llm_decisions.jsonl (row = {name, candidates, triggers, gate, llm, expected}).
모의 LLMClient 는 주어진 `llm` 블록을 그대로 LLMResult 로 반환.
각 시나리오는 expected.action (+ amount) 일치·used_llm 일치·reason prefix 일치 검증.

실제 LLM API 는 호출되지 않는다 (snapshot 은 결정론적).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from holdem.decide.ev import EVCandidate
from holdem.meta.llm_client import LLMResult
from holdem.meta.llm_coordinator import (
    Coordinator,
    EscalationTriggers,
)

SNAPSHOT_PATH = Path(__file__).parent / "snapshots/llm_decisions.jsonl"


@dataclass
class MockLLMClient:
    """결정론적 응답 반환 — snapshot 의 `llm` 블록 그대로."""
    text: str = ""
    ok: bool = True
    reason: str = ""
    model: str = "mock"

    async def complete(self, messages, *, role: str = "default") -> LLMResult:
        return LLMResult(
            ok=self.ok,
            text=self.text,
            reason=self.reason,
            latency_s=0.01,
            model=self.model,
        )


def _load_snapshots() -> list[dict[str, Any]]:
    if not SNAPSHOT_PATH.exists():
        pytest.skip(f"snapshot file missing: {SNAPSHOT_PATH}")
    rows: list[dict[str, Any]] = []
    with SNAPSHOT_PATH.open() as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            rows.append(json.loads(ln))
    return rows


def _mk_candidate(row: dict) -> EVCandidate:
    return EVCandidate(
        action=row["action"],
        amount=row.get("amount"),
        chip_ev=float(row.get("chip_ev", 0.0)),
        log_util=float(row.get("log_util", 0.0)),
        variance=float(row.get("variance", 0.0)),
    )


def _mk_triggers(d: dict) -> EscalationTriggers:
    return EscalationTriggers(**d)


@pytest.mark.asyncio
@pytest.mark.parametrize("snap", _load_snapshots(), ids=lambda s: s["name"])
async def test_llm_snapshot(snap):
    cands = [_mk_candidate(c) for c in snap["candidates"]]
    triggers = _mk_triggers(snap.get("triggers", {}))
    gate = snap["gate"]

    llm_cfg = snap["llm"]
    client = MockLLMClient(
        text=llm_cfg.get("text", ""),
        ok=llm_cfg.get("ok", True),
        reason=llm_cfg.get("reason", ""),
        model=llm_cfg.get("model", "mock"),
    )
    coord = Coordinator(client=client, gate=gate, budget=None)

    decision = await coord.decide(cands, triggers=triggers, context={})

    expected = snap["expected"]
    assert decision.candidate.action == expected["action"], (
        f"[{snap['name']}] action={decision.candidate.action} expected={expected['action']}"
    )
    if "amount" in expected:
        assert decision.candidate.amount == expected["amount"], (
            f"[{snap['name']}] amount={decision.candidate.amount} expected={expected['amount']}"
        )
    assert decision.used_llm == expected["used_llm"], (
        f"[{snap['name']}] used_llm={decision.used_llm} expected={expected['used_llm']}"
    )
    # reason 은 prefix 매칭 (e.g. "fallback:timeout" == "fallback:timeout")
    assert decision.reason == expected["reason"], (
        f"[{snap['name']}] reason={decision.reason!r} expected={expected['reason']!r}"
    )


def test_snapshot_file_has_coverage():
    """최소한 fallback / llm 성공 / llm 실패 시나리오를 포함해야."""
    rows = _load_snapshots()
    names = {r["name"] for r in rows}
    assert any("timeout" in n or "fallback" in n for n in names), "fallback 시나리오 누락"
    assert any("critical" in n or "standard" in n for n in names), "tier escalation 누락"
    assert any("schema_violation" in n for n in names), "schema violation 시나리오 누락"
    assert len(rows) >= 5, "스냅샷 시나리오 5개 이상 필요"
