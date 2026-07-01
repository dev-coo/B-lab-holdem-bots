"""패배 원인 분류기.

`HandRecord` 하나에 대해 내 봇이 진 원인을 카테고리로 판정.
특히 탈락 핸드에는 더 상세한 분류를 시도한다.
"""

from __future__ import annotations

from typing import Literal

from holdem_core.hand_eval import rank7

from holdem_tools.analysis.loader import HandRecord

LossCause = Literal[
    "bad_preflop_call",
    "outdrawn",
    "counterfactual_wrong_fold",
    "aggressive_bet_into_better",
    "unlucky_bad_beat",
    "preflop_tight_fold_to_blinds",
    "normal_loss",
]


def my_in_showdown(hand: HandRecord, bot_name: str) -> bool:
    return any(s.get("name") == bot_name for s in hand.showdown if isinstance(s, dict))


def my_won_hand(hand: HandRecord, bot_name: str) -> bool:
    return any(
        w.get("name") == bot_name for w in hand.winners if isinstance(w, dict)
    )


def villain_showdown_cards(hand: HandRecord, bot_name: str) -> list[tuple[str, list[str]]]:
    """쇼다운에 나온 상대 (이름, 카드) 목록."""
    out: list[tuple[str, list[str]]] = []
    for s in hand.showdown:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        cards = s.get("cards") or []
        if name and name != bot_name and len(cards) >= 2:
            out.append((str(name), list(cards)))
    return out


def classify_loss(hand: HandRecord, bot_name: str) -> LossCause | None:
    """이 핸드에 대한 패배 원인 분류. 내가 이긴 핸드면 None.

    우선순위(위에 있을수록 구체적):
      1. unlucky_bad_beat
      2. outdrawn
      3. counterfactual_wrong_fold
      4. aggressive_bet_into_better
      5. bad_preflop_call
      6. preflop_tight_fold_to_blinds (탈락 핸드 한정)
      7. normal_loss
    """
    if my_won_hand(hand, bot_name):
        return None
    if not hand.my_actions and not hand.eliminated:
        return None  # 내가 참여 안 한 핸드

    last_dec = hand.my_actions[-1] if hand.my_actions else None
    last_meta = (last_dec.meta or {}) if last_dec else {}
    last_equity = _as_float(last_meta.get("equity"))

    in_sd = my_in_showdown(hand, bot_name)

    # 쇼다운 패배 카테고리
    if in_sd:
        if last_equity is not None and last_equity >= 0.80:
            return "unlucky_bad_beat"
        if last_equity is not None and last_equity >= 0.60:
            return "outdrawn"
        if last_dec is not None and last_dec.action in ("raise", "allin"):
            return "aggressive_bet_into_better"
        # 프리플롭 call 로 진입 + lost
        preflop_actions = [d for d in hand.my_actions if d.phase == "preflop"]
        if preflop_actions:
            last_pre = preflop_actions[-1]
            meta = last_pre.meta or {}
            is_top = bool(meta.get("is_top300"))
            is_pair = bool(meta.get("is_pair"))
            if (
                last_pre.action == "call"
                and not is_top
                and not is_pair
                and _faced_preflop_raise(hand)
            ):
                return "bad_preflop_call"
        return "normal_loss"

    # 폴드 후 쇼다운 발생 — counterfactual wrong fold
    if _i_folded(hand) and hand.showdown and _counterfactual_won(hand, bot_name):
        return "counterfactual_wrong_fold"

    # 탈락 핸드 — blind pressure
    if bot_name in hand.eliminated:
        if _all_folds(hand) and _bb_heavy(hand):
            return "preflop_tight_fold_to_blinds"

    return "normal_loss"


def _faced_preflop_raise(hand: HandRecord) -> bool:
    for a in hand.opp_actions:
        if a.get("phase") == "preflop" and a.get("action") in ("raise", "allin"):
            return True
    return False


def _i_folded(hand: HandRecord) -> bool:
    return any(d.action == "fold" for d in hand.my_actions)


def _all_folds(hand: HandRecord) -> bool:
    if not hand.my_actions:
        return False
    return all(d.action == "fold" for d in hand.my_actions)


def _bb_heavy(hand: HandRecord) -> bool:
    if not hand.blind or len(hand.blind) < 2:
        return False
    bb = hand.blind[1]
    start = hand.start_stack or 1
    return bb / max(start, 1) >= 0.3


def _counterfactual_won(hand: HandRecord, bot_name: str) -> bool:
    """내가 폴드 했더라도 내 카드 + 최종 board 로 evaluate 해서
    쇼다운에 나온 상대(최강) 보다 높았을까?
    """
    if len(hand.board_final) < 5:
        return False
    my_cards = hand.your_cards
    if len(my_cards) < 2:
        return False
    try:
        my_r = rank7(my_cards + hand.board_final)
    except Exception:  # noqa: BLE001
        return False
    for _, cards in villain_showdown_cards(hand, bot_name):
        try:
            vr = rank7(cards + hand.board_final)
        except Exception:  # noqa: BLE001
            continue
        if my_r > vr:
            return True
    return False


def _as_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
