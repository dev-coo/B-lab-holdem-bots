"""최상위 의사결정 — ActionRequest → Action.

Week 2 D1 한정 동작:
  - preflop 만 차트 기반 의사결정 (push_fold / hybrid).
  - postflop / mid / deep 은 전부 fold (D2 이후 확장).
  - 응답 불가 상황은 fold 로 수렴 (30s timeout 방어).

설계:
  - 순수 함수: `decide(req, bot_name) -> Action`.
  - chart / thresholds / position_map 은 테스트 시 주입 가능.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import random

from ..estimate.bayes import DirichletResponse
from ..estimate.equity import equity_from_cards
from ..math.m_ratio import compute_m
from ..math.odds import pot_odds
from ..state.game_state import GameState
from ..state.profile_store import ProfileStore, name_weight
from ..transport import protocol as p
from .cbet import cbet_response_adjustment
from .conservatism import ConservatismProfile, compute_profile
from .ev import EVCandidate, EVInputs
from .hand_notation import canonicalize_hand
from .mode_selector import ModeThresholds, select_mode
from .opening_chart import OpeningChart, default_opening_chart
from .position import PositionMap, default_map
from .push_fold_chart import PushFoldChart, default_chart
from .sizing import enumerate_candidates as ev_enumerate
from .sizing import optimize as ev_optimize
from .stage import Stage, apply_stage_to_conservatism, identify_stage

log = logging.getLogger(__name__)


@dataclass
class DecideDeps:
    chart: PushFoldChart
    position_map: PositionMap
    opening: OpeningChart
    thresholds: Optional[ModeThresholds] = None
    equity_samples: int = 800          # postflop MC 예산 (≈ 15ms)
    equity_safety_margin: float = 0.02  # pot-odds 초과분 최소 여유
    profile_store: Optional[ProfileStore] = None  # Day 18: opponent lookup (활용은 D5 에서)
    use_ev_tree_postflop: bool = True    # P1: postflop EV tree 기본 활성. --no-ev-tree 로 회귀 가능.
    ev_seed: Optional[int] = None        # 결정적 Thompson 샘플링 — 테스트용
    game_state: Optional[GameState] = None   # P5-2: starting_table_size 추출용 (5-max vs 9-max 분기)


def build_default_deps() -> DecideDeps:
    return DecideDeps(
        chart=default_chart(),
        position_map=default_map(),
        opening=default_opening_chart(),
    )


def _is_facing_raise(req: p.ActionRequest) -> bool:
    """프리플롭 기준 누군가 raise/allin 했는가."""
    for entry in req.action_history:
        if entry.phase == "preflop" and entry.action in ("raise", "allin"):
            return True
    return False


def _is_facing_allin(req: p.ActionRequest, bot_name: str) -> bool:
    for entry in req.action_history:
        if entry.phase == "preflop" and entry.action == "allin" and entry.player != bot_name:
            return True
    return False


def _safe_fold(room_id: int) -> p.Action:
    return p.Action(room_id=room_id, action="fold")


def decide(
    req: p.ActionRequest,
    bot_name: str,
    deps: Optional[DecideDeps] = None,
) -> p.Action:
    deps = deps or build_default_deps()

    if len(req.your_cards) < 2:
        log.warning("insufficient cards: %s", req.your_cards)
        return _safe_fold(req.room_id)
    try:
        hand = canonicalize_hand(req.your_cards[0], req.your_cards[1])
    except ValueError:
        log.warning("cannot canonicalize cards: %s", req.your_cards)
        return _safe_fold(req.room_id)

    sb = req.blind[0] if len(req.blind) >= 1 else 0
    bb = req.blind[1] if len(req.blind) >= 2 else 0
    m = compute_m(req.my_stack, sb, bb)
    mode = select_mode(m, deps.thresholds)
    pos_class = deps.position_map.classify(req.seat, len(req.players))
    facing_raise = _is_facing_raise(req)
    facing_allin = _is_facing_allin(req, bot_name)

    # P3: HU 단계의 preflop 은 HU 전용 차트 (push_fold 보다 훨씬 wide).
    # facing aggression 은 hu_call (catch-all) 로 항상 적용. first-in 은 hu_jam bucket 이
    # 매칭 가능한 M 범위(≤13)에서만 분기 — 그 위는 일반 hybrid/mid 경로 활용.
    starting_size = (
        deps.game_state.starting_table_size(req.room_id)
        if deps.game_state is not None
        else None
    )
    if identify_stage(req, original_table_size=starting_size) == Stage.HEADS_UP and req.phase == "preflop":
        is_facing = facing_raise or facing_allin or req.to_call > bb
        # P5-3: hu_jam (M ≤ 13) 또는 hu_open (M > 13) 둘 중 하나라도 매칭되면 HU chart 사용.
        hu_chart_applicable = (
            deps.chart.pick("hu_jam", m) is not None
            or deps.chart.pick("hu_open", m) is not None
        )
        if is_facing or hu_chart_applicable:
            return _decide_heads_up(req, hand, m, facing_raise, facing_allin, deps)

    # push_fold/hybrid 는 프리플롭만 차트. postflop 에서는 pot-odds 로 위임.
    if mode in ("push_fold", "hybrid") and req.phase == "preflop":
        if mode == "push_fold":
            return _decide_push_fold(req, hand, m, pos_class, facing_raise, facing_allin, deps)
        return _decide_hybrid(req, hand, m, pos_class, facing_raise, deps)
    # mid/deep (+push_fold/hybrid postflop): opening chart / pot-odds
    return _decide_midlow_and_deep(req, hand, pos_class, facing_raise, deps, bot_name=bot_name)


def _decide_heads_up(
    req: p.ActionRequest,
    hand: str,
    m: float,
    facing_raise: bool,
    facing_allin: bool,
    deps: DecideDeps,
) -> p.Action:
    """HU (alive=2) preflop 전용 차트 분기.

    - facing raise/allin → hu_call chart 에 있으면 call, 아니면 fold.
    - first-in: hu_jam bucket 적용 가능(M ≤ 13)이면 jam range 검사 — 안에 있으면
      all-in, 밖이면 fold.
    - M > 13 (deep): hu_jam bucket = None → 일반 hybrid/mid 경로로 fallthrough
      (return 하지 않고 None-sentinel 대신 caller 가 사전 체크하므로 도달 시점에
      bucket 은 항상 매칭).
    """
    bb = req.blind[1] if len(req.blind) >= 2 else 0
    voluntary_over_blind = req.to_call > bb

    if facing_raise or facing_allin or voluntary_over_blind:
        bucket = deps.chart.pick("hu_call", m)
        if bucket is None or not bucket.lookup(hand, "any"):
            return _safe_fold(req.room_id)
        return p.Action(room_id=req.room_id, action="call")

    # First-in: M ≤ 13 → jam range, M > 13 → 일반 raise (hu_open).
    jam_bucket = deps.chart.pick("hu_jam", m)
    if jam_bucket is not None:
        if not jam_bucket.lookup(hand, "any"):
            if req.to_call == 0:
                return p.Action(room_id=req.room_id, action="check")
            return _safe_fold(req.room_id)
        return p.Action(room_id=req.room_id, action="allin")

    # P5-3: deep stack HU first-in. hu_open chart 안이면 raise (2.5x bb), 밖이면 check/fold.
    open_bucket = deps.chart.pick("hu_open", m)
    if open_bucket is None or not open_bucket.lookup(hand, "any"):
        if req.to_call == 0:
            return p.Action(room_id=req.room_id, action="check")
        return _safe_fold(req.room_id)
    target = max(int(round(2.5 * bb)), req.min_raise)
    if target <= 0 or target > req.my_stack:
        return _safe_fold(req.room_id)
    return p.Action(room_id=req.room_id, action="raise", amount=target)


def _decide_push_fold(
    req: p.ActionRequest,
    hand: str,
    m: float,
    pos_class: str,
    facing_raise: bool,
    facing_allin: bool,
    deps: DecideDeps,
) -> p.Action:
    # "facing a real action" 판정: 누군가 voluntary raise/allin 했거나,
    # BB 가 아닌 포지션에서 to_call 이 BB 를 초과 (= 상대가 raise 했다는 의미).
    bb = req.blind[1] if len(req.blind) >= 2 else 0
    voluntary_over_blind = req.to_call > bb
    if facing_raise or facing_allin or voluntary_over_blind:
        bucket = deps.chart.pick("call_vs_jam", m)
        if bucket is None or not bucket.lookup(hand, pos_class):
            return _safe_fold(req.room_id)
        return p.Action(room_id=req.room_id, action="call")

    bucket = deps.chart.pick("jam", m)
    if bucket is None or not bucket.lookup(hand, pos_class):
        return _safe_fold(req.room_id)
    return p.Action(room_id=req.room_id, action="allin")


def _table_is_loose_meta(
    req: p.ActionRequest, deps: DecideDeps, bot_name: str
) -> bool:
    """활성 상대들의 누적 VPIP 가중평균 ≥ 0.40 면 True.

    조건:
      - profile_store 가 있고,
      - 최소 1 명의 active villain 이 ≥ 30 hands 관측,
      - 그 villain 들의 VPIP hands-weighted 평균이 ≥ 0.40.

    P-Adapt2 의도: loose-passive 메타에서 isolation 빈도 확대. 30 hands 미만이면
    표본 부족으로 false 디폴트 (=> 기존 chart 유지).
    """
    store = deps.profile_store
    if store is None:
        return False
    weighted = 0.0
    total_w = 0.0
    for pl in req.players:
        if pl.status != "active" or not pl.name or pl.name == bot_name:
            continue
        prof = store.profiles.get(pl.name)
        if prof is None:
            continue
        cnt = prof.get("VPIP")
        if cnt.n_obs < 30:
            continue
        # P-Bias: test bot 은 가중치 0.3 으로 down-weight.
        w = cnt.n_obs * name_weight(pl.name)
        weighted += cnt.rate(default=0.0) * w
        total_w += w
    if total_w <= 0:
        return False
    return (weighted / total_w) >= 0.40


def _decide_midlow_and_deep(
    req: p.ActionRequest,
    hand: str,
    pos_class: str,
    facing_raise: bool,
    deps: DecideDeps,
    *,
    bot_name: str = "",
) -> p.Action:
    """mid (15 < M ≤ 30) / deep (M > 30).

    Week 3 D2 한정:
      - Preflop unopened: opening_chart + RFI size.
      - Preflop vs raise: call_vs_jam (타이트) 에 있을 때만 call, else fold.
      - Postflop: pot-odds call. 내 equity ≥ required + 여유마진 이면 call, 아니면 fold.
      - Postflop check/bet: to_call==0 일 때 check (적극 베팅은 D5+ 에서).
    """
    if req.phase == "preflop":
        if facing_raise:
            # tight defend: push_fold 의 call_vs_jam 을 재활용 (작은 범위)
            m = compute_m(req.my_stack, req.blind[0] if req.blind else 0,
                          req.blind[1] if len(req.blind) >= 2 else 0)
            bucket = deps.chart.pick("call_vs_jam", m)
            if bucket is None or not bucket.lookup(hand, pos_class):
                return _safe_fold(req.room_id)
            return p.Action(room_id=req.room_id, action="call")

        # unopened → RFI chart (P-Adapt2: loose 메타 / P5-1: 5-max 분기).
        meta_loose = _table_is_loose_meta(req, deps, bot_name)
        n_active = sum(
            1 for pl in req.players
            if pl.status == "active" and (pl.name or "").strip()
        )
        if not deps.opening.in_rfi_range(
            hand, pos_class, meta_loose=meta_loose, n_players=n_active
        ):
            if req.to_call == 0:
                return p.Action(room_id=req.room_id, action="check")
            return _safe_fold(req.room_id)

        # 오픈 사이즈 = conservatism-selected RFI bb × BB
        bb = req.blind[1] if len(req.blind) >= 2 else 2
        fallback_bb = deps.opening.rfi_size_bb(pos_class)
        cons = _table_conservatism(req, "", deps)  # bot_name 은 자기제외용, RFI 는 self 인지 불필요
        size_bb = _rfi_size_bb(pos_class, cons, fallback_bb)
        target = max(int(round(size_bb * bb)), req.min_raise)
        if target > req.my_stack or req.min_raise <= 0:
            return _safe_fold(req.room_id)
        return p.Action(room_id=req.room_id, action="raise", amount=target)

    # --- postflop ---
    # P1: EV tree 가 기본. --no-ev-tree 로 회귀하면 pot-odds 경로.
    if deps.use_ev_tree_postflop:
        return _decide_postflop_ev(req, deps, bot_name=bot_name)

    if req.to_call == 0:
        return p.Action(room_id=req.room_id, action="check")

    # pot-odds 기반 call/fold
    required = pot_odds(req.to_call, req.pot)
    try:
        eq = equity_from_cards(
            req.your_cards[0], req.your_cards[1],
            list(req.community_cards),
            n_opp=max(1, _count_active_opponents(req)),
            samples=deps.equity_samples,
        )
    except Exception:
        log.exception("equity calc failed")
        return _safe_fold(req.room_id)

    if eq >= required + deps.equity_safety_margin:
        return p.Action(room_id=req.room_id, action="call")
    return _safe_fold(req.room_id)


def postflop_candidates(req: p.ActionRequest, deps: DecideDeps) -> list[EVCandidate]:
    """Postflop 상황에서 허용 EVCandidate list 를 반환 (coordinator 입력용).

    equity 계산 실패 시 빈 list.
    """
    try:
        eq = equity_from_cards(
            req.your_cards[0], req.your_cards[1],
            list(req.community_cards),
            n_opp=max(1, _count_active_opponents(req)),
            samples=deps.equity_samples,
        )
    except Exception:
        log.exception("equity calc failed")
        return []
    bb = req.blind[1] if len(req.blind) >= 2 else 2
    me = next((pl for pl in req.players if pl.name == req.seat or pl.position == req.seat), None)
    my_bet = me.bet if me else 0
    inputs = EVInputs(
        pot=req.pot,
        to_call=req.to_call,
        my_stack=req.my_stack,
        my_bet=my_bet,
        equity=eq,
        bb=bb,
    )
    cons = _table_conservatism(req, "", deps)
    # per-opponent × phase response (학습된 반응). store 없거나 신규 상대면 (1,1,1).
    response = _aggregate_response(req, deps)
    rng = random.Random(deps.ev_seed) if deps.ev_seed is not None else None
    return ev_enumerate(cons, response, inputs, kind="value", rng=rng)


def _aggregate_response(req: p.ActionRequest, deps: DecideDeps) -> DirichletResponse:
    """활성 상대들의 phase 별 DirichletResponse 를 집계.

    - 2-way: 단순 Dirichlet α 합산 (기존 동작).
    - 3+way (plan H.8): 보수 joint fold 근사 `P(all_fold) = min(f_i)^(n-1)`.
      독립 곱 가정 f̄^n 보다 엄격 — 블러핑 EV 과대 추정 방지.

    me (자신) 은 request 의 seat 로 식별해 제외.
    """
    store = deps.profile_store
    if store is None:
        return DirichletResponse()
    my_name = _resolve_my_name(req)
    opponent_names = [
        pl.name for pl in req.players
        if pl.status == "active" and pl.name and pl.name != my_name
    ]
    n_opp = len(opponent_names)
    if n_opp <= 0:
        return DirichletResponse()

    agg = store.responses.aggregate(opponent_names, req.phase)
    if n_opp < 2:
        return agg

    # 멀티웨이 보수: 개별 상대 fold mean 중 min 을 base 로 joint fold 계산.
    per_opp = [store.responses.lookup(nm, req.phase) for nm in opponent_names]
    fold_rates = [r.mean()["fold"] for r in per_opp]
    if not fold_rates:
        return agg
    min_fold = min(fold_rates)
    joint_fold = min_fold ** n_opp
    # 남는 확률 질량 = 1 - joint_fold → aggregate mean 의 call/raise 비율로 분배.
    agg_mean = agg.mean()
    cr_sum = max(1e-9, agg_mean["call"] + agg_mean["raise"])
    call_share = agg_mean["call"] / cr_sum
    raise_share = 1.0 - call_share
    remaining = max(0.0, 1.0 - joint_fold)
    total_alpha = max(3.0, agg.alpha_fold + agg.alpha_call + agg.alpha_raise)
    return DirichletResponse(
        alpha_fold=joint_fold * total_alpha,
        alpha_call=remaining * call_share * total_alpha,
        alpha_raise=remaining * raise_share * total_alpha,
    )


def _resolve_my_name(req: p.ActionRequest) -> str:
    """req 에서 내 이름을 추출. seat 가 name 일 수도, position 일 수도 있음."""
    for pl in req.players:
        if pl.name == req.seat or pl.position == req.seat:
            return pl.name or ""
    return ""


def candidate_to_action(cand: EVCandidate, req: p.ActionRequest, my_bet: int = 0) -> p.Action:
    """EVCandidate → 서버 전송 가능한 Action (min_raise/stack 경계 보정)."""
    if cand.action == "raise":
        amount = cand.amount or 0
        if amount < max(1, req.min_raise):
            amount = max(1, req.min_raise)
        if amount > req.my_stack + my_bet:
            amount = req.my_stack + my_bet
        return p.Action(room_id=req.room_id, action="raise", amount=amount)
    if cand.action in ("allin", "call", "check", "fold"):
        return p.Action(room_id=req.room_id, action=cand.action)
    return _safe_fold(req.room_id)


def _decide_postflop_ev(
    req: p.ActionRequest, deps: DecideDeps, bot_name: str = ""
) -> p.Action:
    """D6 EV tree + D4 Conservatism + P1 c-bet 으로 postflop 결정.

    실패 경로 (equity 계산 오류, 후보 0개 등) 는 안전 fallback (check or fold).

    P1 변경:
      - value + bluff candidate 모두 enumerate 후 max(log_util) 선택.
      - flop preflop-aggressor 시나리오에서는 cbet 모듈이 fold equity 보정.
    """
    try:
        eq = equity_from_cards(
            req.your_cards[0], req.your_cards[1],
            list(req.community_cards),
            n_opp=max(1, _count_active_opponents(req)),
            samples=deps.equity_samples,
        )
    except Exception:
        log.exception("equity calc failed")
        if req.to_call == 0:
            return p.Action(room_id=req.room_id, action="check")
        return _safe_fold(req.room_id)

    bb = req.blind[1] if len(req.blind) >= 2 else 2
    me = next((pl for pl in req.players if pl.name == req.seat or pl.position == req.seat), None)
    my_bet = me.bet if me else 0
    inputs = EVInputs(
        pot=req.pot,
        to_call=req.to_call,
        my_stack=req.my_stack,
        my_bet=my_bet,
        equity=eq,
        bb=bb,
    )
    cons = _table_conservatism(req, bot_name, deps)
    # P2: stage 별 bluff_factor 보정 (final_table 보수화, HU 공격화).
    starting_size = (
        deps.game_state.starting_table_size(req.room_id)
        if deps.game_state is not None
        else None
    )
    cons = apply_stage_to_conservatism(
        cons,
        identify_stage(req, original_table_size=starting_size),
        table_size=starting_size,
    )
    response = _aggregate_response(req, deps)
    # C-bet 보정: 시나리오 충족 시 fold equity boost 한 새 response 사용.
    # P-Adapt1: profile_store 를 전달해 villain 누적 FOLD_TO_CBET 직접 반영.
    cbet_resp = cbet_response_adjustment(
        req, bot_name or _resolve_my_name(req), response, deps.profile_store
    )
    if cbet_resp is not None:
        response = cbet_resp
    rng = random.Random(deps.ev_seed) if deps.ev_seed is not None else None

    val_cands = ev_enumerate(cons, response, inputs, kind="value", rng=rng)
    bluff_cands = ev_enumerate(cons, response, inputs, kind="bluff", rng=rng)
    # 중복 fold/check/call 후보는 동일 EV 라 max 선택에 영향 없음.
    all_cands = val_cands + bluff_cands
    best = max(all_cands, key=lambda c: c.log_util)

    # server 최소 베팅/스택 경계 보정
    if best.action == "raise":
        amount = best.amount or 0
        if amount < max(1, req.min_raise):
            amount = max(1, req.min_raise)
        if amount > req.my_stack + my_bet:
            amount = req.my_stack + my_bet
        return p.Action(room_id=req.room_id, action="raise", amount=amount)
    if best.action == "allin":
        return p.Action(room_id=req.room_id, action="allin")
    if best.action == "call":
        return p.Action(room_id=req.room_id, action="call")
    if best.action == "check":
        return p.Action(room_id=req.room_id, action="check")
    return _safe_fold(req.room_id)


def _count_active_opponents(req: p.ActionRequest) -> int:
    n = 0
    for pl in req.players:
        if pl.status == "active" and pl.name != "":
            n += 1
    return max(0, n - 1)   # 본인 제외


def _table_conservatism(
    req: p.ActionRequest,
    bot_name: str,
    deps: DecideDeps,
) -> ConservatismProfile:
    """테이블-와이드 보수성 = 활성 상대 중 n_effective 가 가장 낮은 상대 기준.

    즉 '가장 모르는 상대' 에 맞춰 보수적으로 플레이.
    profile_store 가 없거나 비어있으면 None 프로필 (hard_conservative).
    """
    store = deps.profile_store
    if store is None:
        return compute_profile(None)
    worst: ConservatismProfile | None = None
    for pl in req.players:
        if pl.name == bot_name or pl.status != "active":
            continue
        prof = store.profiles.get(pl.name)
        cp = compute_profile(prof)
        if worst is None or cp.n_effective < worst.n_effective:
            worst = cp
    return worst or compute_profile(None)


def _rfi_size_bb(
    pos_class: str,
    cons: ConservatismProfile,
    fallback_bb: float,
) -> float:
    """sizing_grid 의 raise_open_bb 목록에서 보수성-적절 사이즈 선택.

    conservative grid: 가장 작은 값 (tight open).
    balanced/exploit: 포지션별 분기 — EP 는 작게, LP 는 중간.
    """
    sizes = cons.sizing_grid.raise_open_bb
    if len(sizes) == 0:
        return fallback_bb
    # 간단 규칙: EP/MP 는 맨 앞 (작음), LP/BLIND 는 중앙.
    if pos_class in ("LP", "BLIND") and len(sizes) > 1:
        return sizes[len(sizes) // 2]
    return sizes[0]


async def decide_async(
    req: p.ActionRequest,
    bot_name: str,
    deps: Optional[DecideDeps] = None,
    coordinator=None,
    triggers=None,
) -> p.Action:
    """Async decide entrypoint — postflop 에서 coordinator 를 경유.

    coordinator 가 None 이거나 preflop 이면 sync `decide()` 와 동일 동작.
    postflop + use_ev_tree_postflop 경로에서만 EV candidates → coordinator → Action.
    """
    deps = deps or build_default_deps()
    if coordinator is None or req.phase == "preflop" or not deps.use_ev_tree_postflop:
        return decide(req, bot_name, deps)

    candidates = postflop_candidates(req, deps)
    if not candidates:
        return decide(req, bot_name, deps)

    if triggers is None:
        from ..meta.triggers import build_triggers
        triggers = build_triggers(req, bot_name, profile_store=deps.profile_store)

    decision = await coordinator.decide(
        candidates,
        triggers=triggers,
        context={"phase": req.phase, "pot": req.pot, "to_call": req.to_call},
        room_id=req.room_id,
        hand_number=req.hand_number,
    )
    me = next((pl for pl in req.players if pl.name == req.seat or pl.position == req.seat), None)
    my_bet = me.bet if me else 0
    return candidate_to_action(decision.candidate, req, my_bet=my_bet)


def _decide_hybrid(
    req: p.ActionRequest,
    hand: str,
    m: float,
    pos_class: str,
    facing_raise: bool,
    deps: DecideDeps,
) -> p.Action:
    if facing_raise:
        bucket = deps.chart.pick("call_vs_jam", m)
        if bucket is None or not bucket.lookup(hand, pos_class):
            return _safe_fold(req.room_id)
        return p.Action(room_id=req.room_id, action="call")

    bucket = deps.chart.pick("hybrid_open", m)
    if bucket is None or not bucket.lookup(hand, pos_class):
        return _safe_fold(req.room_id)
    # min_raise 가 유효하지 않으면 fold (서버 자동 폴드 방어)
    if req.min_raise <= 0 or req.min_raise > req.my_stack:
        return _safe_fold(req.room_id)
    return p.Action(room_id=req.room_id, action="raise", amount=req.min_raise)
