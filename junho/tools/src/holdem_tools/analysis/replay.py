"""결정 리플레이 & 파라미터 튜닝 유틸.

과거 `.debug/room_*.jsonl` 의 inbound `action_request` 를 그대로 파싱해서
`BalancedStrategy(cfg).decide(req)` 를 돌려보고, 원본 액션과 비교한다.

쓰임새:
- 튜닝: 여러 StrategyConfig 중 어느 쪽이 더 많이 원본 결정을 유지/바꾸는지
- A/B: 두 config 의 액션 diff 를 카운트
- 그리드 서치: coordinate-descent 로 fixture score 최대화
- Fixture: `tests/fixtures/decisions/*.json` 형식 (user 가 100개 준비)
"""

from __future__ import annotations

import copy
import itertools
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from holdem_core.models.actions import Action
from holdem_core.models.events import ActionRequest, IncomingAdapter

# replay 는 BalancedStrategy 전용이므로 봇 패키지 import (tools → bot 의존성).
# 더 많은 봇을 리플레이 하려면 factory 추상화 필요 — v4 에서.
from holdem_main_bot.strategy import BalancedStrategy, StrategyConfig


# ─── Case / Trace 구조 ──────────────────────────────────────────────────────


@dataclass
class ReplayCase:
    """한 번의 결정 리플레이 단위. 원본 + fixture 양쪽에서 사용."""
    request: ActionRequest
    original_action: str | None = None       # .debug 복원 시 봇이 실제 보낸 액션
    original_amount: int | None = None
    expected_action: str | None = None       # fixture 에서 옴
    category: str | None = None              # fixture 에서 옴
    source: str = "debug"                    # "debug" or "fixture"
    room_id: int | None = None
    hand_number: int | None = None
    equity_truth: float | None = None        # fixture 용 참값 (선택)


@dataclass
class DecisionOutcome:
    """한 case 에 하나의 config 를 돌린 결과."""
    case: ReplayCase
    action: str
    amount: int | None
    meta: dict[str, Any]


@dataclass
class ConfigScore:
    """한 StrategyConfig 로 전체 case 를 돌린 집계."""
    cfg_overrides: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    matches_expected: int = 0         # fixture 의 expected_action 과 일치
    matches_original: int = 0         # debug 의 원본 액션과 일치
    action_hist: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    avg_equity: float = 0.0

    @property
    def expected_match_rate(self) -> float:
        n = sum(1 for _ in [self.matches_expected] if self.total)
        return (self.matches_expected / self.total) if self.total else 0.0

    @property
    def original_match_rate(self) -> float:
        return (self.matches_original / self.total) if self.total else 0.0


# ─── 로딩 ───────────────────────────────────────────────────────────────────


def iter_action_requests_from_debug(path: Path) -> Iterator[ReplayCase]:
    """`.debug/room_X.jsonl` 에서 action_request 이벤트와 바로 다음 outbound action 을
    짝지어 ReplayCase 로 yield 한다.

    파일은 append-only 이고, dispatch 는 동기적이므로 action_request 직후 오는
    outbound action 이 봇이 그 요청에 대한 결정이라고 가정한다.
    """
    if not path.exists():
        return
    pending_req: ActionRequest | None = None
    pending_room: int | None = None
    pending_hand: int | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "_run_started" in obj:
            continue
        direction = obj.get("dir")
        if direction == "in" and obj.get("type") == "action_request":
            ev = obj.get("event") or {}
            try:
                req = IncomingAdapter.validate_python(ev)
            except Exception:  # noqa: BLE001
                req = None
            if isinstance(req, ActionRequest):
                pending_req = req
                pending_room = obj.get("room_id")
                pending_hand = ev.get("hand_number") if isinstance(ev, dict) else None
        elif direction == "out" and obj.get("kind") == "action" and pending_req is not None:
            payload = obj.get("payload") or {}
            action_str = payload.get("action") if isinstance(payload, dict) else None
            amount_val = payload.get("amount") if isinstance(payload, dict) else None
            yield ReplayCase(
                request=pending_req,
                original_action=action_str,
                original_amount=amount_val,
                source="debug",
                room_id=pending_room,
                hand_number=pending_hand,
            )
            pending_req = None


def load_debug_cases(rooms_glob: str | Path = ".debug/room_*.jsonl") -> list[ReplayCase]:
    """모든 룸 로그에서 ReplayCase 모음."""
    cases: list[ReplayCase] = []
    root = Path(".")
    for p in sorted(root.glob(str(rooms_glob))):
        cases.extend(list(iter_action_requests_from_debug(p)))
    return cases


def load_fixture_cases(fixtures_glob: str | Path) -> list[ReplayCase]:
    """`tests/fixtures/decisions/*.json` 같은 사용자 제공 테스트케이스를 ReplayCase 로.

    Fixture 포맷:
        {
          "request": {<ActionRequest dict>},
          "expected_action": "raise",
          "category": "preflop_open",
          "equity_truth": 0.62   // optional
        }
    """
    cases: list[ReplayCase] = []
    root = Path(".")
    paths = sorted(root.glob(str(fixtures_glob)))
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            req_data = item.get("request")
            if not isinstance(req_data, dict):
                continue
            try:
                req = IncomingAdapter.validate_python(req_data)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(req, ActionRequest):
                continue
            cases.append(
                ReplayCase(
                    request=req,
                    expected_action=item.get("expected_action"),
                    category=item.get("category"),
                    source="fixture",
                    equity_truth=item.get("equity_truth"),
                    hand_number=req.hand_number,
                    room_id=req.room_id,
                )
            )
    return cases


# ─── 리플레이 실행 ──────────────────────────────────────────────────────────


def replay_case(case: ReplayCase, cfg: StrategyConfig, *, seed: int | None = None) -> DecisionOutcome:
    """단일 case 를 주어진 cfg 로 돌려 DecisionOutcome 반환.

    `seed` 는 equity MC 의 결정성을 위해 `random.seed` 를 설정. 완전 결정은 아니지만
    반복 비교에서 표준편차를 줄인다.
    """
    if seed is not None:
        random.seed(seed)
    strat = BalancedStrategy(cfg=cfg)
    try:
        action = strat.decide(case.request)
    except Exception as e:  # noqa: BLE001
        # 예외도 "fold" 로 처리 — 원본 client._dispatch 와 동일 동작.
        action = Action(room_id=case.request.room_id, action="fold", meta={"reason": f"exception:{e!r}"})
    return DecisionOutcome(
        case=case,
        action=action.action,
        amount=action.amount,
        meta=action.meta or {},
    )


def score_config(
    cases: list[ReplayCase],
    cfg: StrategyConfig,
    *,
    seed: int = 0,
    overrides: dict[str, Any] | None = None,
) -> ConfigScore:
    """여러 case 를 한 cfg 로 돌려 집계."""
    score = ConfigScore(cfg_overrides=overrides or {})
    eq_sum = 0.0
    eq_n = 0
    for c in cases:
        out = replay_case(c, cfg, seed=seed)
        score.total += 1
        score.action_hist[out.action] = score.action_hist.get(out.action, 0) + 1
        if c.expected_action and out.action == c.expected_action:
            score.matches_expected += 1
        if c.original_action and out.action == c.original_action:
            score.matches_original += 1
        if c.category:
            b = score.by_category.setdefault(c.category, {"total": 0, "match": 0})
            b["total"] += 1
            if c.expected_action and out.action == c.expected_action:
                b["match"] += 1
        eq = out.meta.get("equity")
        if isinstance(eq, (int, float)):
            eq_sum += float(eq)
            eq_n += 1
    score.avg_equity = (eq_sum / eq_n) if eq_n else 0.0
    return score


# ─── A/B / 그리드 서치 ──────────────────────────────────────────────────────


def diff_configs(
    cases: list[ReplayCase],
    cfg_a: StrategyConfig,
    cfg_b: StrategyConfig,
    *,
    seed: int = 0,
) -> dict[str, Any]:
    """두 cfg 의 case 별 액션 차이를 집계."""
    changes: dict[tuple[str, str], int] = {}
    a_wins = 0
    b_wins = 0
    ties = 0
    diffs: list[dict[str, Any]] = []
    for c in cases:
        oa = replay_case(c, cfg_a, seed=seed)
        ob = replay_case(c, cfg_b, seed=seed)
        k = (oa.action, ob.action)
        changes[k] = changes.get(k, 0) + 1
        if c.expected_action:
            a_ok = oa.action == c.expected_action
            b_ok = ob.action == c.expected_action
            if a_ok and not b_ok:
                a_wins += 1
            elif b_ok and not a_ok:
                b_wins += 1
            else:
                ties += 1
        if oa.action != ob.action:
            diffs.append(
                {
                    "hand": c.hand_number,
                    "room": c.room_id,
                    "phase": c.request.phase,
                    "your_cards": list(c.request.your_cards),
                    "to_call": c.request.to_call,
                    "cfg_a_action": (oa.action, oa.amount),
                    "cfg_b_action": (ob.action, ob.amount),
                }
            )
    return {
        "total": len(cases),
        "action_matrix": {f"{k[0]}->{k[1]}": v for k, v in changes.items()},
        "a_wins_vs_expected": a_wins,
        "b_wins_vs_expected": b_wins,
        "ties_vs_expected": ties,
        "first_diffs": diffs[:20],
    }


def _apply_overrides(base: StrategyConfig, overrides: dict[str, Any]) -> StrategyConfig:
    data = asdict(base)
    data.update(overrides)
    return StrategyConfig(**data)


def grid_search(
    cases: list[ReplayCase],
    base_cfg: StrategyConfig,
    param_grid: dict[str, list[Any]],
    *,
    scorer: Callable[[ConfigScore], float] | None = None,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """데카르트곱 그리드. 반환은 점수 내림차순.

    `scorer(score)` 기본: expected_match_rate, 없으면 original_match_rate.
    """
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    if scorer is None:
        def scorer(s: ConfigScore) -> float:  # noqa: E306
            return s.expected_match_rate if any(c.expected_action for c in cases) else s.original_match_rate
    results: list[dict[str, Any]] = []
    for combo in combos:
        overrides = dict(zip(keys, combo))
        cfg = _apply_overrides(base_cfg, overrides)
        s = score_config(cases, cfg, seed=seed, overrides=overrides)
        results.append(
            {
                "overrides": overrides,
                "score": scorer(s),
                "total": s.total,
                "matches_expected": s.matches_expected,
                "matches_original": s.matches_original,
                "action_hist": dict(s.action_hist),
                "by_category": dict(s.by_category),
                "avg_equity": s.avg_equity,
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def coordinate_descent(
    cases: list[ReplayCase],
    base_cfg: StrategyConfig,
    axes: dict[str, list[Any]],
    *,
    scorer: Callable[[ConfigScore], float] | None = None,
    max_iters: int = 3,
    seed: int = 0,
) -> tuple[StrategyConfig, list[dict[str, Any]]]:
    """한 축씩 최적값으로 고정해가는 그리드 서치.

    데카르트곱은 파라미터 6개에 값 4개씩이면 4096 — 너무 크므로 축별 순회.
    """
    if scorer is None:
        def scorer(s: ConfigScore) -> float:  # noqa: E306
            return s.expected_match_rate if any(c.expected_action for c in cases) else s.original_match_rate
    cfg = copy.deepcopy(base_cfg)
    trace: list[dict[str, Any]] = []
    for _ in range(max_iters):
        changed = False
        for axis, values in axes.items():
            best_val = getattr(cfg, axis)
            best_score = scorer(score_config(cases, cfg, seed=seed))
            for v in values:
                trial = _apply_overrides(cfg, {axis: v})
                s = scorer(score_config(cases, trial, seed=seed))
                if s > best_score:
                    best_score = s
                    best_val = v
                    changed = True
            if getattr(cfg, axis) != best_val:
                cfg = _apply_overrides(cfg, {axis: best_val})
            trace.append({"axis": axis, "value": best_val, "score": best_score})
        if not changed:
            break
    return cfg, trace


# ─── 편의 함수 (기존 API 유지) ─────────────────────────────────────────────


def rebuild_action_request(record: Any, decision_idx: int) -> ActionRequest | None:
    """Legacy API — HandRecord.my_actions[i].meta 기반 복원. 정확도 낮음.

    신규 코드는 `iter_action_requests_from_debug` 사용 권장.
    """
    if not hasattr(record, "my_actions"):
        return None
    if decision_idx < 0 or decision_idx >= len(record.my_actions):
        return None
    dec = record.my_actions[decision_idx]
    meta = dec.meta or {}
    try:
        return ActionRequest(
            type="action_request",
            room_id=record.room_id,
            hand_number=record.hand_number,
            your_cards=list(dec.your_cards or record.your_cards),
            community_cards=list(dec.community_cards or []),
            phase=dec.phase,
            pot=dec.pot,
            my_stack=dec.my_stack,
            to_call=dec.to_call,
            min_raise=int(meta.get("min_raise") or 0),
            blind=list(record.blind or [1, 2]),
            seat=dec.seat or record.your_seat,
            players=[],
            action_history=[],
            timeout_ms=10000,
        )
    except Exception:  # noqa: BLE001
        return None


def replay_decision(
    req: ActionRequest, cfg: StrategyConfig, seed: int | None = None
) -> tuple[Action, dict[str, Any]]:
    """Legacy API — 단일 req 를 cfg 로 결정. `replay_case` 대체 가능."""
    if seed is not None:
        random.seed(seed)
    strat = BalancedStrategy(cfg=cfg)
    action = strat.decide(req)
    return action, (action.meta or {})
