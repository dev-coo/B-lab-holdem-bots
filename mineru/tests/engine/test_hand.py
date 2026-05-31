from holdem_agent.engine.hand import HandState
from holdem_agent.models.state import ActionRecord, PlayerState


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
    "phase": "flop",
    "community_cards": ["2c", "7d", "Ts"],
    "pot": 12,
    "my_stack": 292,
    "to_call": 4,
    "min_raise": 8,
    "players": [
        {"name": "bot-A", "stack": 292, "position": "btn", "status": "active", "action": "bet", "bet": 4},
        {"name": "bot-B", "stack": 294, "position": "sb", "status": "active", "action": "fold", "bet": 0},
        {"name": "bot-C", "stack": 290, "position": "bb", "status": "active", "action": "call", "bet": 4},
    ],
    "action_history": [
        {"phase": "preflop", "player": "bot-B", "action": "fold", "amount": 0},
        {"phase": "preflop", "player": "bot-C", "action": "call", "amount": 2},
        {"phase": "flop", "player": "bot-A", "action": "bet", "amount": 4},
    ],
}

SAMPLE_PHASE_CHANGE = {
    "room_id": 1,
    "phase": "turn",
    "community_cards": ["2c", "7d", "Ts", "Jc"],
}


def test_create_empty_hand_state() -> None:
    hand = HandState()

    assert hand.hand_number == 0
    assert hand.phase == "preflop"
    assert hand.pot == 0
    assert hand.my_stack == 0
    assert hand.my_seat == ""
    assert hand.hole_cards == []
    assert hand.community_cards == []
    assert hand.to_call == 0
    assert hand.min_raise == 0
    assert hand.blind == (0, 0)
    assert hand.players == []
    assert hand.action_history == []


def test_update_from_hand_start_sets_initial_hand_state() -> None:
    hand = HandState(to_call=99, min_raise=77, community_cards=["As"], action_history=[ActionRecord(phase="river", player="x", action="bet", amount=1)])

    hand.update_from_hand_start(SAMPLE_HAND_START)

    assert hand.hand_number == 1
    assert hand.phase == "preflop"
    assert hand.hole_cards == ["Ah", "Kh"]
    assert hand.my_stack == 298
    assert hand.my_seat == "btn"
    assert hand.blind == (1, 2)
    assert hand.community_cards == []
    assert hand.to_call == 0
    assert hand.min_raise == 0
    assert hand.players == [
        PlayerState(name="bot-A", stack=298, position="btn", status="active", action=None, bet=0),
        PlayerState(name="bot-B", stack=297, position="sb", status="active", action=None, bet=1),
        PlayerState(name="bot-C", stack=296, position="bb", status="active", action=None, bet=2),
    ]
    assert hand.action_history == []
    assert hand.pot == 3


def test_update_from_action_request_updates_runtime_fields() -> None:
    hand = HandState()
    hand.update_from_hand_start(SAMPLE_HAND_START)

    hand.update_from_action_request(SAMPLE_ACTION_REQUEST)

    assert hand.phase == "flop"
    assert hand.community_cards == ["2c", "7d", "Ts"]
    assert hand.pot == 12
    assert hand.my_stack == 292
    assert hand.to_call == 4
    assert hand.min_raise == 8
    assert hand.players[0] == PlayerState(name="bot-A", stack=292, position="btn", status="active", action="bet", bet=4)
    assert hand.action_history == [
        ActionRecord(phase="preflop", player="bot-B", action="fold", amount=0),
        ActionRecord(phase="preflop", player="bot-C", action="call", amount=2),
        ActionRecord(phase="flop", player="bot-A", action="bet", amount=4),
    ]


def test_update_from_phase_change_updates_phase_and_board() -> None:
    hand = HandState()
    hand.update_from_hand_start(SAMPLE_HAND_START)

    hand.update_from_phase_change(SAMPLE_PHASE_CHANGE)

    assert hand.phase == "turn"
    assert hand.community_cards == ["2c", "7d", "Ts", "Jc"]
