from pydantic import BaseModel, ConfigDict


class GameRecord(BaseModel):
    id: int | None = None
    room_id: int
    strategy_name: str
    started_at: str
    finished_at: str | None = None
    final_rank: int | None = None
    final_chips: int | None = None
    total_hands: int = 0

    model_config = ConfigDict(frozen=True)


class ActionRequestRecord(BaseModel):
    id: int | None = None
    game_id: int
    room_id: int
    hand_number: int
    phase: str
    hole_cards: str
    community_cards: str
    pot: int
    my_stack: int
    to_call: int
    min_raise: int
    seat: str
    players_json: str
    action_history_json: str
    timestamp: str

    model_config = ConfigDict(frozen=True)


class DecisionRecord(BaseModel):
    id: int | None = None
    game_id: int
    room_id: int
    hand_number: int
    action_type: str
    amount: int | None = None
    reasoning: str = ""
    strategy_name: str
    timestamp: str

    model_config = ConfigDict(frozen=True)


class HandResultRecord(BaseModel):
    id: int | None = None
    game_id: int
    room_id: int
    hand_number: int
    pot: int
    winners_json: str
    showdown_json: str
    community_cards: str
    eliminated_json: str
    timestamp: str

    model_config = ConfigDict(frozen=True)


class StrategyVersionRecord(BaseModel):
    id: int | None = None
    name: str
    version: int
    genome_json: str
    parent_name: str | None = None
    parent_version: int | None = None
    origin: str
    created_at: str
    games_played: int = 0
    win_rate: float = 0.0

    model_config = ConfigDict(frozen=True)


class StrategyMetrics(BaseModel):
    strategy_name: str
    games_played: int
    win_rate: float
    avg_roi: float
    total_hands: int
    vpip: float
    pfr: float
    money_won: int

    model_config = ConfigDict(frozen=True)
