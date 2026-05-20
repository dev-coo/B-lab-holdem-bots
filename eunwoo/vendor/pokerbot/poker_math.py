"""포커 이론 계산식 — EV 기반 의사결정의 기본 공식 모음.

모든 함수는 순수 함수(no side effects). 단위는 명시:
- chips: 정수 칩 단위
- fraction: 0.0~1.0 확률
- bb: 빅블라인드 단위

주요 공식 그룹:
- 오즈 & 방어율:   pot_odds, required_equity, mdf, alpha
- 기대값(EV):       ev_call, ev_raise_bluff, ev_raise_value, ev_bluff
- 드로우 확률:     outs_to_equity, rule_of_two_four
- 블러프 밸런싱:   bluff_value_ratio, optimal_bluff_freq
- 레인지 에퀴티:   range_equity_lookup
- 스택 관리:       spr, commitment_threshold, kelly_fraction
- 포지션 보정:     equity_realization (휴리스틱)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RANK_ORDER = "23456789TJQKA"


# ── 오즈 & 방어율 ─────────────────────────────────────────────

def pot_odds(to_call: int, pot: int) -> float:
    """콜에 필요한 최소 에퀴티.

    to_call=25, pot=75 → 25/(75+25) = 0.25 즉 25% 이상이면 콜 EV+.
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


def required_equity(to_call: int, pot: int) -> float:
    """pot_odds의 별칭 — 가독성용."""
    return pot_odds(to_call, pot)


def mdf(bet: int, pot: int) -> float:
    """MDF (Minimum Defense Frequency) — 상대 블러프에 안 당하려는 최소 방어율.

    bet=50, pot=100 → 100/(100+50) = 0.67. 즉 67% 이상은 콜/레이즈로 방어해야
    상대가 블러프로 이득 못 봄. 상대 블러프 빈도 > (1 - mdf) 이면 콜 기준 상향.
    """
    if pot <= 0:
        return 0.0
    return pot / (pot + bet)


def alpha(bet: int, pot: int) -> float:
    """Alpha — 우리 블러프가 성공하려는 상대 필요 폴드율.

    bet=50, pot=100 → 50/150 = 0.33. 즉 상대가 33% 이상 폴드하면 순수 EV+.
    알파는 bet/(bet+pot) 공식 — MDF의 여집합과 동일.
    """
    if bet + pot <= 0:
        return 0.0
    return bet / (bet + pot)


# ── 기대값(EV) ─────────────────────────────────────────────

def ev_call(p_win: float, pot: int, to_call: int, tie_prob: float = 0.0) -> float:
    """콜의 EV (칩 단위).

    승: pot + to_call 획득 (콜 포함)
    무: (pot + to_call) / 2
    패: -to_call
    """
    p_win = max(0.0, min(1.0, p_win))
    tie_prob = max(0.0, min(1.0 - p_win, tie_prob))
    p_lose = 1.0 - p_win - tie_prob
    return (p_win * (pot + to_call)
            + tie_prob * (pot + to_call) / 2
            - p_lose * to_call)


def ev_bluff(p_fold: float, bet: int, pot: int) -> float:
    """순수 블러프의 EV (우리가 질 때 -bet, 상대 폴드 시 +pot).

    p_call_lose 상황 모두 포함 — 블러프는 콜 당하면 진다 가정.
    """
    p_fold = max(0.0, min(1.0, p_fold))
    return p_fold * pot - (1.0 - p_fold) * bet


def ev_raise(p_fold: float, p_call_win: float, pot: int, bet: int) -> float:
    """레이즈의 EV — 폴드/콜(승)/콜(패) 3분기.

    단순 모델: 콜 당하면 쇼다운 간다 가정.
    """
    p_fold = max(0.0, min(1.0, p_fold))
    p_call_win = max(0.0, min(1.0 - p_fold, p_call_win))
    p_call_lose = 1.0 - p_fold - p_call_win
    return (p_fold * pot
            + p_call_win * (pot + bet)
            - p_call_lose * bet)


def ev_semi_bluff(p_fold: float, p_hit: float, pot: int, bet: int,
                  future_win: float = 0.0) -> float:
    """세미블러프 EV — 폴드 or 드로우 맞추기 + 향후 수익.

    p_hit: 콜 당했을 때 드로우 완성 확률
    future_win: 드로우 완성 시 추가로 뽑을 수 있는 칩 기대치
    """
    p_fold = max(0.0, min(1.0, p_fold))
    p_hit = max(0.0, min(1.0, p_hit))
    p_call = 1.0 - p_fold
    call_ev = p_hit * (pot + bet + future_win) - (1.0 - p_hit) * bet
    return p_fold * pot + p_call * call_ev


# ── 드로우 확률 ─────────────────────────────────────────────

def rule_of_two_four(outs: int, streets_left: int) -> float:
    """Rule of 2/4 근사 — 아웃 × (streets_left == 2 ? 4 : 2) %.

    플롭 → 턴+리버 = 4× / 턴 → 리버 = 2× / 리버 = 0.
    정확도 ±2% (드로우 15아웃 이하 유효).
    """
    if streets_left == 2:
        return min(0.95, outs * 0.04)
    if streets_left == 1:
        return min(0.95, outs * 0.02)
    return 0.0


def outs_to_equity_exact(outs: int, unknown: int, streets_left: int) -> float:
    """정확한 아웃 → 에퀴티 (조합론).

    unknown: 우리가 못 보는 카드 수 (표준 52 - hole - community).
    """
    if unknown <= 0 or streets_left <= 0:
        return 0.0
    miss_one = (unknown - outs) / unknown
    if streets_left == 1:
        return 1.0 - miss_one
    # 2 streets
    miss_two = miss_one * ((unknown - 1 - outs) / max(1, unknown - 1))
    return 1.0 - miss_two


# ── 블러프 밸런싱 ─────────────────────────────────────────────

def bluff_value_ratio(bet_size_pct_pot: float) -> float:
    """GTO 리버 블러프:밸류 비율.

    bet/(bet+pot) = alpha 만큼 블러프를 섞으면 상대는 pot_odds에 무차별.
    예: 1/2 pot bet → alpha = 1/3 → 1 블러프당 2 밸류.
    반환값은 "블러프 1당 밸류 N" 형태의 N.
    """
    a = bet_size_pct_pot / (bet_size_pct_pot + 1.0) if bet_size_pct_pot > 0 else 0
    if a <= 0:
        return 0
    return (1.0 - a) / a


def optimal_bluff_freq(bet_size_pct_pot: float) -> float:
    """리버 최적 블러프 빈도 = alpha (0~1)."""
    if bet_size_pct_pot <= 0:
        return 0.0
    return bet_size_pct_pot / (bet_size_pct_pot + 1.0)


# ── 레인지 에퀴티 ─────────────────────────────────────────────

_MATRIX_CACHE: dict[str, dict[str, float]] | None = None


def _load_matrix() -> dict[str, dict[str, float]] | None:
    global _MATRIX_CACHE
    if _MATRIX_CACHE is not None:
        return _MATRIX_CACHE
    path = Path(__file__).parent / "preflop_equity_matrix.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        _MATRIX_CACHE = json.load(f)
    return _MATRIX_CACHE


def hand_class(hole: list[str]) -> str:
    """홀카드 → 169 클래스 (AA, AKs, AKo, ..., 22)."""
    if len(hole) != 2:
        return ""
    r1, s1 = hole[0][0], hole[0][1]
    r2, s2 = hole[1][0], hole[1][1]
    v1 = RANK_ORDER.index(r1)
    v2 = RANK_ORDER.index(r2)
    if v1 < v2:
        r1, r2, s1, s2 = r2, r1, s2, s1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ("s" if s1 == s2 else "o")


def heads_up_equity(hole: list[str], opp_class: str) -> float | None:
    """내 홀 vs 상대 핸드 클래스의 heads-up 에퀴티 — 매트릭스 조회."""
    m = _load_matrix()
    if m is None:
        return None
    my = hand_class(hole)
    row = m.get(my)
    if not row:
        return None
    return row.get(opp_class)


def range_equity_lookup(hole: list[str], opp_range: list[str]) -> float:
    """내 홀 vs 상대 레인지(클래스 목록)의 평균 에퀴티.

    가중치 없이 레인지 내 모든 클래스에 동일 확률 부여.
    더 정확히 하려면 class별 combo 개수로 가중(향후 확장).
    """
    if not opp_range:
        return 0.5
    m = _load_matrix()
    if m is None:
        return 0.5
    my = hand_class(hole)
    row = m.get(my)
    if not row:
        return 0.5
    eqs = [row[c] for c in opp_range if c in row]
    if not eqs:
        return 0.5
    return sum(eqs) / len(eqs)


# ── 스택 & 자금 관리 ─────────────────────────────────────────

def spr(stack: int, pot: int) -> float:
    """Stack-to-Pot Ratio. 낮을수록 commitment 높음."""
    if pot <= 0:
        return float("inf")
    return stack / pot


def commitment_threshold(spr_val: float) -> float:
    """SPR별 commitment 에퀴티 임계 (휴리스틱).

    SPR < 3: 강한 탑페어급 이상이면 commit (lower bar)
    SPR 3~10: 투페어/셋 이상
    SPR > 10: 넛트 계열만
    """
    if spr_val < 3:
        return 0.55
    if spr_val < 10:
        return 0.70
    return 0.82


def kelly_fraction(p_win: float, odds: float) -> float:
    """Kelly Criterion — 자금의 몇 %를 걸어야 장기 성장 최대화.

    p_win: 승률 (0~1)
    odds: 1 단위 걸어 이기면 몇 단위 따는가 (b). even money면 1.
    f = (p·(b+1) - 1) / b
    """
    if odds <= 0:
        return 0.0
    f = (p_win * (odds + 1.0) - 1.0) / odds
    return max(0.0, min(1.0, f))


# ── 포지션 & 실현 에퀴티 ─────────────────────────────────────

def equity_realization(equity_raw: float, has_position: bool,
                       num_opps: int, has_playability: bool = True) -> float:
    """Raw equity를 실현 에퀴티로 보정 (휴리스틱).

    - 포지션 있으면 +5%
    - 멀티웨이면 -5%/opp (첫 번째 opp 제외)
    - playability 낮으면(오프수트 작은 카드) -10%
    """
    realized = equity_raw
    if has_position:
        realized *= 1.05
    if num_opps > 1:
        realized *= (1.0 - 0.05 * (num_opps - 1))
    if not has_playability:
        realized *= 0.90
    return max(0.0, min(1.0, realized))


# ── 헬퍼: implied odds ─────────────────────────────────────

def implied_odds(to_call: int, pot: int, expected_future_win: int) -> float:
    """Implied odds — 드로우 맞으면 추가로 뽑을 수 있는 칩 반영한 유효 오즈.

    반환값은 "콜에 필요한 에퀴티"의 하향 조정된 버전.
    expected_future_win: 드로우 완성 시 상대로부터 받을 추가 콜/레이즈 기대치.
    """
    if to_call <= 0:
        return 0.0
    effective_pot = pot + expected_future_win
    return to_call / (effective_pot + to_call)


# ── 자가 테스트 ─────────────────────────────────────────

if __name__ == "__main__":
    # 간단 sanity check
    print(f"pot_odds(25, 75) = {pot_odds(25, 75):.3f}  (기대 0.25)")
    print(f"mdf(50, 100) = {mdf(50, 100):.3f}  (기대 0.667)")
    print(f"alpha(50, 100) = {alpha(50, 100):.3f}  (기대 0.333)")
    print(f"ev_call(0.4, 100, 25) = {ev_call(0.4, 100, 25):.2f}  (기대 +35)")
    print(f"ev_bluff(0.6, 50, 100) = {ev_bluff(0.6, 50, 100):.2f}  (기대 +40)")
    print(f"rule_of_two_four(9, 2) = {rule_of_two_four(9, 2):.2f}  (기대 0.36)")
    print(f"outs_to_equity_exact(9, 47, 2) = {outs_to_equity_exact(9, 47, 2):.3f}  (기대 ~0.35)")
    print(f"bluff_value_ratio(0.5) = {bluff_value_ratio(0.5):.2f}  (기대 2.0)")
    print(f"optimal_bluff_freq(0.5) = {optimal_bluff_freq(0.5):.3f}  (기대 0.333)")
    print(f"spr(200, 40) = {spr(200, 40):.1f}  (기대 5.0)")
    print(f"kelly_fraction(0.525, 1.0) = {kelly_fraction(0.525, 1.0):.3f}  (기대 ~0.05)")
    m = _load_matrix()
    if m:
        print(f"heads_up_equity(['As','Kh'], 'QQ') = {heads_up_equity(['As','Kh'], 'QQ'):.3f}")
        opp_range = ["AA", "KK", "QQ", "AKs", "AKo"]
        print(f"range_equity(['As','Ah'], tight range) = {range_equity_lookup(['As','Ah'], opp_range):.3f}")
    else:
        print("(매트릭스 파일 없음)")
