from __future__ import annotations

import pytest

from holdem_agent.models.state import ActionRecord, PlayerState
from holdem_agent.strategy.analysts.blockers import analyze_blockers
from holdem_agent.strategy.analysts.board_texture import analyze_board_texture
from holdem_agent.strategy.analysts.image import analyze_self_image
from holdem_agent.strategy.analysts.spr import analyze_spr, calculate_spr
from holdem_agent.strategy.base import DecisionContext, Strategy
from holdem_agent.strategy.builtins.omni import OmniStrategy
from holdem_agent.strategy.genome import StrategyGenome
from holdem_agent.strategy.registry import get_strategy, strategy_exists


def _ctx(**overrides) -> DecisionContext:
    defaults = dict(
        hand_number=1,
        hole_cards=["Ah", "Kh"],
        community_cards=[],
        phase="preflop",
        pot=20,
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


class TestOmniAnalysts:
    def test_board_texture_scores_dry_to_wet(self) -> None:
        dry = analyze_board_texture(["Ah", "7d", "2c"])
        wet = analyze_board_texture(["Ts", "Js", "Qs"])

        assert dry.texture_score < wet.texture_score
        assert dry.texture_score < 0.45
        assert wet.texture_score > 0.75
        assert wet.is_monotone is True
        assert wet.connectedness > dry.connectedness

    def test_board_texture_detects_paired_board(self) -> None:
        paired = analyze_board_texture(["Kh", "Kd", "2s"])

        assert paired.is_paired is True
        assert paired.pairedness > 0.0

    def test_blockers_detect_nut_blockers(self) -> None:
        blockers = analyze_blockers(["Ah", "Ks"], ["Qh", "Jh", "Th"])

        assert blockers.blocks_flush is True
        assert blockers.blocks_straight is True
        assert blockers.blocks_ace_high is True
        assert blockers.blocker_score == pytest.approx(1.0)

    def test_spr_classifies_low_and_high_commitment(self) -> None:
        low = analyze_spr(stack=120, pot=80)
        high = analyze_spr(stack=1000, pot=80)

        assert calculate_spr(120, 80) == pytest.approx(1.5)
        assert low.category == "low"
        assert low.prefer_push_fold is True
        assert low.commitment_threshold < high.commitment_threshold

    def test_self_image_rewards_tight_and_values_loose(self) -> None:
        tight_history = [
            ActionRecord(phase="preflop", player="hero", action="fold", amount=0),
            ActionRecord(phase="preflop", player="hero", action="fold", amount=0),
            ActionRecord(phase="preflop", player="hero", action="fold", amount=0),
            ActionRecord(phase="preflop", player="hero", action="call", amount=2),
        ]
        loose_history = [
            ActionRecord(phase="preflop", player="hero", action="raise", amount=6),
            ActionRecord(phase="preflop", player="hero", action="call", amount=6),
            ActionRecord(phase="preflop", player="hero", action="raise", amount=18),
        ]

        tight = analyze_self_image(tight_history, {"hero"})
        loose = analyze_self_image(loose_history, {"hero"})

        assert tight.image == "tight"
        assert tight.bluff_success_bonus > 0.0
        assert loose.image == "loose"
        assert loose.value_size_multiplier > 1.0


class TestOmniStrategy:
    def test_name_and_genome(self) -> None:
        strategy = OmniStrategy()

        assert strategy.name == "omni"
        assert isinstance(strategy.genome, StrategyGenome)
        assert strategy.genome.cbet_frequency > 0.65
        assert issubclass(OmniStrategy, Strategy)

    def test_from_genome(self) -> None:
        genome = StrategyGenome(bluff_frequency=0.22, exploit_aggression=0.75)
        strategy = OmniStrategy.from_genome(genome)

        assert isinstance(strategy, OmniStrategy)
        assert strategy.genome == genome

    def test_registry_auto_registers_omni(self) -> None:
        assert strategy_exists("omni") is True
        assert isinstance(get_strategy("omni"), OmniStrategy)

    def test_texture_aware_cbet_bluff_on_dry_board(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.estimated_equity", lambda *_a, **_k: 0.10)
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.random.random", lambda: 0.01)
        strategy = OmniStrategy()
        context = _ctx(
            phase="flop",
            hole_cards=["2h", "7d"],
            community_cards=["Ah", "7d", "2c"],
            players=[PlayerState(name="hero", stack=300, position="btn", status="active")],
            action_history=[ActionRecord(phase="preflop", player="hero", action="raise", amount=6)],
            to_call=0,
            pot=40,
            min_raise=10,
        )

        action = strategy.decide(context)

        assert action.action == "raise"
        assert action.reasoning.startswith("Omni")

    def test_nut_blocker_bluff_when_not_preflop_raiser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.estimated_equity", lambda *_a, **_k: 0.10)
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.random.random", lambda: 0.01)
        strategy = OmniStrategy()
        context = _ctx(
            phase="river",
            hole_cards=["Ah", "Ks"],
            community_cards=["Qh", "Jh", "Th", "2c", "7d"],
            to_call=0,
            pot=80,
            min_raise=20,
        )

        action = strategy.decide(context)

        assert action.action == "raise"
        assert "bluff" in action.reasoning.lower()

    def test_low_spr_folds_speculative_draw_to_bet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.estimated_equity", lambda *_a, **_k: 0.30)
        strategy = OmniStrategy()
        context = _ctx(
            phase="flop",
            hole_cards=["Ah", "Kh"],
            community_cards=["2h", "7h", "Qc"],
            my_stack=160,
            pot=100,
            to_call=60,
            min_raise=120,
        )

        action = strategy.decide(context)

        assert action.action == "fold"
        assert "low-SPR" in action.reasoning

    def test_low_spr_commits_strong_hand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holdem_agent.strategy.builtins.omni.estimated_equity", lambda *_a, **_k: 0.70)
        strategy = OmniStrategy()
        context = _ctx(
            phase="turn",
            community_cards=["As", "Kd", "7c", "2h"],
            my_stack=150,
            pot=90,
            to_call=50,
            min_raise=100,
        )

        action = strategy.decide(context)

        assert action.action == "allin"
        assert action.reasoning.startswith("Omni")
