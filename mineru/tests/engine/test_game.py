from holdem_agent.engine.game import GameTracker
from holdem_agent.engine.hand import HandState
from holdem_agent.models.state import BlindLevel, PlayerInfo
from holdem_agent.strategy.base import DecisionContext


SAMPLE_GAME_START = {
    "room_id": 1,
    "starting_stack": 300,
    "blind_structure": [
        {"level": 1, "small": 1, "big": 2, "hands": 0},
        {"level": 2, "small": 2, "big": 4, "hands": 10},
    ],
    "players": [
        {"name": "bot-A", "type": "bot", "stack": 300},
        {"name": "bot-B", "type": "bot", "stack": 300},
        {"name": "bot-C", "type": "bot", "stack": 300},
    ],
}

SAMPLE_HAND_START = {
    "room_id": 1,
    "hand_number": 1,
    "your_cards": ["Ah", "Kh"],
    "your_stack": 298,
    "your_seat": "btn",
    "blind": [1, 2],
    "players": [
        {"name": "bot-A", "stack": 298, "position": "btn", "status": "active", "action": None, "bet": 0},
        {"name": "bot-B", "stack": 297, "position": "sb", "status": "active", "action": None, "bet": 1},
        {"name": "bot-C", "stack": 296, "position": "bb", "status": "active", "action": None, "bet": 2},
    ],
}

SAMPLE_ACTION_REQUEST = {
    "room_id": 1,
    "phase": "preflop",
    "community_cards": [],
    "pot": 6,
    "my_stack": 298,
    "to_call": 2,
    "min_raise": 4,
    "players": [
        {"name": "bot-A", "stack": 298, "position": "btn", "status": "active", "action": None, "bet": 0},
        {"name": "bot-B", "stack": 297, "position": "sb", "status": "active", "action": "call", "bet": 2},
        {"name": "bot-C", "stack": 296, "position": "bb", "status": "active", "action": "check", "bet": 2},
    ],
    "action_history": [
        {"phase": "preflop", "player": "bot-B", "action": "call", "amount": 1},
    ],
}

SAMPLE_GAME_END = {
    "room_id": 1,
    "rankings": [
        {"rank": 2, "name": "bot-A", "chips": 150},
        {"rank": 1, "name": "bot-B", "chips": 450},
    ],
}


def test_tracker_creation_starts_empty() -> None:
    tracker = GameTracker()

    assert tracker.active_games == []


def test_get_or_create_returns_same_game_for_same_room() -> None:
    tracker = GameTracker()

    first = tracker.get_or_create(1)
    second = tracker.get_or_create(1)

    assert first is second
    assert first.room_id == 1


def test_get_or_create_returns_distinct_games_for_different_rooms() -> None:
    tracker = GameTracker()

    first = tracker.get_or_create(1)
    second = tracker.get_or_create(2)

    assert first is not second
    assert {game.room_id for game in tracker.active_games} == {1, 2}


def test_handle_game_start_populates_blind_structure_and_players() -> None:
    tracker = GameTracker()

    game = tracker.handle_game_start(SAMPLE_GAME_START)

    assert game.room_id == 1
    assert game.starting_stack == 300
    assert game.blind_structure == [
        BlindLevel(level=1, small=1, big=2, hands=0),
        BlindLevel(level=2, small=2, big=4, hands=10),
    ]
    assert game.players == [
        PlayerInfo(name="bot-A", type="bot", stack=300),
        PlayerInfo(name="bot-B", type="bot", stack=300),
        PlayerInfo(name="bot-C", type="bot", stack=300),
    ]
    assert game.is_active is True


def test_handle_hand_start_resets_hand_state() -> None:
    tracker = GameTracker()
    game = tracker.get_or_create(1)
    game.hand = HandState(hand_number=99, phase="river", community_cards=["As"], to_call=5)

    updated = tracker.handle_hand_start(SAMPLE_HAND_START)

    assert updated is game
    assert updated.hand.hand_number == 1
    assert updated.hand.phase == "preflop"
    assert updated.hand.community_cards == []
    assert updated.hand.to_call == 0
    assert updated.hand.hole_cards == ["Ah", "Kh"]


def test_handle_action_request_returns_decision_context() -> None:
    tracker = GameTracker()
    tracker.handle_game_start(SAMPLE_GAME_START)
    tracker.handle_hand_start(SAMPLE_HAND_START)

    context = tracker.handle_action_request(SAMPLE_ACTION_REQUEST)

    assert isinstance(context, DecisionContext)
    assert context.hand_number == 1
    assert context.hole_cards == ["Ah", "Kh"]
    assert context.phase == "preflop"
    assert context.pot == 6
    assert context.my_stack == 298
    assert context.my_seat == "btn"
    assert context.to_call == 2
    assert context.min_raise == 4
    assert context.blind == (1, 2)
    assert context.room_id == 1
    assert context.starting_stack == 300
    assert context.blind_structure == [
        BlindLevel(level=1, small=1, big=2, hands=0),
        BlindLevel(level=2, small=2, big=4, hands=10),
    ]


def test_handle_game_end_marks_game_inactive() -> None:
    tracker = GameTracker()
    tracker.handle_game_start(SAMPLE_GAME_START)

    tracker.handle_game_end(SAMPLE_GAME_END)

    game = tracker.get_or_create(1)
    assert game.is_active is False
    assert game.final_rank == 2
    assert game.final_chips == 150
    assert tracker.active_games == []


def test_multi_room_games_are_tracked_independently() -> None:
    tracker = GameTracker()

    tracker.handle_game_start(SAMPLE_GAME_START)
    tracker.handle_hand_start(SAMPLE_HAND_START)
    tracker.handle_action_request(SAMPLE_ACTION_REQUEST)

    tracker.handle_game_start({
        "room_id": 2,
        "starting_stack": 500,
        "blind_structure": [{"level": 1, "small": 5, "big": 10, "hands": 0}],
        "players": [{"name": "bot-X", "type": "bot", "stack": 500}],
    })
    tracker.handle_hand_start({
        "room_id": 2,
        "hand_number": 7,
        "your_cards": ["Qs", "Qd"],
        "your_stack": 500,
        "your_seat": "bb",
        "blind": [5, 10],
        "players": [{"name": "bot-X", "stack": 490, "position": "bb", "status": "active", "action": None, "bet": 10}],
    })

    first = tracker.get_or_create(1)
    second = tracker.get_or_create(2)

    assert first.room_id == 1
    assert first.hand.hand_number == 1
    assert first.hand.hole_cards == ["Ah", "Kh"]
    assert second.room_id == 2
    assert second.starting_stack == 500
    assert second.hand.hand_number == 7
    assert second.hand.hole_cards == ["Qs", "Qd"]
