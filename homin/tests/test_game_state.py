"""GameState — 이벤트 dispatch 와 재접속 snapshot 복원."""
from __future__ import annotations

from holdem.state.game_state import GameState
from holdem.transport import protocol as p


def _hand_start(room_id: int = 1, bot: str = "my-bot") -> p.HandStart:
    return p.HandStart(
        type="hand_start",
        room_id=room_id,
        hand_number=1,
        your_cards=["Ah", "Kh"],
        your_stack=298,
        your_seat="btn",
        blind=[1, 2],
        players=[
            p.PlayerState(name=bot, stack=298, position="btn", status="active", bet=0),
            p.PlayerState(name="bot-B", stack=297, position="sb", status="active", bet=1),
            p.PlayerState(name="bot-C", stack=296, position="bb", status="active", bet=2),
        ],
    )


def test_hand_start_initializes_state():
    gs = GameState("my-bot")
    gs.handle(_hand_start())
    s = gs.require(1)
    assert s.hand_number == 1
    assert s.my_cards == ["Ah", "Kh"]
    assert s.my_seat == "btn"
    assert s.blind_sb == 1 and s.blind_bb == 2
    assert s.pot == 3  # sb + bb


def test_phase_change_updates_board():
    gs = GameState("my-bot")
    gs.handle(_hand_start())
    gs.handle(p.PhaseChange(
        type="phase_change", room_id=1, phase="flop",
        community_cards=["2s", "7d", "Kc"],
    ))
    s = gs.require(1)
    assert s.phase == "flop"
    assert s.community_cards == ["2s", "7d", "Kc"]


def test_action_performed_appends_history_and_updates_pot():
    gs = GameState("my-bot")
    gs.handle(_hand_start())
    gs.handle(p.ActionPerformed(
        type="action_performed", room_id=1, player="bot-B",
        action="raise", amount=6, pot=9,
    ))
    s = gs.require(1)
    assert s.pot == 9
    assert s.action_history[-1].action == "raise"
    assert s.action_history[-1].player == "bot-B"


def test_action_performed_by_me_updates_my_stack():
    gs = GameState("my-bot")
    gs.handle(_hand_start())
    gs.handle(p.ActionPerformed(
        type="action_performed", room_id=1, player="my-bot",
        action="call", amount=2, pot=6,
        players=[p.PlayerState(name="my-bot", stack=296, position="btn", bet=2)],
    ))
    s = gs.require(1)
    assert s.my_stack == 296


def test_multi_room_isolation():
    gs = GameState("my-bot")
    gs.handle(_hand_start(room_id=1))
    gs.handle(_hand_start(room_id=2))
    assert gs.require(1).room_id == 1
    assert gs.require(2).room_id == 2
    # 2번 방에만 phase_change
    gs.handle(p.PhaseChange(type="phase_change", room_id=2, phase="flop",
                            community_cards=["Ah", "2d", "3c"]))
    assert gs.get(1).phase == "preflop"
    assert gs.get(2).phase == "flop"


def test_game_end_cleans_room():
    gs = GameState("my-bot")
    gs.handle(_hand_start(room_id=5))
    gs.handle(p.GameEnd(type="game_end", room_id=5, rankings=[]))
    assert gs.get(5) is None


# --- P5-2: starting_table_size ---

def test_game_start_records_starting_size():
    gs = GameState("my-bot")
    ev = p.GameStart(
        type="game_start", room_id=7,
        players=[{"name": f"p{i}"} for i in range(5)],
        starting_stack=1000, blind_structure=[],
    )
    gs.handle(ev)
    assert gs.starting_table_size(7) == 5


def test_starting_size_none_without_game_start():
    gs = GameState("my-bot")
    assert gs.starting_table_size(99) is None


def test_game_end_clears_starting_size():
    gs = GameState("my-bot")
    gs.handle(p.GameStart(
        type="game_start", room_id=10,
        players=[{"name": "a"}, {"name": "b"}],
        starting_stack=1000, blind_structure=[],
    ))
    assert gs.starting_table_size(10) == 2
    gs.handle(p.GameEnd(type="game_end", room_id=10, rankings=[]))
    assert gs.starting_table_size(10) is None


def test_action_request_fallback_records_starting_size():
    """GameStart / hand_start 미수신 시 ActionRequest 의 players 로 starting_size 보강."""
    gs = GameState("my-bot")
    players = [
        p.PlayerState(name="my-bot", position="btn", stack=200, bet=0, status="active"),
        p.PlayerState(name="a", position="sb", stack=200, bet=0, status="active"),
        p.PlayerState(name="b", position="bb", stack=200, bet=0, status="active"),
        p.PlayerState(name="c", position="utg", stack=200, bet=0, status="active"),
        p.PlayerState(name="d", position="co", stack=200, bet=0, status="active"),
    ]
    req = p.ActionRequest(
        type="action_request", room_id=11, hand_number=1,
        your_cards=["As", "Ks"], community_cards=[], phase="preflop",
        pot=3, my_stack=200, to_call=2, min_raise=4,
        blind=[1, 2], seat="btn", players=players, action_history=[],
    )
    gs.handle(req)
    assert gs.starting_table_size(11) == 5


def test_action_request_keeps_max_observed_starting_size():
    """ActionRequest fallback 도 max(observed) 유지 — 후속 핸드에서 인원 줄어도 보존."""
    gs = GameState("my-bot")
    full = [
        p.PlayerState(name=f"p{i}", position="btn", stack=200, bet=0, status="active")
        for i in range(6)
    ]
    req5 = p.ActionRequest(
        type="action_request", room_id=12, hand_number=1,
        your_cards=["As", "Ks"], community_cards=[], phase="preflop",
        pot=3, my_stack=200, to_call=2, min_raise=4,
        blind=[1, 2], seat="btn", players=full, action_history=[],
    )
    gs.handle(req5)
    assert gs.starting_table_size(12) == 6
    # 다음 핸드는 4명 — starting_size 는 6 유지.
    req4 = p.ActionRequest(
        type="action_request", room_id=12, hand_number=2,
        your_cards=["Qs", "Qd"], community_cards=[], phase="preflop",
        pot=3, my_stack=200, to_call=2, min_raise=4,
        blind=[1, 2], seat="btn", players=full[:4], action_history=[],
    )
    gs.handle(req4)
    assert gs.starting_table_size(12) == 6


def test_joined_room_records_starting_size_from_players():
    """JoinedRoom 의 players 길이로도 starting_size 보강."""
    gs = GameState("my-bot")
    ev = p.JoinedRoom(
        type="joined_room", room_id=13, reconnected=False,
        players=["my-bot", "a", "b", "c", "d", "e"],
        snapshot=None,
    )
    gs.handle(ev)
    assert gs.starting_table_size(13) == 6


def test_joined_room_snapshot_restores_state():
    gs = GameState("my-bot")
    ev = p.JoinedRoom(
        type="joined_room", room_id=1, reconnected=True,
        players=["my-bot", "bot-B"],
        snapshot=p.JoinedSnapshot(
            hand_number=5, phase="flop",
            community_cards=["2s", "7d", "Kc"],
            pot=120, blind=[5, 10],
            players=[
                p.PlayerState(name="my-bot", stack=280, position="btn", status="active", bet=0),
                p.PlayerState(name="bot-B", stack=320, position="bb", status="active", action="call", bet=10),
            ],
            action_history=[
                p.HistoryEntry(phase="preflop", player="bot-B", action="call", amount=10),
            ],
            your_cards=["Ah", "Kh"],
        ),
    )
    gs.handle(ev)
    s = gs.require(1)
    assert s.hand_number == 5
    assert s.phase == "flop"
    assert s.my_stack == 280        # snapshot 에 my_stack 없음 → players[] 에서 추출
    assert s.my_seat == "btn"
    assert s.pot == 120
    assert s.my_cards == ["Ah", "Kh"]


def test_joined_room_no_snapshot_clears_room():
    gs = GameState("my-bot")
    gs.handle(_hand_start(room_id=3))
    assert gs.get(3) is not None
    gs.handle(p.JoinedRoom(type="joined_room", room_id=3, reconnected=True, players=[], snapshot=None))
    assert gs.get(3) is None


def test_action_request_without_prior_state_bootstraps():
    """재접속 직후 action_request 가 먼저 오는 경우."""
    gs = GameState("my-bot")
    ev = p.ActionRequest(
        type="action_request", room_id=2, hand_number=7,
        your_cards=["Qd", "Qs"],
        community_cards=["As", "Kh"],  # invalid count but tolerated
        phase="flop", pot=24, my_stack=150, to_call=0, min_raise=4,
        blind=[2, 4], seat="bb",
        players=[p.PlayerState(name="my-bot", stack=150, position="bb", bet=0)],
        action_history=[],
    )
    gs.handle(ev)
    s = gs.require(2)
    assert s.hand_number == 7
    assert s.my_cards == ["Qd", "Qs"]
    assert s.blind_bb == 4
