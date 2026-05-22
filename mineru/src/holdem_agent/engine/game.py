import dataclasses

from holdem_agent.engine.hand import HandState
from holdem_agent.models.state import BlindLevel, PlayerInfo
from holdem_agent.strategy.base import DecisionContext


@dataclasses.dataclass
class GameState:
    """Per-room game state."""

    room_id: int
    starting_stack: int = 300
    blind_structure: list[BlindLevel] = dataclasses.field(default_factory=list)
    players: list[PlayerInfo] = dataclasses.field(default_factory=list)
    hand: HandState = dataclasses.field(default_factory=HandState)
    is_active: bool = True
    final_rank: int | None = None
    final_chips: int | None = None


class GameTracker:
    """Manages game states across multiple rooms."""

    def __init__(self) -> None:
        self._games: dict[int, GameState] = {}

    def get_or_create(self, room_id: int) -> GameState:
        """Get existing or create new game state for room."""

        if room_id not in self._games:
            self._games[room_id] = GameState(room_id=room_id)
        return self._games[room_id]

    def handle_game_start(self, msg: dict) -> GameState:
        """Process game_start event."""

        game = self.get_or_create(msg["room_id"])
        game.starting_stack = msg["starting_stack"]
        game.blind_structure = [BlindLevel(**blind_level) for blind_level in msg.get("blind_structure", [])]
        game.players = [PlayerInfo(**player) for player in msg.get("players", [])]
        game.is_active = True
        game.final_rank = None
        game.final_chips = None
        return game

    def handle_hand_start(self, msg: dict) -> GameState:
        """Process hand_start event."""

        game = self.get_or_create(msg["room_id"])
        game.hand = HandState()
        game.hand.update_from_hand_start(msg)
        return game

    def handle_action_request(self, msg: dict) -> DecisionContext:
        """Process action_request and return strategy context."""

        game = self.get_or_create(msg["room_id"])
        game.hand.update_from_action_request(msg)
        return self._build_context(game)

    def handle_phase_change(self, msg: dict) -> None:
        """Process phase_change event."""

        game = self.get_or_create(msg["room_id"])
        game.hand.update_from_phase_change(msg)

    def handle_hand_result(self, msg: dict) -> None:
        """Process hand_result event."""

        game = self.get_or_create(msg["room_id"])
        game.final_chips = msg.get("your_stack")

    def handle_game_end(self, msg: dict) -> None:
        """Process game_end event."""

        game = self.get_or_create(msg["room_id"])
        game.is_active = False
        rankings = msg.get("rankings", [])
        if rankings:
            game.final_rank = rankings[0].get("rank")
            game.final_chips = rankings[0].get("chips")

    def remove_game(self, room_id: int) -> None:
        """Remove finished game."""

        self._games.pop(room_id, None)

    @property
    def active_games(self) -> list[GameState]:
        return [game for game in self._games.values() if game.is_active]

    def _build_context(self, game: GameState) -> DecisionContext:
        """Convert game state to DecisionContext for strategy."""

        hand = game.hand
        return DecisionContext(
            hand_number=hand.hand_number,
            hole_cards=hand.hole_cards,
            community_cards=hand.community_cards,
            phase=hand.phase,
            pot=hand.pot,
            my_stack=hand.my_stack,
            my_seat=hand.my_seat,
            to_call=hand.to_call,
            min_raise=hand.min_raise,
            blind=hand.blind,
            players=hand.players,
            action_history=hand.action_history,
            blind_structure=game.blind_structure,
            starting_stack=game.starting_stack,
            room_id=game.room_id,
        )
