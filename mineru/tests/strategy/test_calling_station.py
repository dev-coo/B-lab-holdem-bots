from __future__ import annotations

from holdem_agent.strategy.base import Action, DecisionContext
from holdem_agent.strategy.builtins.calling_station import CallingStation
from holdem_agent.strategy.genome import StrategyGenome, calling_station_genome


def _make_context(to_call: int = 0, **overrides) -> DecisionContext:
    defaults = dict(
        hand_number=1,
        hole_cards=["Ah", "Kh"],
        community_cards=[],
        phase="preflop",
        pot=10,
        my_stack=300,
        my_seat="btn",
        to_call=to_call,
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


def test_calling_station_checks_when_free() -> None:
    strategy = CallingStation()
    context = _make_context(to_call=0)
    assert strategy.decide(context) == Action(action="check", reasoning="Calling station: free check")


def test_calling_station_calls_when_bet() -> None:
    strategy = CallingStation()
    context = _make_context(to_call=10)
    assert strategy.decide(context) == Action(action="call", reasoning="Calling station: always call")


def test_calling_station_calls_large_bet() -> None:
    strategy = CallingStation()
    context = _make_context(to_call=1000)
    assert strategy.decide(context) == Action(action="call", reasoning="Calling station: always call")


def test_calling_station_genome() -> None:
    strategy = CallingStation()
    assert strategy.genome == calling_station_genome()


def test_calling_station_name() -> None:
    strategy = CallingStation()
    assert strategy.name == "calling-station"


def test_calling_station_from_genome() -> None:
    genome = StrategyGenome()
    strategy = CallingStation.from_genome(genome)
    assert isinstance(strategy, CallingStation)


def test_calling_station_from_genome_ignores_genome() -> None:
    custom_genome = StrategyGenome(cbet_frequency=1.0, m_conservative=25.0)
    strategy = CallingStation.from_genome(custom_genome)

    assert strategy.decide(_make_context(to_call=50)) == Action(action="call", reasoning="Calling station: always call")
    assert strategy.genome == calling_station_genome()
    assert strategy.name == "calling-station"
