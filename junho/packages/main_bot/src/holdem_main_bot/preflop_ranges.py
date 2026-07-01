"""포지션별 프리플롭 레인지(open / 3bet / 4bet / call).

169 핸드 클래스 키 표기는 `opp_range._hand_key` 와 동일 ('AA', 'AKs', 'AKo').
레인지 테이블은 GTO 참조 차트(Upswing/PokerTracker 표준)를 보수적으로
단순화한 버전.

NOTE:
- SB 는 LP 보다 약간 타이트 (스틸 범위이지만 OOP 페널티).
- BB 에서의 open 은 존재하지 않음 (항상 defend/3bet).
- 4bet 은 value only 기본형. 블러프 4bet 은 지양 (분산↑).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from holdem_main_bot.opp_range import _hand_key as _opp_hand_key

if TYPE_CHECKING:
    from holdem_main_bot.position import Position


def hand_key(c1: str, c2: str) -> str:
    """'Ah','Kh' → 'AKs'. opp_range._hand_key 공개판."""
    return _opp_hand_key(c1, c2)


# ─── Open raise ranges ────────────────────────────────────────────────────────

# v5.2: VPIP 17.7% / PFR 15.2% 실측 → desperate 구간 진입 24% (블라인드 갉아먹힘).
# LP 27% → 40%, SB 23% → 30%, EP 12% → 14% 로 확장. 표준 TAG (VPIP 22-28%) 영역.

# EP (UTG): ~14%. + 88, AJo (타이트 유지하되 88/AJo 추가).
OPEN_EP: frozenset[str] = frozenset(
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
        "ATs",
        "KQs",
        "KJs",
        "QJs",
        "JTs",
        "AKo",
        "AQo",
        "AJo",
    }
)

# MP: ~20%. + 77, KTs, QTs, T9s, 98s, KQo, KJo.
OPEN_MP: frozenset[str] = OPEN_EP | frozenset(
    {
        "77",
        "A9s",
        "A8s",
        "KTs",
        "QTs",
        "J9s",
        "T9s",
        "98s",
        "KQo",
        "KJo",
    }
)

# LP (CO/BTN): ~40%. MP 기준 + 소형 페어, 넓은 Ax, Kx, Qx, suited connectors 전체.
OPEN_LP: frozenset[str] = OPEN_MP | frozenset(
    {
        "66",
        "55",
        "44",
        "33",
        "22",
        # Suited Ax 전부
        "A7s",
        "A6s",
        "A5s",
        "A4s",
        "A3s",
        "A2s",
        # Offsuit Ax 확장 (BTN 스틸)
        "ATo",
        "A9o",
        "A8o",
        "A7o",
        "A6o",
        "A5o",
        "A4o",
        "A3o",
        "A2o",
        # Suited Kx 확장
        "K9s",
        "K8s",
        "K7s",
        "K6s",
        "K5s",
        "K4s",
        "K3s",
        "K2s",
        # Offsuit Kx 확장
        "KTo",
        "K9o",
        # Suited Qx 확장
        "Q9s",
        "Q8s",
        "Q7s",
        "Q6s",
        # Offsuit Q broadway
        "QJo",
        "QTo",
        "Q9o",
        # Suited Jx
        "J8s",
        "J7s",
        # Offsuit Jx
        "JTo",
        "J9o",
        # Suited Tx
        "T8s",
        "T7s",
        "T9o",
        # Suited connectors 전체 (gap 포함)
        "97s",
        "87s",
        "86s",
        "76s",
        "75s",
        "65s",
        "64s",
        "54s",
        "43s",
    }
)

# SB (OOP): ~30%. LP 에서 marginal offsuit + 낮은 gapper 제외.
# OOP 페널티로 3bet 당할 때 불리 → 중간 강도만 남김.
OPEN_SB: frozenset[str] = OPEN_LP - frozenset(
    {
        "A5o",
        "A4o",
        "A3o",
        "A2o",  # 약한 offsuit Ax
        "K6s",
        "K5s",
        "K4s",
        "K3s",
        "K2s",  # 약한 suited Kx
        "K9o",
        "Q7s",
        "Q6s",
        "Q9o",
        "J7s",
        "J9o",
        "T7s",
        "T9o",
        "43s",
        "64s",
        "75s",
        "86s",
        "97s",  # gap/low suited connectors
    }
)

# BB 는 open 안 함 → 빈집합.
OPEN_BB: frozenset[str] = frozenset()


# ─── Heads-up (2-handed) 전용 레인지 ──────────────────────────────────────────
# v5.3: 실측 55게임에서 2등 탈락 25건 (45%). HU 구간 520핸드 중 fold 65.4% →
# blind 으로 스택 갉아먹혀 forced_showdown_dominated 로 자주 탈락.
# 기존 pos_map 은 HU(2명) 를 LP/BB 로 매핑해서 일반 6-max 레인지(OPEN_LP ~40%)
# 를 적용. HU 표준은 BTN 75~85%, BB defend 65~80% 이므로 대폭 확장.

# HU BTN (실제 SB): ~85% combos. 거의 모든 playable. 완전 쓰레기 low offsuit 만 제외.
HU_OPEN_BTN: frozenset[str] = OPEN_LP | frozenset(
    {
        # Offsuit K/Q/J/T/9/8/7/6/5 확장
        "K8o",
        "K7o",
        "K6o",
        "K5o",
        "K4o",
        "K3o",
        "K2o",
        "Q8o",
        "Q7o",
        "Q6o",
        "Q5o",
        "Q4o",
        "Q3o",
        "Q2o",
        "J8o",
        "J7o",
        "J6o",
        "J5o",
        "J4o",
        "J3o",
        "J2o",
        "T8o",
        "T7o",
        "T6o",
        "T5o",
        "T4o",
        "T3o",
        "T2o",
        "98o",
        "97o",
        "96o",
        "95o",
        "94o",
        "93o",
        "92o",
        "87o",
        "86o",
        "85o",
        "84o",
        "76o",
        "75o",
        "74o",
        "65o",
        "64o",
        "54o",
        # Low suited gap 전부
        "53s",
        "52s",
        "42s",
        "32s",
        "63s",
        "62s",
        "74s",
        "73s",
        "85s",
        "84s",
        "96s",
        "95s",
        "T6s",
        "T5s",
        "T4s",
        "J6s",
        "J5s",
        "J4s",
        "J3s",
        "J2s",
        "Q5s",
        "Q4s",
        "Q3s",
        "Q2s",
    }
)

# HU BB defend (vs BTN open): call 범위. ~48% combos. top range 는 3bet 쪽으로.
HU_CALL_BB: frozenset[str] = frozenset(
    {
        # Pairs 22-99 (TT+ 는 3bet 쪽)
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        # Suited Ax (AQs+ 는 3bet)
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
        # Offsuit Ax (AJo 이하; AQo+ 는 3bet)
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
        # Suited Kx
        "KTs",
        "K9s",
        "K8s",
        "K7s",
        "K6s",
        "K5s",
        "K4s",
        "K3s",
        "K2s",
        # Offsuit Kx (KQo+ 는 3bet)
        "KJo",
        "KTo",
        "K9o",
        "K8o",
        "K7o",
        # Suited Qx
        "QJs",
        "QTs",
        "Q9s",
        "Q8s",
        "Q7s",
        "Q6s",
        "Q5s",
        # Offsuit Qx
        "QJo",
        "QTo",
        "Q9o",
        "Q8o",
        # Suited Jx
        "JTs",
        "J9s",
        "J8s",
        "J7s",
        # Offsuit Jx
        "JTo",
        "J9o",
        "J8o",
        # Suited Tx
        "T9s",
        "T8s",
        "T7s",
        # Offsuit Tx
        "T9o",
        "T8o",
        # Suited connectors
        "98s",
        "97s",
        "87s",
        "86s",
        "76s",
        "75s",
        "65s",
        "64s",
        "54s",
        "43s",
    }
)

# HU BB 3bet: value + light bluff. ~18% combos.
HU_3BET_BB: frozenset[str] = frozenset(
    {
        "AA",
        "KK",
        "QQ",
        "JJ",
        "TT",
        "AKs",
        "AQs",
        "AKo",
        "AQo",
        "KQs",
        "KQo",
        "KJs",
        # Light 3bet (blocker / playable OOP)
        "A5s",
        "A4s",
        "A3s",  # 휠 블러프 (A 블로커 + playable)
        "K5s",
        "K4s",
        "76s",
        "65s",  # suited connector bluff
    }
)


def open_range(pos: "Position") -> frozenset[str]:
    if pos == "EP":
        return OPEN_EP
    if pos == "MP":
        return OPEN_MP
    if pos == "LP":
        return OPEN_LP
    if pos == "SB":
        return OPEN_SB
    return OPEN_BB


def hu_open_range() -> frozenset[str]:
    """HU BTN(실제 SB) 전용 open. HU_OPEN_BTN."""
    return HU_OPEN_BTN


def hu_call_range() -> frozenset[str]:
    """HU BB 에서 BTN open 에 defend (call). HU_CALL_BB."""
    return HU_CALL_BB


def hu_three_bet_range() -> frozenset[str]:
    """HU BB 에서 3bet (value + light bluff). HU_3BET_BB."""
    return HU_3BET_BB


# ─── 3-bet ranges ─────────────────────────────────────────────────────────────

# 3bet value: QQ+, AKs, AKo (슬림).
THREE_BET_VALUE: frozenset[str] = frozenset({"AA", "KK", "QQ", "AKs", "AKo"})

# 3bet IP 블러프 섞은 범위: + JJ, AQs, AQo, KQs, AJs 일부.
THREE_BET_IP: frozenset[str] = THREE_BET_VALUE | frozenset(
    {
        "JJ",
        "TT",
        "AQs",
        "AQo",
        "AJs",
        "KQs",
        "KJs",
    }
)

# 3bet OOP: value only (BB/SB 에서 squeeze value).
THREE_BET_OOP: frozenset[str] = THREE_BET_VALUE | frozenset({"JJ", "AQs"})


def three_bet_range(pos: "Position", vs_pos: "Position") -> frozenset[str]:
    """내 포지션 vs 오프너 포지션 조합으로 3bet 레인지."""
    from holdem_main_bot.position import is_in_position

    if is_in_position(pos, vs_pos):
        return THREE_BET_IP
    return THREE_BET_OOP


# ─── 4-bet ranges ─────────────────────────────────────────────────────────────

# 4bet value only (블러프 X).
FOUR_BET_VALUE: frozenset[str] = frozenset({"AA", "KK", "AKs"})


def four_bet_range() -> frozenset[str]:
    return FOUR_BET_VALUE


# ─── Cold-call ranges (vs open) ───────────────────────────────────────────────

# 3bet 은 못 해도 pot-odds 맞으면 call 해볼 만한 범위.
# 중소페어/수티드 커넥터/수티드 에이스 위주 (셋마이닝 + implied odds).
CALL_VS_OPEN_IP: frozenset[str] = frozenset(
    {
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        "AJs",
        "ATs",
        "A9s",
        "A8s",
        "A5s",
        "A4s",
        "A3s",
        "KQs",
        "KJs",
        "KTs",
        "QJs",
        "QTs",
        "JTs",
        "T9s",
        "98s",
        "87s",
        "76s",
        "AQo",
        "AJo",
        "KQo",
    }
)

# v4: BB defense 확장 — KTs, QTs, A9s, AJo, KJo, A9o 추가. loss-patterns.md §C +
# pattern-hunter 보고: counterfactual_wrong_fold 494건 (4.1%) 중 BTN 31% / SB 20%
# 스틸 위치 폴드. BB defense 를 suited broadway + 약한 Ax broadway 까지 확장.
CALL_VS_OPEN_OOP: frozenset[str] = frozenset(
    {
        "99",
        "88",
        "77",
        "66",
        "55",
        "44",
        "33",
        "22",
        "AJs",
        "ATs",
        "A9s",
        "KQs",
        "KJs",
        "KTs",
        "QJs",
        "QTs",
        "JTs",
        "T9s",
        "98s",
        "AQo",
        "AJo",
        "A9o",
        "KQo",
        "KJo",
    }
)


def call_range(pos: "Position", vs_pos: "Position") -> frozenset[str]:
    from holdem_main_bot.position import is_in_position

    if is_in_position(pos, vs_pos):
        return CALL_VS_OPEN_IP
    return CALL_VS_OPEN_OOP


# ─── Limp Isolation (v5 §J) ───────────────────────────────────────────────────
#
# forensics §5 #2: SB/BB 또는 앞 상대가 림프(raise 없이 call) 할 때 LP/BTN 이
# isolation raise 로 치지 않아 limp-pot 이 형성됨 → 드로잉 상대에게 pot-odds
# 제공. LP 에서 림프를 만났을 때 (raise_cnt==0 이되 call_cnt>0) 이 range 로
# iso-raise.
#
# OPEN_LP 에 mid Ax/Kx, speculative suited connector 를 더한 약간 넓은 range.
# Top-pair 적중률 높고 림프 상대 레인지 (pair 낮음, broadway 낮음) 를 타겟.
ISO_LIMP_RANGE: frozenset[str] = OPEN_LP | frozenset(
    {
        "A8o",
        "A7o",
        "A6o",
        "K9o",
        "Q8s",
        "J8s",
        "T8s",
        "97s",
    }
)


def iso_limp_range() -> frozenset[str]:
    """LP/BTN 에서 림프 상대에게 isolate raise 로 들어가는 범위."""
    return ISO_LIMP_RANGE
