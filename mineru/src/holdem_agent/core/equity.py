from __future__ import annotations

import random

from treys import Card, Evaluator

from holdem_agent.core.card import server_hand_to_treys


_evaluator = Evaluator()
_FULL_DECK: list[int] = [Card.new(r + s) for r in "23456789TJQKA" for s in "shdc"]


def monte_carlo_equity(
    hole_cards: list[str],
    community_cards: list[str],
    num_opponents: int = 1,
    simulations: int = 1000,
) -> float:
    """Estimate win probability via Monte Carlo simulation.

    Returns:
        Win probability between 0.0 and 1.0.
    """
    if len(hole_cards) != 2:
        raise ValueError("Exactly 2 hole cards required")

    hole_ints = server_hand_to_treys(hole_cards)
    community_ints = server_hand_to_treys(community_cards) if community_cards else []

    known = set(hole_ints) | set(community_ints)
    remaining = [c for c in _FULL_DECK if c not in known]

    wins = 0
    ties = 0
    total = 0

    for _ in range(simulations):
        random.shuffle(remaining)
        idx = 0

        # Complete community cards to 5
        board = list(community_ints)
        while len(board) < 5:
            board.append(remaining[idx])
            idx += 1

        # Deal opponent hands
        my_rank = _evaluator.evaluate(hole_ints, board)
        i_win = True
        is_tie = False

        for _ in range(num_opponents):
            opp_hole = [remaining[idx], remaining[idx + 1]]
            idx += 2
            opp_rank = _evaluator.evaluate(opp_hole, board)
            if opp_rank < my_rank:
                i_win = False
                is_tie = False
                break
            elif opp_rank == my_rank:
                is_tie = True
                i_win = False

        if i_win:
            wins += 1
        elif is_tie:
            ties += 1
        total += 1

    return (wins + ties * 0.5) / total if total > 0 else 0.0
