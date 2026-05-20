"""프리플랍 GTO 결정 모듈.

`action_request` 메시지 → (action, amount).
내부적으로 lib.preflop_charts 를 사용해 6-max GTO 차트 룩업.

포지션 매핑은 **내 뒤에 남은 액션 플레이어 수**(seats_after_me) 기반 동적 매핑.
테이블 사이즈(2~9인)에 따라 같은 이름의 자리도 다른 차트로 매핑된다.
예: 4인 테이블의 utg는 뒤에 3명 남음 → 6-max CO 차트(26%)를 사용.

푸쉬폴드 모드(decide_pushfold)는 effective_bb ≤ 10일 때 진입. Chen 공식 기반
핸드 강도 + 위치 보정 + 효과 스택 보정으로 push/fold 결정. 정밀 Nash 차트가
아니어서 토너먼트 데이터 쌓이면 차트로 교체할 여지 있음.
"""
import csv
from pathlib import Path

from lib import config
from lib.preflop_charts import hand_key, lookup
from lib.strategy_variant import StrategyVariant, VALUE as DEFAULT_VARIANT


# ────── vs-random equity 룩업 (Nash push-fold 결정 용) ──────
_VS_RANDOM_PATH = Path(__file__).parent.parent / "data" / "preflop_equity_vs_random.csv"
_VS_RANDOM: dict[tuple[str, int], float] = {}


def _load_vs_random():
    if _VS_RANDOM:
        return
    with _VS_RANDOM_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            _VS_RANDOM[(row["hand"], int(row["num_opponents"]))] = float(row["equity"])


def vs_random_equity(hand: str, num_opponents: int = 1) -> float:
    """169 클래스 핸드의 N명 random opp 대상 equity (200k MC 사전 계산)."""
    _load_vs_random()
    return _VS_RANDOM.get((hand, max(1, min(num_opponents, 8))), 0.5)

# 테이블 사이즈별 프리플랍 액션 순서 (BOT_REFERENCE 기준).
# 앞에 있을수록 먼저 액션 = 뒤에 남은 플레이어 더 많음 = 더 타이트해야 함.
PREFLOP_ORDER = {
    2: ["btn", "bb"],                                                     # HU: btn 선행
    3: ["btn", "sb", "bb"],
    4: ["utg", "btn", "sb", "bb"],
    5: ["utg", "co", "btn", "sb", "bb"],
    6: ["utg", "hj", "co", "btn", "sb", "bb"],
    7: ["utg", "mp", "hj", "co", "btn", "sb", "bb"],
    8: ["utg", "utg1", "mp", "hj", "co", "btn", "sb", "bb"],
    9: ["utg", "utg1", "mp", "mp1", "hj", "co", "btn", "sb", "bb"],
}


def _seats_after_me(seat: str, n_players: int) -> int:
    """프리플랍 기준 내 뒤에 아직 액션 안 한 플레이어 수."""
    order = PREFLOP_ORDER.get(n_players)
    if not order:
        return 0
    s = seat.lower()
    if s not in order:
        return 0
    return len(order) - 1 - order.index(s)


def _map_seat(seat: str, n_players: int) -> str:
    """내 뒤에 남은 플레이어 수 → 6-max 차트 포지션."""
    s = seat.lower()
    if s == "bb":
        return "BB"
    if s == "sb":
        return "SB"
    left = _seats_after_me(s, n_players)
    # UTG(5+ 뒤남음) / MP(4) / CO(3) / BTN(2 이하)
    if left >= 5:
        return "UTG"
    if left == 4:
        return "MP"
    if left == 3:
        return "CO"
    return "BTN"  # 2, 1(HU btn) 모두 BTN 넓은 레인지로


def _classify_scenario(history: list, my_name: str) -> tuple[str, str | None]:
    """action_history에서 현재 프리플랍 시나리오와 villain 포지션 결정.

    반환: (scenario, villain_seat | None)
      - scenario: 'RFI' | 'vs-open' | 'vs-3bet' | 'vs-4bet' | 'ISO' | 'limped'
      - villain_seat: 6-max 매핑된 포지션 문자열, 없으면 None

    limped: 레이즈 없고 림퍼만 있는 경우 → ISO 차트 사용 시도
    """
    pre = [h for h in history if h.get("phase") == "preflop"]

    raises = [h for h in pre if h.get("action") == "raise"]
    calls = [h for h in pre if h.get("action") == "call"]
    my_raises = [h for h in raises if h.get("player") == my_name]

    if not raises:
        if calls:
            return ("ISO", None)
        return ("RFI", None)

    if not my_raises:
        # 내가 아직 레이즈 안 했는데 앞에서 레이즈 있음
        if len(raises) == 1:
            return ("vs-open", raises[0].get("player_seat"))
        # 2번 이상 레이즈 = 콜드 3/4벳 상황. 차트에 없어서 'vs-3bet'로 근사
        return ("vs-3bet", raises[-1].get("player_seat"))

    # 내가 레이즈 했음 → 이후 누가 더 레이즈했는지 확인
    my_last_idx = max(i for i, h in enumerate(pre) if h.get("player") == my_name and h.get("action") == "raise")
    after = pre[my_last_idx + 1:]
    after_raises = [h for h in after if h.get("action") == "raise"]

    if not after_raises:
        return ("RFI", None)  # 이미 레이즈했는데 액션이 다시 돌아왔다면 보통 일어나지 않음

    if len(after_raises) == 1:
        return ("vs-3bet", after_raises[0].get("player_seat"))
    return ("vs-4bet", after_raises[0].get("player_seat"))


def _seat_of_player(players: list, name: str) -> str | None:
    for p in players:
        if p.get("name") == name:
            return p.get("position")
    return None


def _attach_seats(history: list, players: list) -> list:
    """history 항목에 player_seat 필드 추가."""
    for h in history:
        h["player_seat"] = _seat_of_player(players, h.get("player"))
    return history


def _raise_amount(scenario: str, to_call: int, min_raise: int, bb: int, my_stack: int,
                  variant: StrategyVariant) -> int:
    """시나리오별 사이징 → 이번 라운드 총 베팅 목표액. 변형별 배수 반영."""
    if scenario == "RFI" or scenario == "ISO":
        target = int(variant.open_size_bb * bb)
    elif scenario == "vs-open":
        target = int(variant.threebet_mult * to_call)
    elif scenario == "vs-3bet":
        target = int(variant.fourbet_mult * to_call)
    elif scenario == "vs-4bet":
        # 5bet은 사실상 올인 스팟.
        target = my_stack
    else:
        target = max(2 * to_call, min_raise)

    target = max(target, min_raise)
    return min(target, my_stack)


# ────────────── 푸쉬폴드 / 자동올인 ──────────────

_RANK_ORDER = "23456789TJQKA"
_HIGH_SCORE = {
    "A": 10.0, "K": 8.0, "Q": 7.0, "J": 6.0, "T": 5.0,
    "9": 4.5, "8": 4.0, "7": 3.5, "6": 3.0, "5": 2.5,
    "4": 2.0, "3": 1.5, "2": 1.0,
}
# 위치 보너스 (BTN 가장 넓음, UTG 가장 좁음)
_POS_BONUS = {"BTN": 1.5, "CO": 1.0, "MP": 0.0, "UTG": -1.0, "SB": 0.5, "BB": 1.0}


def chen_score(hand: str) -> float:
    """Chen 공식 핸드 강도. AA=20, AKs=12, AKo=10, 72o=-1.

    hand 형식: 'AA', 'AKs', 'AKo' (preflop_charts.hand_key 출력 형태).
    """
    if len(hand) == 2:  # 페어
        return max(_HIGH_SCORE[hand[0]] * 2, 5.0)

    h, l, suited = hand[0], hand[1], hand[2] == "s"
    score = _HIGH_SCORE[h]

    gap = _RANK_ORDER.index(h) - _RANK_ORDER.index(l) - 1
    if gap == 0:
        score += 1.0   # connector
    elif gap == 1:
        score -= 1.0
    elif gap == 2:
        score -= 2.0
    elif gap == 3:
        score -= 4.0
    else:
        score -= 5.0

    if suited:
        score += 2.0
    return score


def _push_threshold(eff_bb: float, n_active_opp: int) -> float:
    """Nash 푸쉬 임계 (vs-random equity 기준).

    HU(1opp): 4bb 0.40 / 7bb 0.45 / 10bb 0.50 / 12+bb 0.55
    멀티웨이: 더 빡빡 (+0.05~0.10).
    """
    if n_active_opp <= 1:
        if eff_bb <= 4: return 0.40
        if eff_bb <= 7: return 0.45
        if eff_bb <= 10: return 0.50
        return 0.55
    # 멀티웨이 — 한 명만 콜해도 unfavorable, 더 강해야
    if eff_bb <= 4: return 0.50
    if eff_bb <= 7: return 0.55
    if eff_bb <= 10: return 0.62
    return 0.68


def decide_pushfold(msg: dict, bot_name: str, eff_bb: float, mode: str = "pushfold") -> tuple[str, int]:
    """Nash 기반 푸쉬폴드 결정.

    push 시점: vs-random equity (1 또는 N opp) 룩업 → 임계 비교.
    call 시점: equity > pot_odds + 마진.
    """
    cards = msg.get("your_cards", [])
    to_call = msg.get("to_call", 0)
    pot = msg.get("pot", 0)
    my_stack = msg.get("my_stack", 0)
    players = msg.get("players", [])

    if len(cards) != 2 or my_stack <= 0:
        return ("check", 0) if to_call == 0 else ("fold", 0)

    # 활성 상대 수 (나 제외, 폴드/탈락 제외)
    n_active_opp = sum(
        1 for p in players
        if p.get("name") != bot_name
        and p.get("status", "active") in ("active", "allin")
    )
    n_active_opp = max(1, n_active_opp)

    hand = hand_key(cards)
    eq = vs_random_equity(hand, n_active_opp)

    tightness = float(config.get("pushfold_tightness", 1.0))

    # 콜 페이싱
    if to_call > 0:
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0
        # 마진: HU 0.02, 멀티웨이 0.05 (multiway 임계 더 보수)
        margin = 0.02 if n_active_opp == 1 else 0.05
        margin *= tightness
        if eq > pot_odds + margin:
            if to_call >= my_stack * 0.9:
                return "allin", 0
            return "call", 0
        # allin 모드에서 매우 좋은 오즈 (≤30%)면 약한 패도 콜
        if mode == "allin" and pot_odds < 0.30 and eq > 0.32:
            return "call", 0
        return "fold", 0

    # 첫 액션 (open push or check)
    push_thresh = _push_threshold(eff_bb, n_active_opp) * tightness
    if eq >= push_thresh:
        return "allin", 0
    return ("check", 0) if to_call == 0 else ("fold", 0)


# ────────────── 일반 GTO 차트 ──────────────

def decide_preflop(msg: dict, bot_name: str, provider: str = "greenline",
                   variant: StrategyVariant = DEFAULT_VARIANT) -> tuple[str, int]:
    """프리플랍 GTO 결정. (action, amount) 반환.

    msg: action_request 메시지 원본
    bot_name: 내 봇 이름 (action_history에서 나를 식별)
    provider: 'greenline' | 'pekarstas'
    variant: 방에 할당된 전략 변형 (사이징에만 영향, 차트 선택은 고정)
    """
    cards = msg.get("your_cards", [])
    seat = msg.get("seat", "utg")
    to_call = msg.get("to_call", 0)
    min_raise = msg.get("min_raise", 0)
    my_stack = msg.get("my_stack", 0)
    blind = msg.get("blind", [1, 2])
    bb = blind[1] if len(blind) > 1 else 2
    history = list(msg.get("action_history", []))
    players = msg.get("players", [])

    if len(cards) != 2:
        return ("check", 0) if to_call == 0 else ("fold", 0)

    _attach_seats(history, players)
    scenario, villain_seat = _classify_scenario(history, bot_name)

    n_players = sum(1 for p in players if p.get("status") != "eliminated") or len(players)
    hand = hand_key(cards)
    hero = _map_seat(seat, n_players)
    villain = _map_seat(villain_seat, n_players) if villain_seat else None

    # ISO는 차트에 없음 → RFI 룩업으로 폴백 (레이트 포지션이면 오픈)
    chart_scenario = "RFI" if scenario == "ISO" else scenario

    action = lookup(hero, chart_scenario, hand, villain, provider)

    # 액션 → 서버 프로토콜 매핑
    if action == "fold":
        return ("check", 0) if to_call == 0 else ("fold", 0)
    if action == "call":
        return ("check", 0) if to_call == 0 else ("call", 0)
    if action == "raise":
        amt = _raise_amount(scenario, to_call, min_raise, bb, my_stack, variant)
        return ("raise", amt)
    if action == "allin":
        return ("allin", 0)

    return ("check", 0) if to_call == 0 else ("fold", 0)
