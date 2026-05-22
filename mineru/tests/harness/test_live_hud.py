from io import StringIO

from holdem_agent.harness.live_hud import LiveHud


def test_live_hud_tracks_rank_and_hand_results_by_bot_name():
    output = StringIO()
    hud = LiveHud("bot-A", output=output)

    hud.game_started({"type": "game_start", "room_id": 1})
    hud.hand_started(
        {
            "type": "hand_start",
            "room_id": 1,
            "hand_number": 1,
            "your_cards": ["Ah", "Kh"],
            "your_stack": 298,
        }
    )
    hud.action_sent(1, "call", None)
    hud.hand_finished(
        {
            "type": "hand_result",
            "room_id": 1,
            "winners": [{"name": "bot-A", "amount": 20}],
            "pot": 20,
        }
    )
    hud.game_finished(
        {
            "type": "game_end",
            "room_id": 1,
            "rankings": [
                {"rank": 2, "name": "bot-B", "chips": 0},
                {"rank": 1, "name": "bot-A", "chips": 600},
            ],
        }
    )

    assert hud.games_started == 1
    assert hud.games_finished == 1
    assert hud.wins == 1
    assert hud.hands_seen == 1
    assert hud.hands_won == 1
    assert hud.actions["call"] == 1
    rendered = output.getvalue()
    assert "\x1b[H\x1b[2J" in rendered
    assert "W-L=1-0" in rendered
    assert "Hands: seen=1 won=1 win=100.0%" in rendered
    assert "Actions: call:1" in rendered
