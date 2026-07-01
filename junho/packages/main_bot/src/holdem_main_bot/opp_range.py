"""상대 홀카드 레인지 추정.

`action_history` 를 보고 살아있는 상대 중 가장 공격적인 플레이어('주요 위협')
하나를 골라 프리플롭 첫 액션 기준으로 tier 분류 후, 해당 tier 에 속하는
169 핸드 클래스를 실제 `(card1, card2)` combo 리스트로 확장.

MVP 한계:
- 프리플롭 액션만 반영. 포스트플롭 액션 기반 레인지 업데이트는 다음 PR.
- 멀티웨이는 위협 1명만 계산에 반영 (나머지 무시).

반환된 combo 리스트는 `app/strategy/equity.py::equity_mc` 의 `opp_combos` 로 전달.
"""

from __future__ import annotations

from itertools import combinations
from typing import Literal

from holdem_core.models.events import ActionRequest

_RANKS = "23456789TJQKA"
_SUITS = "shdc"
_FULL_DECK: tuple[str, ...] = tuple(r + s for r in _RANKS for s in _SUITS)
_RANK_INDEX = {r: i for i, r in enumerate(_RANKS)}

Tier = Literal["top10", "top20", "top40", "any"]

# 169 핸드 클래스 키 (rank + rank + 's'/'o', 페어는 rank+rank).
# top10: 프리미엄 — JJ+, AK, AQs, AJs, KQs.
TIER_TOP10: frozenset[str] = frozenset(
    {
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "AKs",
        "AKo",
        "AQs",
        "AQo",
        "AJs",
        "KQs",
    }
)

# top20: 표준 오픈레이즈 레인지.
TIER_TOP20: frozenset[str] = TIER_TOP10 | frozenset(
    {
        "99",
        "88",
        "77",
        "AJo",
        "ATs",
        "ATo",
        "KQo",
        "KJs",
        "KJo",
        "KTs",
        "QJs",
        "QJo",
        "QTs",
        "JTs",
    }
)

# top40: 콜 레인지. 작은 페어 + 수트 에이스 + 수트 커넥터 등.
TIER_TOP40: frozenset[str] = TIER_TOP20 | frozenset(
    {
        "66",
        "55",
        "44",
        "33",
        "22",
        "A9s",
        "A8s",
        "A7s",
        "A6s",
        "A5s",
        "A4s",
        "A3s",
        "A2s",
        "K9s",
        "Q9s",
        "J9s",
        "T9s",
        "98s",
        "87s",
        "76s",
        "65s",
        "54s",
    }
)


def _hand_key(c1: str, c2: str) -> str:
    """(Ah, Kh) → 'AKs', (Ah, Kd) → 'AKo', (Ah, Ac) → 'AA'."""
    r1, s1 = c1[0], c1[1]
    r2, s2 = c2[0], c2[1]
    if _RANK_INDEX[r1] >= _RANK_INDEX[r2]:
        high, low = r1, r2
    else:
        high, low = r2, r1
    if high == low:
        return high + low
    return high + low + ("s" if s1 == s2 else "o")


def _tier_set(tier: Tier) -> frozenset[str] | None:
    if tier == "top10":
        return TIER_TOP10
    if tier == "top20":
        return TIER_TOP20
    if tier == "top40":
        return TIER_TOP40
    return None  # "any"


def combos_from_keys(keys: frozenset[str], dead_cards: set[str]) -> list[tuple[str, str]]:
    """임의 hand_key 집합 → 실제 (card1, card2) combo 리스트.

    `dead_cards` 는 내 홀카드 + 보드 등 이미 알려진 카드. 공용 유틸.
    tournament 의 push/call 레인지 → combo 로 확장할 때 사용.
    """
    remaining = [c for c in _FULL_DECK if c not in dead_cards]
    out: list[tuple[str, str]] = []
    for c1, c2 in combinations(remaining, 2):
        if _hand_key(c1, c2) in keys:
            out.append((c1, c2))
    return out


def tier_combos(tier: Tier, dead_cards: set[str]) -> list[tuple[str, str]]:
    """tier 에 속하는 169 클래스를 실제 (card1, card2) combo 리스트로 확장.

    `dead_cards` (내 홀카드 + 보드 + 쇼다운 공개 등 확정된 카드) 에 포함된
    카드를 쓴 combo 는 제외.

    tier='any' 이거나 레인지 집합이 비어 있으면 덱에서 가능한 모든 combo 반환
    (사실상 필터링 없음 — 호출자는 None 으로 간주하는 게 더 효율적).
    """
    class_set = _tier_set(tier)
    remaining = [c for c in _FULL_DECK if c not in dead_cards]
    combos: list[tuple[str, str]] = []

    if class_set is None:
        for c1, c2 in combinations(remaining, 2):
            combos.append((c1, c2))
        return combos

    for c1, c2 in combinations(remaining, 2):
        if _hand_key(c1, c2) in class_set:
            combos.append((c1, c2))
    return combos


def _preflop_actions(history: list[dict[str, object]], player: str) -> list[dict[str, object]]:
    return [a for a in history if a.get("phase") == "preflop" and a.get("player") == player]


_TIER_ORDER: tuple[Tier, ...] = ("top10", "top20", "top40", "any")

# v5.4: 누적 profile 의 high-volume 시그널 임계.
# 17K핸드 분석 결과 너구리쿤(SD승률 62%, 3bet 18%) 같은 상대가 'any' tier 로
# 떨어져서 primary_threat 으로 한 번도 안 잡히던 버그 발견.
_PROFILE_FLOOR_HANDS_TOP20 = 100  # n>=100 부터 누적 시그널 신뢰
_PROFILE_FLOOR_HANDS_TOP10 = 500
_PROFILE_FLOOR_SD_WIN_TOP20 = 0.55  # SD win rate >= 0.55 + n>=100 → top20 floor
_PROFILE_FLOOR_SD_WIN_TOP10 = 0.60
_PROFILE_FLOOR_THREEBET_RATE = 0.10  # 3bet rate >= 10% + n>=100 → top20 floor
_PROFILE_FLOOR_VPIP_WIDE = 0.50  # VPIP >= 50% + n>=100 → top20 floor (LAG)


def _tier_strength(t: Tier) -> int:
    """top10=3, top20=2, top40=1, any=0 — 큰 게 더 좁은(=강한) range."""
    return {"top10": 3, "top20": 2, "top40": 1, "any": 0}[t]


def _max_tier(a: Tier, b: Tier) -> Tier:
    """두 tier 중 더 좁은(=강한) 쪽."""
    return a if _tier_strength(a) >= _tier_strength(b) else b


def _tighten_tier(t: Tier) -> Tier:
    """top40 → top20 → top10 (더 좁은 range)."""
    idx = _TIER_ORDER.index(t)
    if idx <= 0:
        return t
    return _TIER_ORDER[idx - 1]


def _widen_tier(t: Tier) -> Tier:
    """top10 → top20 → top40 → any (더 넓은 range)."""
    idx = _TIER_ORDER.index(t)
    if idx >= len(_TIER_ORDER) - 1:
        return t
    return _TIER_ORDER[idx + 1]


def _profile_floor_tier(profile: dict[str, object]) -> Tier:
    """누적 profile 시그널만으로 결정되는 minimum tier (= floor).

    v5.4 신설. 이 floor 가 'any' 보다 강하면 estimate_tier 의 base 를 강제로
    그 floor 로 끌어올린다.

    시그널 (모두 hands_seen >= N 조건부):
    - SD win rate >= 0.60 + n >= 500    → top10
    - SD win rate >= 0.55 + n >= 100    → top20
    - 3bet rate   >= 0.10 + n >= 100    → top20
    - VPIP        >= 0.50 + n >= 100    → top20  (extreme LAG, range 알 수 없음)
    """
    try:
        n = int(profile.get("hands_seen", 0) or 0)
    except (TypeError, ValueError):
        return "any"
    if n < _PROFILE_FLOOR_HANDS_TOP20:
        return "any"

    floor: Tier = "any"

    # showdown win rate
    try:
        sd_n = int(profile.get("showdown_n") or profile.get("showdowns") or 0)
        sd_won = int(profile.get("showdown_won_n") or 0)
    except (TypeError, ValueError):
        sd_n = sd_won = 0
    if sd_n >= 30:
        sd_wr = sd_won / sd_n
        if sd_wr >= _PROFILE_FLOOR_SD_WIN_TOP10 and n >= _PROFILE_FLOOR_HANDS_TOP10:
            floor = _max_tier(floor, "top10")
        elif sd_wr >= _PROFILE_FLOOR_SD_WIN_TOP20:
            floor = _max_tier(floor, "top20")

    # 3bet rate (preflop aggression)
    try:
        threebet_n = int(profile.get("threebet_n", 0) or 0)
    except (TypeError, ValueError):
        threebet_n = 0
    if n > 0 and (threebet_n / n) >= _PROFILE_FLOOR_THREEBET_RATE:
        floor = _max_tier(floor, "top20")

    # VPIP (LAG = wide + winning)
    try:
        vpip_n = int(profile.get("vpip_n", 0) or 0)
    except (TypeError, ValueError):
        vpip_n = 0
    if n > 0 and (vpip_n / n) >= _PROFILE_FLOOR_VPIP_WIDE:
        floor = _max_tier(floor, "top20")

    return floor


def estimate_tier(
    player: str,
    history: list[dict[str, object]],
    profile: dict[str, object] | None = None,
    profile_min_hands: int = 15,
    profile_vpip_tight: float = 0.18,
    profile_vpip_wide: float = 0.40,
) -> Tier:
    """해당 플레이어의 프리플롭 액션 시퀀스로 tier 분류 + 프로필로 보정.

    기본 규칙 (이번 핸드 history):
    - 2회 이상 레이즈 (3-bet+) → top10
    - 1회 레이즈 → top20
    - 콜 (레이즈 없이) → top40
    - 체크/림프/액션 없음 → any

    v2: 누적 프로필(`.debug/opponent_profiles.json`) 이 충분히 크면 VPIP 로 보정:
    - tight(VPIP<0.18) → tier 한 단계 좁힘
    - wide(VPIP>0.40) → tier 한 단계 넓힘
    """
    acts = _preflop_actions(history, player)
    raise_count = sum(1 for a in acts if a.get("action") in ("raise", "allin"))
    has_call = any(a.get("action") == "call" for a in acts)

    if not acts:
        base: Tier = "any"
    elif raise_count >= 2:
        base = "top10"
    elif raise_count == 1:
        base = "top20"
    elif has_call:
        base = "top40"
    else:
        base = "any"

    if profile is None:
        return base

    # v5.4: 누적 profile floor — 이번 핸드 액션 무관하게 high-volume + winning
    # 상대는 minimum tier 부여. 너구리쿤 같은 상대가 'any' 로 떨어져 primary_threat
    # 으로 한 번도 인식되지 않던 버그(0건/17K핸드) fix.
    floor = _profile_floor_tier(profile)
    base = _max_tier(base, floor)

    try:
        hands_seen = int(profile.get("hands_seen", 0) or 0)
    except (TypeError, ValueError):
        return base
    if hands_seen < profile_min_hands:
        return base

    vpip_n = profile.get("vpip_n") or profile.get("vpip") or 0
    try:
        if isinstance(vpip_n, (int, float)) and vpip_n <= 1.0 and vpip_n >= 0:
            # "vpip" 이미 비율일 수도 있음 (summary.py 스키마 참조)
            vpip = float(vpip_n)
        else:
            vpip = float(vpip_n) / max(hands_seen, 1)
    except (TypeError, ValueError):
        return base

    if vpip < profile_vpip_tight:
        return _tighten_tier(base)
    if vpip > profile_vpip_wide:
        return _widen_tier(base)
    return base


def primary_threat(
    req: ActionRequest,
    profiles: dict[str, dict[str, object]] | None = None,
    profile_min_hands: int = 15,
    profile_vpip_tight: float = 0.18,
    profile_vpip_wide: float = 0.40,
) -> tuple[str | None, Tier]:
    """살아있는 상대 중 가장 공격적인 1명의 (이름, tier).

    아무도 공격적이지 않으면 (None, 'any').
    v2: profiles dict (name → OppProfile) 있으면 estimate_tier 에 전달.
    """
    my_seat = req.seat
    history = [a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in req.action_history]

    # 내가 아닌 살아있는 상대만 후보
    active_opps: list[str] = []
    for p in req.players:
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if p_dict.get("position") == my_seat:
            continue
        if p_dict.get("status") != "active":
            continue
        name = p_dict.get("name")
        if isinstance(name, str):
            active_opps.append(name)

    best_name: str | None = None
    best_tier: Tier = "any"
    best_hands: int = -1
    for name in active_opps:
        prof = (profiles or {}).get(name)
        t = estimate_tier(
            name,
            history,
            profile=prof,
            profile_min_hands=profile_min_hands,
            profile_vpip_tight=profile_vpip_tight,
            profile_vpip_wide=profile_vpip_wide,
        )
        # v5.4: tie-break — 동률 tier 면 누적 hands_seen 큰 쪽 우선.
        # 17K핸드 누적 너구리쿤 vs 신참 LAG 가 같은 top20 일 때, 너구리쿤이 더
        # 신뢰 가능한 위협이므로 primary 로 잡는다.
        try:
            cur_hands = int((prof or {}).get("hands_seen", 0) or 0)
        except (TypeError, ValueError):
            cur_hands = 0
        ts_cur, ts_best = _tier_strength(t), _tier_strength(best_tier)
        if ts_cur > ts_best or (ts_cur == ts_best and cur_hands > best_hands):
            best_tier = t
            best_name = name
            best_hands = cur_hands

    if best_tier == "any":
        return None, "any"
    return best_name, best_tier


def _active_opponents(req: ActionRequest) -> list[str]:
    """내가 아닌 활성(폴드/탈락 아님) 상대 이름 목록."""
    my_seat = req.seat
    opps: list[str] = []
    for p in req.players:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        if d.get("position") == my_seat:
            continue
        status = d.get("status")
        if status in ("folded", "eliminated"):
            continue
        name = d.get("name")
        if isinstance(name, str):
            opps.append(name)
    return opps


def all_opp_combos(
    req: ActionRequest,
    dead_cards: set[str] | None = None,
    profiles: dict[str, dict[str, object]] | None = None,
    profile_min_hands: int = 15,
    profile_vpip_tight: float = 0.18,
    profile_vpip_wide: float = 0.40,
) -> list[tuple[str, list[tuple[str, str]] | None]]:
    """활성 상대별 (name, combos) 리스트. combos=None 이면 랜덤 덱.

    멀티웨이 equity_mc_multi 의 `opp_combos_list` 입력용.
    v2: profiles 있으면 상대별 VPIP 기반 tier 보정.
    """
    if dead_cards is None:
        dead_cards = set(req.your_cards) | set(req.community_cards)

    history = [a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in req.action_history]

    out: list[tuple[str, list[tuple[str, str]] | None]] = []
    for name in _active_opponents(req):
        prof = (profiles or {}).get(name)
        tier = estimate_tier(
            name,
            history,
            profile=prof,
            profile_min_hands=profile_min_hands,
            profile_vpip_tight=profile_vpip_tight,
            profile_vpip_wide=profile_vpip_wide,
        )
        if tier == "any":
            out.append((name, None))
            continue
        combos = tier_combos(tier, dead_cards)
        out.append((name, combos if combos else None))
    return out


def _combo_strength_score(combo: tuple[str, str], board: list[str]) -> int:
    """combo + board 의 category_rank (1 hi-card ~ 9 straight_flush).

    board 가 비어 있으면 프리플롭으로 간주하므로 호출자는 board 가 3+ 일 때만
    쓸 것. 내부 사용 전용.
    """
    from holdem_core.hand_eval import classify_hand

    cards = list(combo) + list(board)
    cls = classify_hand(cards)
    rank = cls["category_rank"]
    return int(rank) if isinstance(rank, int) else 0


def narrow_by_postflop(
    combos: list[tuple[str, str]],
    player: str,
    history: list[dict[str, object]],
    board: list[str],
) -> list[tuple[str, str]]:
    """player 의 포스트플롭 액션(raise/allin) 기반으로 combos 필터링.

    - flop raise/allin  → category_rank >= 2 (top pair급 / one_pair+)
    - turn raise/allin  → category_rank >= 3 (two_pair+)
    - river raise/allin → category_rank >= 3 (two_pair+)
    - 단순 call 은 필터링하지 않음 (레인지 그대로)

    `board` 가 3장 미만이면 필터링하지 않음.
    """
    if len(board) < 3:
        return combos

    def _max_aggro_rank_on_phase(phase: str) -> int | None:
        # 가장 강한 필터 임계치 찾기
        for a in history:
            if a.get("player") != player:
                continue
            if a.get("phase") != phase:
                continue
            act = a.get("action")
            if act in ("raise", "allin"):
                return 1
        return None

    # 임계치 선정 (phase 별): (min_category_rank, board_snapshot)
    thresholds: list[tuple[int, list[str]]] = []
    flop_board = board[:3]
    if _max_aggro_rank_on_phase("flop") is not None:
        thresholds.append((2, flop_board))  # top pair+ (one_pair 이상)
    if len(board) >= 4 and _max_aggro_rank_on_phase("turn") is not None:
        thresholds.append((3, board[:4]))
    if len(board) >= 5 and _max_aggro_rank_on_phase("river") is not None:
        thresholds.append((3, board[:5]))

    if not thresholds:
        return combos

    filtered: list[tuple[str, str]] = []
    for c in combos:
        ok = True
        for min_rank, b in thresholds:
            if _combo_strength_score(c, b) < min_rank:
                ok = False
                break
        if ok:
            filtered.append(c)
    # 과도하게 좁혀져 0 combo 가 되면 원본 반환 (equity MC 실패 방지).
    return filtered if filtered else combos


def infer_opp_combos(
    req: ActionRequest,
    dead_cards: set[str] | None = None,
    profiles: dict[str, dict[str, object]] | None = None,
    profile_min_hands: int = 15,
    profile_vpip_tight: float = 0.18,
    profile_vpip_wide: float = 0.40,
) -> tuple[list[tuple[str, str]] | None, str | None, Tier]:
    """주요 위협 레인지를 combo 리스트로 반환.

    반환: (combos, threat_name, tier).
    - 위협 없음 (tier='any') → (None, None, 'any') : 호출자는 랜덤 샘플링 사용.
    - 위협 있음 → (combos, name, tier).

    `dead_cards` 가 None 이면 `req.your_cards + req.community_cards` 로 세팅.
    v2: profiles 있으면 상대 VPIP 기반 tier 보정.
    """
    name, tier = primary_threat(
        req,
        profiles=profiles,
        profile_min_hands=profile_min_hands,
        profile_vpip_tight=profile_vpip_tight,
        profile_vpip_wide=profile_vpip_wide,
    )
    if tier == "any":
        return None, None, "any"

    if dead_cards is None:
        dead_cards = set(req.your_cards) | set(req.community_cards)

    combos = tier_combos(tier, dead_cards)
    if not combos:
        return None, name, tier
    return combos, name, tier
