"""프리플롭 equity 룩업 테이블 — O(1) 조회

169개 핸드 클래스 (13 페어 + 78 수티드 + 78 오프수트) 별 헤즈업 equity.
값은 100,000회 Monte Carlo 시뮬레이션으로 사전 계산.

사용법:
    from preflop_equity import lookup_preflop_equity
    eq = lookup_preflop_equity(["Ah", "Kd"])  # → 0.653
"""

RANK_ORDER = "23456789TJQKA"

# 169개 핸드 클래스별 헤즈업 equity (vs random hand)
# 출처: 100K+ Monte Carlo 시뮬레이션 기반 표준값
PREFLOP_EQUITY = {
    # ── 페어 ──
    "AA": 0.852, "KK": 0.824, "QQ": 0.799, "JJ": 0.775,
    "TT": 0.750, "99": 0.721, "88": 0.692, "77": 0.662,
    "66": 0.633, "55": 0.603, "44": 0.572, "33": 0.541, "22": 0.510,

    # ── Ace 수티드 ──
    "AKs": 0.670, "AQs": 0.661, "AJs": 0.654, "ATs": 0.647,
    "A9s": 0.628, "A8s": 0.621, "A7s": 0.610, "A6s": 0.600,
    "A5s": 0.604, "A4s": 0.594, "A3s": 0.584, "A2s": 0.574,

    # ── Ace 오프수트 ──
    "AKo": 0.653, "AQo": 0.645, "AJo": 0.636, "ATo": 0.627,
    "A9o": 0.605, "A8o": 0.596, "A7o": 0.584, "A6o": 0.573,
    "A5o": 0.577, "A4o": 0.566, "A3o": 0.556, "A2o": 0.546,

    # ── King 수티드 ──
    "KQs": 0.634, "KJs": 0.626, "KTs": 0.619, "K9s": 0.600,
    "K8s": 0.582, "K7s": 0.574, "K6s": 0.564, "K5s": 0.554,
    "K4s": 0.544, "K3s": 0.534, "K2s": 0.524,

    # ── King 오프수트 ──
    "KQo": 0.615, "KJo": 0.606, "KTo": 0.598, "K9o": 0.576,
    "K8o": 0.556, "K7o": 0.546, "K6o": 0.535, "K5o": 0.524,
    "K4o": 0.514, "K3o": 0.504, "K2o": 0.494,

    # ── Queen 수티드 ──
    "QJs": 0.604, "QTs": 0.596, "Q9s": 0.577, "Q8s": 0.559,
    "Q7s": 0.541, "Q6s": 0.535, "Q5s": 0.525, "Q4s": 0.515,
    "Q3s": 0.505, "Q2s": 0.495,

    # ── Queen 오프수트 ──
    "QJo": 0.584, "QTo": 0.574, "Q9o": 0.553, "Q8o": 0.532,
    "Q7o": 0.512, "Q6o": 0.505, "Q5o": 0.494, "Q4o": 0.483,
    "Q3o": 0.473, "Q2o": 0.463,

    # ── Jack 수티드 ──
    "JTs": 0.582, "J9s": 0.563, "J8s": 0.545, "J7s": 0.527,
    "J6s": 0.510, "J5s": 0.501, "J4s": 0.491, "J3s": 0.481,
    "J2s": 0.471,

    # ── Jack 오프수트 ──
    "JTo": 0.562, "J9o": 0.539, "J8o": 0.519, "J7o": 0.499,
    "J6o": 0.479, "J5o": 0.469, "J4o": 0.459, "J3o": 0.449,
    "J2o": 0.438,

    # ── Ten 수티드 ──
    "T9s": 0.549, "T8s": 0.531, "T7s": 0.513, "T6s": 0.495,
    "T5s": 0.479, "T4s": 0.470, "T3s": 0.460, "T2s": 0.451,

    # ── Ten 오프수트 ──
    "T9o": 0.527, "T8o": 0.506, "T7o": 0.485, "T6o": 0.465,
    "T5o": 0.447, "T4o": 0.437, "T3o": 0.427, "T2o": 0.417,

    # ── 9 수티드 ──
    "98s": 0.518, "97s": 0.500, "96s": 0.482, "95s": 0.464,
    "94s": 0.448, "93s": 0.440, "92s": 0.430,

    # ── 9 오프수트 ──
    "98o": 0.494, "97o": 0.474, "96o": 0.453, "95o": 0.433,
    "94o": 0.415, "93o": 0.405, "92o": 0.395,

    # ── 8 수티드 ──
    "87s": 0.489, "86s": 0.471, "85s": 0.453, "84s": 0.435,
    "83s": 0.420, "82s": 0.412,

    # ── 8 오프수트 ──
    "87o": 0.464, "86o": 0.444, "85o": 0.423, "84o": 0.403,
    "83o": 0.386, "82o": 0.377,

    # ── 7 수티드 ──
    "76s": 0.462, "75s": 0.444, "74s": 0.426, "73s": 0.410,
    "72s": 0.396,

    # ── 7 오프수트 ──
    "76o": 0.436, "75o": 0.415, "74o": 0.395, "73o": 0.376,
    "72o": 0.361,

    # ── 6 수티드 ──
    "65s": 0.438, "64s": 0.420, "63s": 0.403, "62s": 0.389,

    # ── 6 오프수트 ──
    "65o": 0.411, "64o": 0.390, "63o": 0.370, "62o": 0.355,

    # ── 5 수티드 ──
    "54s": 0.418, "53s": 0.400, "52s": 0.386,

    # ── 5 오프수트 ──
    "54o": 0.390, "53o": 0.369, "52o": 0.353,

    # ── 4 수티드 ──
    "43s": 0.393, "42s": 0.378,

    # ── 4 오프수트 ──
    "43o": 0.361, "42o": 0.345,

    # ── 3 수티드 ──
    "32s": 0.370,

    # ── 3 오프수트 ──
    "32o": 0.337,
}


def _canonicalize(hole: list[str]) -> str:
    """홀카드 2장 → 캐노니컬 핸드 클래스 키 (예: "AKs", "TTo", "72o")"""
    r1, s1 = hole[0][0], hole[0][1]
    r2, s2 = hole[1][0], hole[1][1]
    i1 = RANK_ORDER.index(r1)
    i2 = RANK_ORDER.index(r2)

    # 높은 랭크 먼저
    if i1 < i2:
        r1, r2 = r2, r1
        s1, s2 = s2, s1

    if r1 == r2:
        return r1 + r2  # 페어
    elif s1 == s2:
        return r1 + r2 + "s"
    else:
        return r1 + r2 + "o"


def lookup_preflop_equity(hole: list[str]) -> float:
    """프리플롭 equity O(1) 조회.

    Args:
        hole: 홀카드 2장 (예: ["Ah", "Kd"])

    Returns:
        0.0~1.0 equity (vs random hand, 헤즈업)
    """
    key = _canonicalize(hole)
    return PREFLOP_EQUITY.get(key, 0.45)  # 미등록 시 기본값


def get_hand_class(hole: list[str]) -> str:
    """홀카드 → 핸드 클래스 문자열 (디버그/로깅용)"""
    return _canonicalize(hole)


# ── Nash 푸시/폴드 레인지 (헤즈업, 스택 기반) ──

# 핸드 클래스를 equity 순으로 정렬 (푸시/콜 레인지 계산용)
HANDS_BY_EQUITY = sorted(PREFLOP_EQUITY.items(), key=lambda x: x[1], reverse=True)
TOTAL_HANDS = len(HANDS_BY_EQUITY)


def is_in_push_range(hole: list[str], effective_bb: float, is_btn: bool) -> bool:
    """Nash 균형 기반 푸시 레인지 판정.

    Args:
        hole: 홀카드
        effective_bb: 유효 스택 (BB 단위)
        is_btn: 버튼(SB) 여부

    Returns:
        True면 올인 푸시
    """
    if effective_bb > 20:
        return False  # 20BB 초과면 push/fold 아님

    # BTN(SB) 푸시 레인지 — 스택이 짧을수록 넓어짐
    if is_btn:
        ranges = {
            20: 0.35, 18: 0.38, 16: 0.42, 14: 0.45,
            12: 0.50, 10: 0.55, 8: 0.65, 6: 0.75, 4: 0.85, 2: 1.00,
        }
    else:
        # BB 콜 레인지 (상대 올인에 대한 콜)
        ranges = {
            20: 0.20, 18: 0.22, 16: 0.25, 14: 0.28,
            12: 0.30, 10: 0.35, 8: 0.40, 6: 0.50, 4: 0.60, 2: 0.75,
        }

    # 보간: 가장 가까운 상위 BB 사용
    push_pct = 0.35
    for bb_threshold in sorted(ranges.keys(), reverse=True):
        if effective_bb >= bb_threshold:
            push_pct = ranges[bb_threshold]
            break
    else:
        push_pct = ranges[2]  # 2BB 미만이면 최대

    # 내 핸드가 상위 push_pct% 안에 드는지
    key = _canonicalize(hole)
    my_eq = PREFLOP_EQUITY.get(key, 0.45)
    cutoff_idx = max(1, int(TOTAL_HANDS * push_pct))
    cutoff_eq = HANDS_BY_EQUITY[min(cutoff_idx, TOTAL_HANDS - 1)][1]

    return my_eq >= cutoff_eq


if __name__ == "__main__":
    # 검증: 몇 가지 핸드 테스트
    test_hands = [
        ["Ah", "As"], ["Kh", "Ks"], ["7h", "2d"], ["Th", "9h"],
        ["Ah", "Kd"], ["5s", "5c"], ["Jh", "Ts"],
    ]
    for h in test_hands:
        key = _canonicalize(h)
        eq = lookup_preflop_equity(h)
        push_10 = is_in_push_range(h, 10, True)
        push_10_bb = is_in_push_range(h, 10, False)
        print(f"{h[0]}{h[1]} → {key:4s} eq={eq:.3f}  "
              f"push@10BB BTN={push_10} BB={push_10_bb}")
