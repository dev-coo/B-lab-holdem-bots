"""6-max GTO 프리플랍 차트 룩업 API.

data/preflop_charts.json 을 읽어 `hand × hero × scenario × villain` →
액션("raise"|"call"|"fold"|"allin") 을 반환한다.

혼합 전략(배열 셀 `["raise","fold"]`) 은 균등 랜덤 선택.
"""
import json
import random
from pathlib import Path

RANKS = "23456789TJQKA"

_DATA_PATH = Path(__file__).parent.parent / "data" / "preflop_charts.json"
_CHARTS: dict | None = None


def _load() -> dict:
    global _CHARTS
    if _CHARTS is None:
        with _DATA_PATH.open(encoding="utf-8") as f:
            _CHARTS = json.load(f)
    return _CHARTS


def hand_key(cards: list[str]) -> str:
    """['As', 'Kh'] → 'AKo' / ['As', 'Ks'] → 'AKs' / ['As', 'Ah'] → 'AA'."""
    if len(cards) != 2:
        raise ValueError(f"카드 2장 필요: {cards}")
    r1, r2 = cards[0][0].upper(), cards[1][0].upper()
    s1, s2 = cards[0][-1], cards[1][-1]
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2, s1, s2 = r2, r1, s2, s1
    if r1 == r2:
        return f"{r1}{r2}"
    return f"{r1}{r2}{'s' if s1 == s2 else 'o'}"


def lookup(
    hero: str,
    scenario: str,
    hand: str,
    villain: str | None = None,
    provider: str = "greenline",
) -> str:
    """차트 룩업.

    scenario: 'RFI' | 'vs-open' | 'vs-3bet' | 'vs-4bet' | 'ISO'
    반환: 'raise' | 'call' | 'fold' | 'allin'
    혼합(배열)은 균등 랜덤. 없는 핸드는 'fold'.
    """
    charts = _load().get(provider, {})
    key = f"{hero}-{scenario}" + (f"-{villain}" if villain else "")
    cell = charts.get(key, {}).get(hand, "fold")

    if isinstance(cell, list):
        return random.choice(cell)
    if isinstance(cell, dict):
        weight = cell.get("weight", 0)
        actions = cell.get("actions", {})
        if random.random() * 100 >= weight:
            return "fold"
        r = random.random() * 100
        acc = 0.0
        for act, pct in actions.items():
            acc += pct
            if r <= acc:
                return act
        return "fold"
    return cell


def available_charts(provider: str = "greenline") -> list[str]:
    """디버그용: 등록된 chartKey 리스트."""
    return sorted(_load().get(provider, {}).keys())


def position_9max_to_6max(pos: str) -> str:
    """9-max 포지션을 6-max 차트에 매핑.

    9-max: UTG, UTG+1, UTG+2, LJ, HJ, CO, BTN, SB, BB
    6-max: UTG, MP, CO, BTN, SB, BB
    """
    table = {
        "UTG": "UTG", "UTG+1": "UTG", "UTG+2": "UTG",
        "LJ": "MP", "HJ": "MP", "MP": "MP",
        "CO": "CO", "BTN": "BTN", "SB": "SB", "BB": "BB",
    }
    return table.get(pos, "UTG")
