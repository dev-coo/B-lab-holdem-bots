"""Tournament M-ratio & push/fold 결정.

MTT/Sit-n-Go 에서 블라인드가 스택을 잡아먹기 시작하면 Harrington 식
M-ratio (stack / (SB+BB)) 로 전략을 전환한다.

- M >= cfg.m_healthy   : healthy — 풀 포스트플롭
- M >= cfg.m_tight     : tight — 오픈 레인지 약간 축소
- M >= cfg.m_push_fold : push_fold — 마지널 shove 구간
- M <  cfg.m_push_fold : desperate — wide shove

Nash push chart 를 포지션별 정확 수치로 구현하지 않고, 보수적 근사를 씀.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from holdem_core.equity import equity_mc
from holdem_core.models.actions import Action

from holdem_main_bot.opp_range import combos_from_keys
from holdem_main_bot.position import active_count

if TYPE_CHECKING:
    from holdem_core.models.events import ActionRequest

    from holdem_main_bot.position import Position
    from holdem_main_bot.strategy import StrategyConfig

Regime = Literal["healthy", "tight", "push_fold", "desperate"]


def effective_m(req: "ActionRequest") -> float:
    sb, bb = req.blind[0], req.blind[1]
    total = sb + bb
    if total <= 0:
        return 999.0
    return req.my_stack / total


def m_regime(m: float, cfg: "StrategyConfig") -> Regime:
    if m >= cfg.m_healthy:
        return "healthy"
    if m >= cfg.m_tight:
        return "tight"
    if m >= cfg.m_push_fold:
        return "push_fold"
    return "desperate"


# Nash 근사 push 레인지. 3 <= M < 6 (push_fold).
# v5.2: dominated 위험 큰 A7o 제외. 탈락 52.2% 가 allin_call_dominated 이므로
# marginal offsuit Ax 는 pocket pair + stronger Ax 에 자주 behind.
_PUSH_PF: frozenset[str] = frozenset(
    {
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        "AKs",
        "AQs",
        "AJs",
        "ATs",
        "A9s",
        "A8s",
        "A7s",
        "A6s",
        "A5s",
        "A4s",
        "A3s",
        "A2s",
        "AKo",
        "AQo",
        "AJo",
        "ATo",
        "A9o",
        "A8o",
        "KQs",
        "KJs",
        "KTs",
        "K9s",
        "KQo",
        "KJo",
        "KTo",
        "QJs",
        "QTs",
        "Q9s",
        "QJo",
        "QTo",
        "JTs",
        "J9s",
        "JTo",
        "T9s",
        "98s",
        "87s",
    }
)

# M < 3 (desperate). v5.2: dominated 빈발하는 J9o/T9o/A5o 제외.
# J9o, T9o 는 pocket pair 와 broadway 에 광범위하게 지배됨.
# A5o 는 A8o+ 에 dominated. A6o 유지 (5-wheel blocker).
_PUSH_DESPERATE: frozenset[str] = _PUSH_PF | frozenset(
    {
        "A6o",
        "K9o",
        "Q9o",
    }
)

# SB/BB 에서 blind 회수 목적 shove 는 약간 더 넓게.
_PUSH_BLIND_WIDER: frozenset[str] = frozenset(
    {
        "K8s",
        "K7s",
        "Q8s",
        "J8s",
        "97s",
        "K9o",
        "Q9o",
        "J9o",
        "T9o",
        "98o",
    }
)

# BB 가 facing shove (call 전용) 레인지 — 매우 타이트 (value-only).
# v5.2: 77 제거. shove 당한 상황에서 77 은 overcards 2장 vs coinflip 빈번 → -EV.
# 88+ 로 한정 (상대 shove 레인지 중앙값에 대해 58%+ equity 확보).
_BB_CALL_VS_SHOVE: frozenset[str] = frozenset(
    {
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "99",
        "88",
        "AKs",
        "AQs",
        "AJs",
        "AKo",
        "AQo",
    }
)

# 상대가 loose pusher (VPIP>=30%) 일 때 call 레인지 확장.
# opp_class 가 'loose' 로 판정되면 이 집합을 _BB_CALL_VS_SHOVE 에 union.
_BB_CALL_VS_LOOSE_SHOVE: frozenset[str] = frozenset(
    {
        "77",
        "66",
        "ATs",
        "A9s",
        "KQs",
        "KJs",
        "AJo",
        "KQo",
    }
)

# v5.3: HU(2-handed) 에서 상대 shove 범위는 훨씬 넓음(표준 BTN shove 40~60%).
# call 레인지도 대폭 확장 — ~40% combos.
_HU_CALL_VS_SHOVE: frozenset[str] = frozenset(
    {
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        "AKs",
        "AQs",
        "AJs",
        "ATs",
        "A9s",
        "A8s",
        "A7s",
        "AKo",
        "AQo",
        "AJo",
        "ATo",
        "A9o",
        "KQs",
        "KJs",
        "KTs",
        "K9s",
        "KQo",
        "KJo",
        "KTo",
        "QJs",
        "QTs",
        "Q9s",
        "QJo",
        "QTo",
        "JTs",
        "J9s",
        "JTo",
        "T9s",
    }
)

# v5.3.1: HU push_fold 구간(M 얇음) shove range. 실측 HU 결정 861 중 push_fold+desperate
# 83.5% 인데 _PUSH_PF/_PUSH_DESPERATE (~20~22%) 쓰다보니 fold 73.6%. HU 표준 BTN
# shove 는 M≤10 에서 40~60%, M≤5 에서 70~85%. blind-bleed 탈출 우선.
# ~55% combos — pair 전부, 모든 Ax, Kx, Qx broadway+suited low, 모든 suited connector.
_HU_PUSH_PF: frozenset[str] = frozenset(
    {
        # Pairs
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        # Ax 전부
        "AKs",
        "AQs",
        "AJs",
        "ATs",
        "A9s",
        "A8s",
        "A7s",
        "A6s",
        "A5s",
        "A4s",
        "A3s",
        "A2s",
        "AKo",
        "AQo",
        "AJo",
        "ATo",
        "A9o",
        "A8o",
        "A7o",
        "A6o",
        "A5o",
        "A4o",
        "A3o",
        "A2o",
        # Kx
        "KQs",
        "KJs",
        "KTs",
        "K9s",
        "K8s",
        "K7s",
        "K6s",
        "K5s",
        "K4s",
        "K3s",
        "K2s",
        "KQo",
        "KJo",
        "KTo",
        "K9o",
        "K8o",
        "K7o",
        "K6o",
        "K5o",
        # Qx broadway + suited down to Q5s
        "QJs",
        "QTs",
        "Q9s",
        "Q8s",
        "Q7s",
        "Q6s",
        "Q5s",
        "QJo",
        "QTo",
        "Q9o",
        "Q8o",
        # Jx broadway + suited
        "JTs",
        "J9s",
        "J8s",
        "J7s",
        "JTo",
        "J9o",
        "J8o",
        # Tx suited + T9o
        "T9s",
        "T8s",
        "T7s",
        "T9o",
        # Suited connectors / one-gap
        "98s",
        "97s",
        "87s",
        "86s",
        "76s",
        "75s",
        "65s",
        "64s",
        "54s",
        "53s",
        "43s",
    }
)

# v5.3.1: HU desperate (M<2) — 거의 모든 핸드 shove. blind 1-2바퀴 내에 끝나는 구간.
# 완전 쓰레기 (low-low offsuit disconnected) 만 제외.
_HU_PUSH_DESPERATE: frozenset[str] = _HU_PUSH_PF | frozenset(
    {
        # Remaining Qx/Jx/Tx/9x/8x suited
        "Q4s",
        "Q3s",
        "Q2s",
        "J6s",
        "J5s",
        "J4s",
        "J3s",
        "J2s",
        "T6s",
        "T5s",
        "T4s",
        "96s",
        "95s",
        "85s",
        "84s",
        "74s",
        "73s",
        "63s",
        "62s",
        "52s",
        "42s",
        "32s",
        # Offsuit 확장 (mid-broadway + connected)
        "K4o",
        "K3o",
        "K2o",
        "Q7o",
        "Q6o",
        "Q5o",
        "Q4o",
        "Q3o",
        "Q2o",
        "J7o",
        "J6o",
        "J5o",
        "J4o",
        "T8o",
        "T7o",
        "T6o",
        "T5o",
        "98o",
        "97o",
        "96o",
        "95o",
        "87o",
        "86o",
        "85o",
        "76o",
        "75o",
        "74o",
        "65o",
        "64o",
        "54o",
        "53o",
    }
)


def _faced_shove(req: "ActionRequest") -> bool:
    """내 앞에서 누가 allin 한 상태(= 상대 베팅 >= my_stack)."""
    return req.to_call >= req.my_stack


def _last_aggressor_name(req: "ActionRequest") -> str | None:
    """가장 최근 프리플롭 aggressor 이름 (faced_shove 시 상대 특정용)."""
    name: str | None = None
    for item in req.action_history:
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        if d.get("phase") == "preflop" and d.get("action") in ("raise", "allin"):
            n = d.get("player")
            if isinstance(n, str):
                name = n
    return name


def _preflop_equity_vs_range(
    my_cards: list[str],
    opp_range: frozenset[str],
    samples: int,
) -> float | None:
    """내 홀카드 vs 상대 hand_key range 의 preflop equity.

    samples 작아도 OK (preflop 은 분산 작음). 실패 시 None.
    """
    if not my_cards or len(my_cards) < 2:
        return None
    dead = set(my_cards)
    combos = combos_from_keys(opp_range, dead)
    if not combos:
        return None
    try:
        return equity_mc(my_cards, [], samples=samples, opp_combos=combos)
    except Exception:  # noqa: BLE001
        return None


def push_fold_decision(
    req: "ActionRequest",
    pos: "Position",
    hand_key: str,
    cfg: "StrategyConfig",
    profiles: dict | None = None,
) -> Action | None:
    """M 이 push_fold/desperate 구간일 때 shove-or-fold 결정.

    반환 None 이면 상위 로직이 계속 처리 (healthy/tight 구간).

    profiles: {name: OppProfile} — faced_shove 시 shover VPIP 로 call 범위 조정.
    VPIP >= 0.30 (loose) 상대면 _BB_CALL_VS_LOOSE_SHOVE 를 union 해서 넓게 call.
    """
    m = effective_m(req)
    regime = m_regime(m, cfg)
    if regime in ("healthy", "tight"):
        return None

    faced_shove = _faced_shove(req)
    # v5.3: HU(2-handed) 모드 — call-vs-shove 레인지 대폭 확대 + equity gate 완화.
    is_hu = getattr(cfg, "enable_hu_mode", False) and active_count(req.players) == 2

    # faced_shove 시 call 집합을 상대 VPIP 로 동적 확장.
    _LOOSE_VPIP_THRESHOLD = 0.30
    _MIN_HANDS_FOR_PROFILE = 15

    def _call_set_for_shover() -> frozenset[str]:
        # v5.3: HU 면 기본 HU 전용 widened range. loose VPIP 는 그 위에 union.
        base = _HU_CALL_VS_SHOVE if is_hu else _BB_CALL_VS_SHOVE
        if not profiles:
            return base
        shover = _last_aggressor_name(req)
        if not shover:
            return base
        prof = profiles.get(shover)
        if not isinstance(prof, dict):
            return base
        hands_seen = int(prof.get("hands_seen") or 0)
        if hands_seen < _MIN_HANDS_FOR_PROFILE:
            return base
        vpip = float(prof.get("vpip") or 0.0)
        if vpip >= _LOOSE_VPIP_THRESHOLD:
            return base | _BB_CALL_VS_LOOSE_SHOVE
        return base

    my_cards = list(req.your_cards)
    gate_on = getattr(cfg, "enable_preflop_equity_gate", False)
    gate_samples = int(getattr(cfg, "preflop_equity_gate_samples", 400))
    shove_min = float(getattr(cfg, "preflop_shove_equity_min", 0.36))
    # v5.3: HU 에서는 상대 shove range 가 넓어 call gate 완화.
    call_min = float(
        getattr(cfg, "hu_call_shove_equity_min", 0.40)
        if is_hu
        else getattr(cfg, "preflop_call_shove_equity_min", 0.45)
    )
    # v5.4: shover 별 VPIP 로 call_min 동적 보정.
    # loose pusher (VPIP≥0.30, 예: 고니 53%) — range 넓어 내 equity 낮게 나옴 → 완화.
    # tight pusher (VPIP≤0.18, 예: 편경장 14%) — premium 만 shove → 강화.
    if profiles:
        shover_p = _last_aggressor_name(req)
        if shover_p:
            prof_p = profiles.get(shover_p)
            if isinstance(prof_p, dict) and int(prof_p.get("hands_seen") or 0) >= 200:
                vpip_p = float(prof_p.get("vpip") or 0.0)
                if vpip_p >= 0.30:
                    call_min = max(0.30, call_min - 0.05)
                elif vpip_p <= 0.18:
                    call_min = min(0.55, call_min + 0.05)
    # raise_cnt 추적 — 이미 누가 raise 했다면 상대 tier 높아짐.
    raise_cnt = sum(
        1
        for item in req.action_history
        if (
            (item.model_dump() if hasattr(item, "model_dump") else dict(item)).get("phase")
            == "preflop"
        )
        and (
            (item.model_dump() if hasattr(item, "model_dump") else dict(item)).get("action")
            in ("raise", "allin")
        )
    )

    def _shover_range() -> frozenset[str]:
        """상대 shover 의 추정 레인지. 3bet+ 는 TIGHT, 첫 shove 는 PUSH_PF."""
        from holdem_main_bot.opp_range import TIER_TOP10, TIER_TOP20

        if raise_cnt >= 2:
            return TIER_TOP10  # 3bet+ 레벨, 매우 타이트
        if raise_cnt >= 1:
            return TIER_TOP20  # 일반 open+shove
        return _PUSH_PF  # first-in shove

    # desperate. v2: faced_shove 는 _BB_CALL_VS_SHOVE 만 call 하도록 분리.
    # v5.2: opp_classes 반영 + equity gate. loose pusher 상대에는 더 넓게 call.
    if regime == "desperate":
        if faced_shove:
            call_set = _call_set_for_shover()
            if hand_key in call_set:
                # equity gate: 상대 shove range 대비 내 equity 확인.
                if gate_on:
                    eq = _preflop_equity_vs_range(my_cards, _shover_range(), gate_samples)
                    if eq is not None and eq < call_min:
                        return Action(room_id=req.room_id, action="fold")
                return Action(room_id=req.room_id, action="allin", amount=req.my_stack)
            return Action(room_id=req.room_id, action="fold")
        # v5.3.1: HU 면 더 넓은 _HU_PUSH_DESPERATE 사용 (기본 ~22% → ~80%).
        desperate_push_set = _HU_PUSH_DESPERATE if is_hu else _PUSH_DESPERATE
        if hand_key in desperate_push_set:
            # desperate 에서는 blind 탈출이 더 중요하므로 gate 완화 (shove_min - 0.05).
            if gate_on and raise_cnt >= 1:
                eq = _preflop_equity_vs_range(my_cards, _shover_range(), gate_samples)
                if eq is not None and eq < max(0.30, shove_min - 0.05):
                    return Action(room_id=req.room_id, action="fold")
            return Action(room_id=req.room_id, action="allin", amount=req.my_stack)
        if req.to_call == 0:
            return Action(room_id=req.room_id, action="check")
        return Action(room_id=req.room_id, action="fold")

    # push_fold: shove 레인지 제한.
    # v5.3.1: HU 면 _HU_PUSH_PF (~55%). BLIND_WIDER 는 HU 에 무의미.
    push_set = _HU_PUSH_PF if is_hu else _PUSH_PF
    if not is_hu and pos in ("SB", "BB"):
        push_set = push_set | _PUSH_BLIND_WIDER

    if faced_shove:
        call_set = _call_set_for_shover()
        if hand_key in call_set:
            if gate_on:
                eq = _preflop_equity_vs_range(my_cards, _shover_range(), gate_samples)
                if eq is not None and eq < call_min:
                    return Action(room_id=req.room_id, action="fold")
            return Action(room_id=req.room_id, action="allin", amount=req.my_stack)
        return Action(room_id=req.room_id, action="fold")

    if hand_key in push_set:
        # first-in shove — 상대 call range 대비 equity 체크.
        # v5.3.1: HU 면 상대가 _HU_CALL_VS_SHOVE 로 더 넓게 call 하므로 gate 기준도 확대.
        gate_call_range = _HU_CALL_VS_SHOVE if is_hu else _BB_CALL_VS_SHOVE
        # HU 에선 shove_min 을 낮춰 적용 (상대 range 가 넓어 equity 가 원래 낮게 나옴).
        gate_shove_min = shove_min - 0.05 if is_hu else shove_min
        if gate_on and raise_cnt == 0:
            eq = _preflop_equity_vs_range(my_cards, gate_call_range, gate_samples)
            # call range 는 매우 타이트라 equity 낮을 수 있음 — shove 후에도 fold equity 있으므로
            # 기준은 shove_min.
            if eq is not None and eq < gate_shove_min:
                # fold 대신 check 가능하면 check, 아니면 fold.
                if req.to_call == 0:
                    return Action(room_id=req.room_id, action="check")
                return Action(room_id=req.room_id, action="fold")
        # raise_cnt>=1 이면 상대가 이미 raise 했으니 더 타이트 range 기준.
        if gate_on and raise_cnt >= 1:
            eq = _preflop_equity_vs_range(my_cards, _shover_range(), gate_samples)
            if eq is not None and eq < shove_min:
                return Action(room_id=req.room_id, action="fold")
        return Action(room_id=req.room_id, action="allin", amount=req.my_stack)
    if req.to_call == 0:
        return Action(room_id=req.room_id, action="check")
    return Action(room_id=req.room_id, action="fold")
