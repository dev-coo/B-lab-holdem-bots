"""Layer 0 수학 — 골든 케이스."""
from __future__ import annotations

import pytest

from holdem.math.odds import (
    alpha,
    break_even_equity_for_drawing,
    mdf,
    pot_odds,
    required_fold_equity_for_bluff,
)


def test_pot_odds_simple():
    # pot=10, 상대 bet=10 → to_call=10, pot_after_bet=20, break-even=10/30=1/3
    assert pot_odds(to_call=10, pot_after_bet=20) == pytest.approx(1 / 3, abs=1e-9)


def test_pot_odds_zero_denom():
    assert pot_odds(to_call=0, pot_after_bet=0) == 1.0


def test_pot_odds_free_call():
    # to_call=0 → 어떤 에퀴티도 +EV
    assert pot_odds(to_call=0, pot_after_bet=20) == 0.0


def test_mdf_half_pot_bet():
    # pot=10, bet=5 → mdf=10/15=2/3
    assert mdf(pot_before_bet=10, bet=5) == pytest.approx(2 / 3, abs=1e-9)


def test_mdf_pot_sized_bet():
    # pot=10, bet=10 → mdf=1/2
    assert mdf(10, 10) == 0.5


def test_mdf_overbet():
    # pot=10, bet=20 → mdf=10/30=1/3
    assert mdf(10, 20) == pytest.approx(1 / 3, abs=1e-9)


def test_alpha_half_pot_bet():
    # alpha = 5 / (10 + 5) = 1/3
    assert alpha(10, 5) == pytest.approx(1 / 3, abs=1e-9)


def test_alpha_pot_sized_bet():
    # alpha = 10 / (10 + 10) = 0.5
    assert alpha(10, 10) == 0.5


def test_alpha_overbet():
    # alpha = 20 / (10 + 20) = 2/3
    assert alpha(10, 20) == pytest.approx(2 / 3, abs=1e-9)


def test_alpha_zero_denom():
    assert alpha(0, 0) == 0.0


def test_implied_odds_lowers_threshold():
    raw = pot_odds(to_call=10, pot_after_bet=20)   # 0.333
    boosted = break_even_equity_for_drawing(10, 20, implied_odds_multiplier=2.0)
    assert boosted == pytest.approx(raw / 2.0, abs=1e-9)


def test_bluff_with_zero_equity_equals_alpha():
    # bluff_equity=0 → alpha 와 동일
    fe = required_fold_equity_for_bluff(pot_before_bet=10, bet=10, bluff_equity=0.0)
    assert fe == pytest.approx(alpha(10, 10), abs=1e-6)


def test_bluff_with_positive_equity_needs_less_fold():
    fe_zero = required_fold_equity_for_bluff(10, 10, bluff_equity=0.0)
    fe_some = required_fold_equity_for_bluff(10, 10, bluff_equity=0.25)
    assert fe_some < fe_zero


def test_bluff_with_very_high_equity_needs_no_fold():
    # bluff_equity 가 매우 높으면 상대가 전혀 안 폴드해도 +EV
    fe = required_fold_equity_for_bluff(10, 10, bluff_equity=0.9)
    assert fe == 0.0   # clamped
