import random

import pytest

from holdem_agent.core.equity import monte_carlo_equity


def test_equity_pocket_aces_high() -> None:
    random.seed(12345)
    equity = monte_carlo_equity(["As", "Ah"], [], num_opponents=1, simulations=5000)

    assert equity > 0.7


def test_equity_weak_hand_low() -> None:
    random.seed(777)
    equity = monte_carlo_equity(["2s", "3c"], [], num_opponents=1, simulations=1000)

    assert 0.0 <= equity < 0.5


def test_equity_with_flop() -> None:
    random.seed(17)
    equity = monte_carlo_equity(["As", "Ah"], ["2h", "7d", "Jc"], num_opponents=1, simulations=1000)

    assert 0.6 < equity < 1.0


def test_equity_with_full_board() -> None:
    random.seed(99)
    equity = monte_carlo_equity(["Ad", "As"], ["Ac", "Ks", "Kc", "2h", "2d"], num_opponents=1, simulations=1000)

    assert 0.9 <= equity <= 1.0


def test_equity_multiway() -> None:
    random.seed(2024)
    equity_vs_one = monte_carlo_equity(["As", "Ah"], [], num_opponents=1, simulations=1000)

    random.seed(2024)
    equity_vs_three = monte_carlo_equity(["As", "Ah"], [], num_opponents=3, simulations=1000)

    assert equity_vs_three < equity_vs_one
    assert equity_vs_three < 1.0


def test_equity_invalid_hole_cards() -> None:
    with pytest.raises(ValueError, match="Exactly 2 hole cards required"):
        monte_carlo_equity(["Ah"], [], num_opponents=1, simulations=100)


def test_equity_returns_range() -> None:
    random.seed(2025)
    equity = monte_carlo_equity(["Kd", "Qd"], ["8h", "9s", "Tc", "Jd"], num_opponents=2, simulations=1000)

    assert 0.0 <= equity <= 1.0
