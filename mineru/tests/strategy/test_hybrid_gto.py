from __future__ import annotations

import pytest

from holdem_agent.models.state import ActionRecord
from holdem_agent.strategy.base import DecisionContext, Strategy
from holdem_agent.strategy.builtins.hybrid_gto import HybridGTO
from holdem_agent.strategy.genome import StrategyGenome


def _ctx(**overrides) -> DecisionContext:
    defaults = dict(
        hand_number=1,
        hole_cards=["Ah", "Kh"],
        community_cards=[],
        phase="preflop",
        pot=10,
        my_stack=300,
        my_seat="btn",
        to_call=0,
        min_raise=4,
        blind=(1, 2),
        players=[],
        action_history=[],
        blind_structure=[],
        starting_stack=300,
        room_id=1,
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


def _make_raise_history(player: str = "opp1", amount: int = 8) -> list[ActionRecord]:
    return [ActionRecord(phase="preflop", player=player, action="raise", amount=amount)]


class TestHybridGTOBasic:
    def test_name(self) -> None:
        assert HybridGTO().name == "hybrid-gto"

    def test_default_genome(self) -> None:
        strategy = HybridGTO()
        assert isinstance(strategy.genome, StrategyGenome)
        assert strategy.genome.raise_size_pot_fraction == 0.85
        assert strategy.genome.check_raise_frequency == 0.10
        assert strategy.genome.donk_bet_frequency == 0.08

    def test_from_genome(self) -> None:
        genome = StrategyGenome(bluff_frequency=0.3, exploit_aggression=0.8)
        strategy = HybridGTO.from_genome(genome)
        assert isinstance(strategy, HybridGTO)
        assert strategy.genome == genome

    def test_is_strategy_subclass(self) -> None:
        assert issubclass(HybridGTO, Strategy)


class TestHybridGTOPreflop:
    def test_fold_weak_hand_utg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.08)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(hole_cards=["2h", "7d"], my_seat="utg", to_call=4))
        assert action.action == "fold"

    def test_raise_strong_hand_btn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.85)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(hole_cards=["As", "Ad"], my_seat="btn", to_call=0, pot=20, min_raise=6))
        assert action.action == "raise"
        assert action.amount is not None and action.amount >= 6

    def test_check_free_with_weak_hand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.05)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(hole_cards=["2h", "7d"], my_seat="utg", to_call=0))
        assert action.action == "check"

    def test_call_with_good_equity_vs_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.70)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(to_call=6, action_history=_make_raise_history()))
        assert action.action in {"call", "raise"}

    def test_fold_to_3bet_with_weak_hand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.15)
        strategy = HybridGTO()
        two_raises = [
            ActionRecord(phase="preflop", player="opp1", action="raise", amount=6),
            ActionRecord(phase="preflop", player="opp2", action="raise", amount=18),
        ]
        action = strategy.decide(_ctx(hole_cards=["2h", "7d"], to_call=18, action_history=two_raises))
        assert action.action == "fold"


class TestHybridGTOPostflop:
    def test_value_bet_premium(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.85)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(
            phase="flop",
            community_cards=["As", "Kd", "7c"],
            to_call=0,
            pot=30,
            min_raise=10,
        ))
        assert action.action == "raise"

    def test_call_with_strong_hand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.65)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(
            phase="turn",
            community_cards=["As", "Kd", "7c", "2h"],
            to_call=10,
            pot=40,
            min_raise=20,
        ))
        assert action.action in {"call", "raise"}

    def test_fold_weak_hand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.12)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.random.random", lambda: 0.99)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(
            phase="flop",
            community_cards=["Qs", "Jd", "4c"],
            hole_cards=["2h", "7d"],
            to_call=20,
            pot=30,
        ))
        assert action.action == "fold"

    def test_check_weak_hand_when_no_bluff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.10)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.random.random", lambda: 0.99)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(
            phase="flop",
            community_cards=["Qs", "Jd", "4c"],
            hole_cards=["2h", "7d"],
            to_call=0,
            pot=20,
        ))
        assert action.action == "check"


class TestHybridGTOPushFold:
    def test_push_allin_when_short(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.72)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(my_stack=20, blind=(1, 2), to_call=0))
        assert action.action == "allin"

    def test_fold_desperate_when_weak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.05)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.should_push", lambda *_a, **_k: False)
        strategy = HybridGTO()
        action = strategy.decide(_ctx(my_stack=40, blind=(5, 10), to_call=30))
        assert action.action in {"fold", "check"}


class TestHybridGTOOpponentTracking:
    def test_opponent_tracking_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.70)
        strategy = HybridGTO()
        context = _ctx(
            to_call=6,
            action_history=[
                ActionRecord(phase="preflop", player="opp1", action="raise", amount=6),
                ActionRecord(phase="flop", player="opp1", action="bet", amount=10),
            ],
        )
        strategy.decide(context)
        assert strategy.opponent_tracker.get_profile("opp1") is not None

    def test_trap_vs_aggressive_opponent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.72)
        strategy = HybridGTO()
        aggressive_history = [
            ActionRecord(phase="preflop", player="opp1", action="raise", amount=6),
            ActionRecord(phase="flop", player="opp1", action="raise", amount=12),
            ActionRecord(phase="turn", player="opp1", action="raise", amount=24),
        ]
        context = _ctx(
            phase="flop",
            community_cards=["As", "Kd", "7c"],
            to_call=6,
            action_history=aggressive_history,
        )
        action = strategy.decide(context)
        assert action.action in {"call", "raise"}

    @pytest.mark.property
    def test_draw_hand_plays_aggressively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.estimated_equity", lambda *_a, **_k: 0.30)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.has_flush_draw", lambda *_a: True)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.has_straight_draw", lambda *_a: False)
        monkeypatch.setattr("holdem_agent.strategy.builtins.hybrid_gto.random.random", lambda: 0.01)
        strategy = HybridGTO()
        context = _ctx(
            phase="flop",
            community_cards=["Qs", "Js", "2c"],
            hole_cards=["As", "Ts"],
            to_call=0,
            pot=20,
            min_raise=4,
        )
        action = strategy.decide(context)
        assert action.action in {"raise", "check"}


class TestHybridGTOGenomeClamp:
    def test_genome_clamp(self) -> None:
        genome = HybridGTO._default_genome()
        clamped = genome.clamp()
        assert 0.0 <= clamped.cbet_frequency <= 1.0
        assert 0.0 <= clamped.bluff_frequency <= 0.30
        assert 0.5 <= clamped.raise_size_pot_fraction <= 3.0