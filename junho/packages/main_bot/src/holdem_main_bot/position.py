"""포지션 감지 / 포스트플롭 IP 판정.

BOT_REFERENCE.md §4 2~9명 포지션 테이블을 EP/MP/LP/SB/BB 의 5개 클래스로
축소 매핑한다. 실 서버가 보내는 `seat` 값(btn/sb/bb/utg/utg1/mp/mp1/hj/co)
은 활성 인원수에 따라 같은 문자열이라도 상대적 위치가 다르므로,
`active_count` 를 이용해 런타임에 분류한다.
"""

from __future__ import annotations

from typing import Any, Literal

Position = Literal["EP", "MP", "LP", "SB", "BB"]

# 활성 인원수 → {서버 seat → 우리 포지션 클래스}
_MAP: dict[int, dict[str, Position]] = {
    2: {"btn": "LP", "bb": "BB"},
    3: {"btn": "LP", "sb": "SB", "bb": "BB"},
    4: {"btn": "LP", "sb": "SB", "bb": "BB", "utg": "EP"},
    5: {"btn": "LP", "sb": "SB", "bb": "BB", "utg": "EP", "co": "LP"},
    6: {"btn": "LP", "sb": "SB", "bb": "BB", "utg": "EP", "hj": "MP", "co": "LP"},
    7: {
        "btn": "LP", "sb": "SB", "bb": "BB",
        "utg": "EP", "mp": "MP", "hj": "MP", "co": "LP",
    },
    8: {
        "btn": "LP", "sb": "SB", "bb": "BB",
        "utg": "EP", "utg1": "EP", "mp": "MP", "hj": "MP", "co": "LP",
    },
    9: {
        "btn": "LP", "sb": "SB", "bb": "BB",
        "utg": "EP", "utg1": "EP", "mp": "MP", "mp1": "MP", "hj": "MP", "co": "LP",
    },
}

# 포스트플롭 액션 순서 (SB → BB → EP → MP → LP → LP(BTN))
# 실질적으로는 BTN 이 항상 last-to-act. 단순화: LP > MP > EP > BB > SB 순으로 IP.
_POS_ORDER: dict[Position, int] = {"SB": 0, "BB": 1, "EP": 2, "MP": 3, "LP": 4}


def _player_dict(p: Any) -> dict[str, Any]:
    if hasattr(p, "model_dump"):
        return p.model_dump()
    return dict(p)


def active_count(players: list[Any]) -> int:
    """`status != 'eliminated'` 인 플레이어 수."""
    n = 0
    for p in players:
        d = _player_dict(p)
        if d.get("status") != "eliminated":
            n += 1
    return n


def classify_position(seat: str, players: list[Any]) -> Position:
    """`seat` 와 현재 활성 인원으로 EP/MP/LP/SB/BB 중 하나 반환.

    매핑에 없는 인원수(1명 혹은 10명 이상)는 가장 가까운 쪽으로 폴백.
    """
    n = active_count(players)
    if n < 2:
        n = 2
    if n > 9:
        n = 9
    mapping = _MAP.get(n, _MAP[9])
    pos = mapping.get(seat)
    if pos is not None:
        return pos
    # 안전망: 알 수 없는 seat 문자열은 MP 로.
    if seat == "sb":
        return "SB"
    if seat == "bb":
        return "BB"
    if seat in {"btn", "co"}:
        return "LP"
    if seat in {"hj", "mp", "mp1"}:
        return "MP"
    return "EP"


def is_in_position(my_pos: Position, vs_pos: Position) -> bool:
    """내가 vs_pos 상대 대비 IP(포스트플롭 나중 액션) 인지."""
    return _POS_ORDER[my_pos] > _POS_ORDER[vs_pos]
