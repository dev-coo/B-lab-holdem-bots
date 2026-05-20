"""ICM (Independent Chip Model) equity 계산 — Malmuth-Harville 공식.

용도: final table / 버블 단계에서 "칩 가치 ≠ 상금 가치" 비대칭성을 정량화. 이
함수의 출력값(상금 단위) 을 chip-EV 와 비교하면 ICM 우위/하위를 판정할 수 있다.

알고리즘 (Malmuth-Harville):
  - 1 등 확률(player i) = stack[i] / total
  - 2 등 확률(player j | i 1 등) = stack[j] / (total − stack[i])
  - …
  - 각 위치별 상금을 가중합하여 player 의 ICM equity 산출

복잡도: bitmask DP 로 O(2^n · n²). n ≤ 9 (한 테이블) 가정 — 512 × 81 ≈ 4 만 회로
충분히 빠름.

1 등 승률 vs ITM trade-off 주의: ICM 은 본질적으로 **ITM 보호** 관점이라 직접
적용 시 1 등 승률을 떨어뜨릴 수 있다. 사용처는 (a) bubble/short-stack 의
flip 회피 가이드, (b) chip-leader 의 medium-stack 공격 계산 정도로 한정 권장.
"""
from __future__ import annotations

from functools import lru_cache


def icm_equity(stacks: list[float], payouts: list[float]) -> list[float]:
    """각 player 의 ICM equity (상금 단위) 반환.

    Args:
        stacks: 각 player 의 chip 스택 (양수). 길이 = 참가자 수.
        payouts: 1 위 ~ k 위 상금. payouts[0] = 1 등 상금. 길이 ≤ stacks.
                 ITM 외 인원은 payout 0 으로 간주 (자동 padding).

    Returns:
        len(stacks) 길이의 리스트 — 각 player 의 기대 상금.

    Raises:
        ValueError: 음수/0 stack, 음수 payout, 빈 입력.
    """
    if not stacks:
        raise ValueError("stacks must be non-empty")
    if any(s < 0 for s in stacks):
        raise ValueError("negative stacks not allowed")
    if any(p < 0 for p in payouts):
        raise ValueError("negative payouts not allowed")

    n = len(stacks)
    # payouts 를 n 길이로 zero-padding (ITM 외).
    pads = list(payouts) + [0.0] * max(0, n - len(payouts))
    pads = pads[:n]

    # 0-stack 플레이어 (이미 탈락) 는 ICM 계산에서 제외 — equity 0.
    active_idx = [i for i, s in enumerate(stacks) if s > 0]
    if not active_idx:
        return [0.0] * n

    active_stacks = tuple(float(stacks[i]) for i in active_idx)
    active_n = len(active_idx)
    # active 만큼의 payout 만 의미 있음.
    active_payouts = tuple(pads[: max(active_n, 1)])

    # bitmask DP: state = 살아있는 active 인덱스 집합.
    # 각 state 의 결과 = 그 state 안의 player 들이 (남은 위치 = 살아있는 인원수)
    # 안에서 각자 받는 ICM equity.
    full_mask = (1 << active_n) - 1

    @lru_cache(maxsize=None)
    def dp(mask: int) -> tuple[float, ...]:
        # mask 에 있는 player 들 사이의 남은 순위 = popcount(mask) 위치.
        # 각자가 받게 될 상금 합계의 기대치를 반환.
        bits = [i for i in range(active_n) if mask & (1 << i)]
        if not bits:
            return ()
        place_index = active_n - len(bits)   # 0-indexed 첫 미배정 위치
        if place_index >= len(active_payouts):
            # 남은 위치 모두 ITM 밖 — 상금 0.
            return tuple(0.0 for _ in range(active_n))
        # 남은 stack 합 (순위 결정용 분모).
        total = sum(active_stacks[i] for i in bits)
        if total <= 0:
            return tuple(0.0 for _ in range(active_n))

        result = [0.0] * active_n
        prize_at_place = active_payouts[place_index]
        for i in bits:
            p_first_among_remaining = active_stacks[i] / total
            # i 가 이번 위치(place_index) 에 떨어질 때 받는 prize.
            result[i] += p_first_among_remaining * prize_at_place
            # 그리고 i 가 그 위치에 들어간 뒤 나머지의 ICM 분포.
            sub_mask = mask & ~(1 << i)
            sub = dp(sub_mask)
            if sub:
                for j in range(active_n):
                    result[j] += p_first_among_remaining * sub[j]
        return tuple(result)

    sub_eq = dp(full_mask)
    out = [0.0] * n
    for local_i, global_i in enumerate(active_idx):
        out[global_i] = sub_eq[local_i] if local_i < len(sub_eq) else 0.0
    return out


def chip_share(stacks: list[float]) -> list[float]:
    """순수 chip-EV 비율 (= 1 등만 winner-take-all 가정의 ICM-lite)."""
    total = sum(max(0.0, s) for s in stacks)
    if total <= 0:
        return [0.0 for _ in stacks]
    return [max(0.0, s) / total for s in stacks]
