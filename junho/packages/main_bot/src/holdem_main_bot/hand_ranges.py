"""프리플롭 진입 판정용 스타팅 핸드 레인지.

169개 스타팅 핸드 클래스 중 equity 기준 상위 ~300 combos 에 해당하는
클래스를 정의한다. `is_top_300` 으로 두 홀카드가 이 레인지에 속하는지
판정한다.

Combo count: pair=6, suited=4, offsuit=12.
구성: pairs(78) + suited(108) + offsuit(120) = 306 combos.
"""

_RANK_ORDER = "23456789TJQKA"
_RANK_INDEX = {r: i for i, r in enumerate(_RANK_ORDER)}


_TOP_300: frozenset[str] = frozenset(
    {
        "22", "33", "44", "55", "66", "77", "88", "99",
        "TT", "JJ", "QQ", "KK", "AA",
        "A2s", "A3s", "A4s", "A5s", "A6s", "A7s", "A8s", "A9s",
        "ATs", "AJs", "AQs", "AKs",
        "K9s", "KTs", "KJs", "KQs",
        "Q9s", "QTs", "QJs",
        "J9s", "JTs",
        "T9s",
        "98s", "87s", "76s", "65s", "54s",
        "ATo", "AJo", "AQo", "AKo",
        "KTo", "KJo", "KQo",
        "QTo", "QJo",
        "JTo",
    }
)


def _hand_key(c1: str, c2: str) -> str:
    r1, s1 = c1[0], c1[1]
    r2, s2 = c2[0], c2[1]
    if _RANK_INDEX[r1] >= _RANK_INDEX[r2]:
        high, low = r1, r2
    else:
        high, low = r2, r1
    if high == low:
        return high + low
    return high + low + ("s" if s1 == s2 else "o")


def is_top_300(c1: str, c2: str) -> bool:
    return _hand_key(c1, c2) in _TOP_300
