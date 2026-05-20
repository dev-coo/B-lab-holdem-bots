"""Continuation bet (c-bet) — postflop EV tree 의 fold-equity 보정.

Population fold-to-cbet 은 일반 baseline (~33%) 보다 높음 (~50–60% in HU dry
boards, 보드/포지션/상대수 의존). 그러나 Dirichlet response 는 신규 상대에
대해 (1,1,1) 을 prior 로 시작하므로 EV tree 가 fold equity 를 과소평가해
c-bet 을 결정하지 못함.

이 모듈은 c-bet 시나리오를 식별하고, 적용 가능한 경우 **fold equity 를 boost
한 새 DirichletResponse** 를 반환한다. EV tree 가 그 response 를 사용하면
bluff 사이즈가 +EV 로 보여 자연스럽게 c-bet 이 선택된다.

c-bet 시나리오 조건 (`cbet_response_adjustment`):
  - phase == 'flop'
  - 봇이 preflop aggressor (action_history 에 my_name 이 raise/allin)
  - to_call == 0  (상대가 체크해서 우리 차례)
  - 1 ≤ active_opponents ≤ 2 (HU 또는 3-way 까지 — multi-way 는 fold equity 급감)

Boost 정도:
  - target_fold = base + dryness_bonus + position_bonus
  - dry board (wetness ≤ 0.3) → 더 높은 target
  - HU (n_opp == 1) → 더 높은 target

P-Adapt1 (실 데이터 적응): profile_store 가 주어지면 active villain 들의 누적
`FOLD_TO_CBET` 메트릭을 weighted-blend 해 target_fold 를 보정.
  - villain 의 hands_seen ≥ 50 면 villain rate 100% 사용.
  - hands_seen < 50 면 baseline 과 선형 blend (가중치 = hands/50).
  - 모든 villain 이 sticky (rate < 0.20) + 충분 관측 (≥30) 이면 c-bet 비활성 (None 반환).

target_fold > base 일 때만 boost 적용. 이미 base 가 충분하면 None 반환
(EV tree 의 자연 결정에 맡김).
"""
from __future__ import annotations

from typing import Optional

from ..estimate.bayes import DirichletResponse
from ..estimate.board_texture import analyze as analyze_board
from ..state.profile_store import ProfileStore, name_weight
from ..transport import protocol as p

# P-Floor: villain 데이터에 100% 의존하지 않고 baseline 영향 일정 비율 보존.
# 메타 변화 시 (다른 봇 전략 도입 등) 과거 villain 패턴에 freeze 되지 않도록 안전장치.
_VILLAIN_FULL_WEIGHT_HANDS = 100.0   # full-weight 임계 (보수화: 50 → 100)
_VILLAIN_MAX_WEIGHT = 0.7            # baseline 30% 영향 최소 보존
_STICKY_RATE = 0.20                  # 이 이하면 sticky (c-bet 안 통함)
_STICKY_MIN_HANDS = 30.0             # sticky 판단을 위한 최소 관측 핸드


def is_preflop_aggressor(req: p.ActionRequest, my_name: str) -> bool:
    """action_history 에서 my_name 이 preflop 마지막에 raise/allin 했는가."""
    last_aggressor: str | None = None
    for entry in req.action_history:
        if entry.phase != "preflop":
            continue
        if entry.action in ("raise", "allin"):
            last_aggressor = entry.player
    return last_aggressor == my_name


def _count_active_opps(req: p.ActionRequest, my_name: str) -> int:
    n = 0
    for pl in req.players:
        if pl.status != "active":
            continue
        if not pl.name:
            continue
        if pl.name == my_name:
            continue
        n += 1
    return n


def _target_fold_rate(wetness: float, n_opp: int) -> float:
    """C-bet 시 가정할 상대 fold 확률 (population baseline).

    HU dry  (wetness=0)   → 0.65
    HU wet  (wetness=1)   → 0.45
    3-way dry             → 0.45
    3-way wet             → 0.30
    선형 보간 후 [0.30, 0.70] clamp.
    """
    if n_opp <= 1:
        target = 0.65 - 0.20 * max(0.0, min(1.0, wetness))
    elif n_opp == 2:
        target = 0.45 - 0.15 * max(0.0, min(1.0, wetness))
    else:
        return 0.0   # multi-way 큼 — boost 안 함.
    return max(0.30, min(0.70, target))


def _villain_fold_to_cbet_weighted(
    req: p.ActionRequest,
    my_name: str,
    profile_store: Optional[ProfileStore],
) -> Optional[tuple[float, float, bool]]:
    """active villain 들의 FOLD_TO_CBET hands-weighted 평균.

    Returns:
        None: profile_store 가 None 이거나 어떤 villain 도 관측 데이터 없음.
        (rate, total_hands, all_sticky):
          - rate: 관측된 villain 들의 가중평균 fold rate.
          - total_hands: 누적 관측 핸드 합.
          - all_sticky: 모든 관측된 villain 이 sticky 면 True (각자 ≥30 hands & rate <0.20).
    """
    if profile_store is None:
        return None
    weighted_sum = 0.0
    total_w = 0.0
    sticky_flags: list[bool] = []
    for pl in req.players:
        if pl.status != "active" or not pl.name or pl.name == my_name:
            continue
        prof = profile_store.profiles.get(pl.name)
        if prof is None:
            continue
        cnt = prof.metrics.get("FOLD_TO_CBET")
        if cnt is None or cnt.n_obs <= 0:
            continue
        rate = cnt.rate(default=0.0)
        # P-Bias: test bot 은 가중치 0.3 으로 down-weight.
        w = cnt.n_obs * name_weight(pl.name)
        weighted_sum += rate * w
        total_w += w
        sticky_flags.append(cnt.n_obs >= _STICKY_MIN_HANDS and rate < _STICKY_RATE)
    if total_w <= 0:
        return None
    avg = weighted_sum / total_w
    all_sticky = bool(sticky_flags) and all(sticky_flags)
    return (avg, total_w, all_sticky)


def cbet_response_adjustment(
    req: p.ActionRequest,
    my_name: str,
    base_response: DirichletResponse,
    profile_store: Optional[ProfileStore] = None,
) -> Optional[DirichletResponse]:
    """C-bet 시나리오면 fold equity 가 보정된 DirichletResponse 반환, 아니면 None.

    Returns None if:
      - 시나리오 조건 미충족 (phase / aggressor / to_call / n_opp)
      - base_response 의 fold 평균이 이미 target 이상
      - board 분석 실패
      - profile_store 가 주어졌고 모든 villain 이 sticky (실 메타에서 c-bet 안 통함)
    """
    if req.phase != "flop":
        return None
    if req.to_call != 0:
        return None
    if not is_preflop_aggressor(req, my_name):
        return None

    n_opp = _count_active_opps(req, my_name)
    if n_opp == 0 or n_opp > 2:
        return None

    if len(req.community_cards) < 3:
        return None
    try:
        texture = analyze_board(list(req.community_cards))
    except Exception:
        return None

    target_fold = _target_fold_rate(texture.wetness, n_opp)
    if target_fold <= 0:
        return None

    # P-Adapt1: villain 누적 FOLD_TO_CBET 으로 target_fold 보정.
    villain = _villain_fold_to_cbet_weighted(req, my_name, profile_store)
    if villain is not None:
        v_rate, v_hands, all_sticky = villain
        if all_sticky:
            # 실 메타가 c-bet 안 통하는 sticky pool — boost 비활성.
            return None
        # P-Floor: weight 는 _VILLAIN_MAX_WEIGHT 로 cap → baseline 영향 (30%) 보존.
        weight = min(_VILLAIN_MAX_WEIGHT, v_hands / _VILLAIN_FULL_WEIGHT_HANDS)
        target_fold = (1.0 - weight) * target_fold + weight * v_rate

    base_mean = base_response.mean()
    base_fold = base_mean["fold"]
    if base_fold >= target_fold:
        return None   # 이미 충분 — boost 불필요.

    alpha_total = (
        base_response.alpha_fold
        + base_response.alpha_call
        + base_response.alpha_raise
    )
    if alpha_total <= 0:
        return None

    new_alpha_fold = target_fold * alpha_total
    remaining = alpha_total - new_alpha_fold
    cr_sum = base_response.alpha_call + base_response.alpha_raise
    if cr_sum <= 0:
        # baseline 정보 부족 — call/raise 70/30 으로 분배.
        new_alpha_call = remaining * 0.70
        new_alpha_raise = remaining * 0.30
    else:
        new_alpha_call = remaining * (base_response.alpha_call / cr_sum)
        new_alpha_raise = remaining * (base_response.alpha_raise / cr_sum)

    return DirichletResponse(
        alpha_fold=new_alpha_fold,
        alpha_call=new_alpha_call,
        alpha_raise=new_alpha_raise,
    )
