"""ICM equity 단위 테스트 (Malmuth-Harville)."""
from __future__ import annotations

import pytest

from holdem.math.icm import chip_share, icm_equity


def test_chip_share_proportional():
    eq = chip_share([100, 200, 300, 400])
    assert eq == pytest.approx([0.1, 0.2, 0.3, 0.4])


def test_chip_share_with_zero_stack():
    eq = chip_share([0, 100, 100])
    assert eq == pytest.approx([0.0, 0.5, 0.5])


def test_icm_equity_winner_take_all_matches_chip_share():
    """payout 1 명만 → ICM = chip-share × prize."""
    stacks = [100, 200, 300]
    eq = icm_equity(stacks, [1000])
    # winner-take-all 에서는 ICM = 1 등 확률 × prize = chip share × prize.
    expected = [0.1*1000 + 0.0, 0.2*1000 + 0.0, 0.3*1000 + 0.0]
    # Wait — winner-take-all 에서 1 등만 1000, 2/3 등은 0. 따라서
    # ICM[i] = P(i 1등) × 1000 = chip_share[i] × 1000.
    assert eq == pytest.approx([100.0/600*1000, 200.0/600*1000, 300.0/600*1000])


def test_icm_equity_two_players_split_two_payouts():
    """2 명 + 2 페이아웃 (700, 300) → 1 등 prize 차등 분포."""
    eq = icm_equity([100, 200], [700, 300])
    # P(small=1st) = 100/300 = 0.333
    # eq[small] = 0.333 × 700 + 0.667 × 300 = 233.33 + 200 = 433.33
    # eq[big]   = 0.667 × 700 + 0.333 × 300 = 466.67 + 100 = 566.67
    assert eq == pytest.approx([433.333, 566.667], abs=0.01)
    assert sum(eq) == pytest.approx(1000.0)


def test_icm_equity_chip_lead_under_payout_advantage():
    """4 명 동일 스택 + 페이아웃 (50, 30, 20) → 모두 동일 ICM equity."""
    eq = icm_equity([100, 100, 100, 100], [50, 30, 20])
    expected = [25.0, 25.0, 25.0, 25.0]   # 합 = 100, 각 동일.
    assert eq == pytest.approx(expected, abs=0.01)


def test_icm_equity_big_stack_below_chip_share():
    """상금 분포가 평탄할수록 big stack 의 ICM 비율이 chip 비율보다 낮음
    (큰 chip 의 한계효용 감소). 반대로 short stack 은 ICM 이 더 높음."""
    stacks = [2000, 500, 500]
    payouts = [60, 30, 10]
    total_prize = sum(payouts)
    eq = icm_equity(stacks, payouts)
    chip = chip_share(stacks)
    # Big stack idx=0: chip share = 2000/3000 ≈ 0.667. ICM 비율은 더 낮아야.
    assert eq[0] / total_prize < chip[0]
    # Short stacks 합 ICM > 합 chip share.
    short_icm_share = (eq[1] + eq[2]) / total_prize
    short_chip_share = chip[1] + chip[2]
    assert short_icm_share > short_chip_share


def test_icm_equity_sums_to_total_prize():
    """ICM equity 합 = payout 합 (보존 법칙)."""
    eq = icm_equity([100, 200, 300, 400], [50, 30, 20, 0])
    assert sum(eq) == pytest.approx(100.0, abs=0.01)


def test_icm_equity_zero_payouts_returns_zeros():
    eq = icm_equity([100, 200], [])
    assert eq == [0.0, 0.0]


def test_icm_equity_skips_dead_player():
    """0-stack 플레이어는 equity 0, 다른 플레이어들의 합이 prize 합과 일치."""
    eq = icm_equity([0, 100, 200], [100, 50])
    assert eq[0] == 0.0
    assert sum(eq) == pytest.approx(150.0)


def test_icm_equity_validation():
    with pytest.raises(ValueError):
        icm_equity([], [100])
    with pytest.raises(ValueError):
        icm_equity([-10, 100], [100])
    with pytest.raises(ValueError):
        icm_equity([100, 100], [-50])
