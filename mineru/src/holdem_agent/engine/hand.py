import dataclasses

from holdem_agent.models.state import ActionRecord, PlayerState


@dataclasses.dataclass
class HandState:
    """Tracks state within a single hand."""

    hand_number: int = 0
    phase: str = "preflop"
    pot: int = 0
    my_stack: int = 0
    my_seat: str = ""
    hole_cards: list[str] = dataclasses.field(default_factory=list)
    community_cards: list[str] = dataclasses.field(default_factory=list)
    to_call: int = 0
    min_raise: int = 0
    blind: tuple[int, int] = (0, 0)
    players: list[PlayerState] = dataclasses.field(default_factory=list)
    action_history: list[ActionRecord] = dataclasses.field(default_factory=list)

    def update_from_hand_start(self, msg: dict) -> None:
        """Update state from hand_start event."""

        self.hand_number = msg["hand_number"]
        self.hole_cards = list(msg["your_cards"])
        self.my_stack = msg["your_stack"]
        self.my_seat = msg["your_seat"]
        self.blind = tuple(msg["blind"])
        self.players = [PlayerState(**player) for player in msg["players"]]
        self.community_cards = []
        self.action_history = []
        self.phase = "preflop"
        self.pot = sum(player.bet for player in self.players)
        self.to_call = 0
        self.min_raise = 0

    def update_from_action_request(self, msg: dict) -> None:
        """Update state from action_request event.

        action_request is self-contained per spec §5.3 — it carries
        hand_number / your_cards / seat. Pulling them in here keeps the
        bot operational after a mid-hand reconnect when no hand_start
        precedes the action_request.
        """

        if "hand_number" in msg:
            self.hand_number = msg["hand_number"]
        if isinstance(msg.get("your_cards"), list):
            self.hole_cards = list(msg["your_cards"])
        if isinstance(msg.get("seat"), str):
            self.my_seat = msg["seat"]
        if isinstance(msg.get("blind"), (list, tuple)) and len(msg["blind"]) == 2:
            self.blind = (int(msg["blind"][0]), int(msg["blind"][1]))
        self.community_cards = list(msg.get("community_cards", []))
        self.phase = msg["phase"]
        self.pot = msg["pot"]
        self.my_stack = msg["my_stack"]
        self.to_call = msg["to_call"]
        self.min_raise = msg["min_raise"]
        self.players = [PlayerState(**player) for player in msg.get("players", [])]
        self.action_history = [ActionRecord(**action) for action in msg.get("action_history", [])]

    def update_from_phase_change(self, msg: dict) -> None:
        """Update state from phase_change event."""

        self.phase = msg["phase"]
        self.community_cards = list(msg.get("community_cards", []))
