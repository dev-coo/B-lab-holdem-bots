from __future__ import annotations

import dataclasses


DEFAULT_POSITIONS: tuple[str, ...] = ("btn", "sb", "bb", "utg", "co")


def _default_position_threshold(value: float) -> dict[str, float]:
    return {position: float(value) for position in DEFAULT_POSITIONS}


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


@dataclasses.dataclass
class StrategyGenome:
    preflop_raise_threshold: dict[str, float] = dataclasses.field(
        default_factory=lambda: _default_position_threshold(0.35),
    )
    preflop_call_threshold: dict[str, float] = dataclasses.field(
        default_factory=lambda: _default_position_threshold(0.60),
    )
    preflop_3bet_threshold: dict[str, float] = dataclasses.field(
        default_factory=lambda: _default_position_threshold(0.08),
    )
    cbet_frequency: float = 0.55
    cbet_size_pot_fraction: float = 0.55
    raise_size_pot_fraction: float = 1.0
    three_bet_size_pot_fraction: float = 1.2
    bluff_frequency: float = 0.12
    semi_bluff_equity_threshold: float = 0.25
    river_bluff_frequency: float = 0.05
    fold_to_raise_equity: float = 0.25
    check_raise_frequency: float = 0.07
    donk_bet_frequency: float = 0.07
    m_conservative: float = 15.0
    m_desperate: float = 5.0
    exploit_aggression: float = 0.5
    adapt_speed: float = 0.08

    def clamp(self) -> "StrategyGenome":
        return StrategyGenome(
            preflop_raise_threshold={
                position: _clamp(value, 0.0, 1.0)
                for position, value in self.preflop_raise_threshold.items()
            },
            preflop_call_threshold={
                position: _clamp(value, 0.0, 1.0)
                for position, value in self.preflop_call_threshold.items()
            },
            preflop_3bet_threshold={
                position: _clamp(value, 0.0, 1.0)
                for position, value in self.preflop_3bet_threshold.items()
            },
            cbet_frequency=_clamp(self.cbet_frequency, 0.0, 1.0),
            cbet_size_pot_fraction=_clamp(self.cbet_size_pot_fraction, 0.25, 1.0),
            raise_size_pot_fraction=_clamp(self.raise_size_pot_fraction, 0.5, 3.0),
            three_bet_size_pot_fraction=_clamp(self.three_bet_size_pot_fraction, 0.5, 3.0),
            bluff_frequency=_clamp(self.bluff_frequency, 0.0, 0.30),
            semi_bluff_equity_threshold=_clamp(self.semi_bluff_equity_threshold, 0.15, 0.40),
            river_bluff_frequency=_clamp(self.river_bluff_frequency, 0.0, 0.15),
            fold_to_raise_equity=_clamp(self.fold_to_raise_equity, 0.0, 0.50),
            check_raise_frequency=_clamp(self.check_raise_frequency, 0.0, 0.20),
            donk_bet_frequency=_clamp(self.donk_bet_frequency, 0.0, 0.20),
            m_conservative=_clamp(self.m_conservative, 10.0, 25.0),
            m_desperate=_clamp(self.m_desperate, 3.0, 8.0),
            exploit_aggression=_clamp(self.exploit_aggression, 0.0, 1.0),
            adapt_speed=_clamp(self.adapt_speed, 0.01, 0.5),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyGenome":
        return cls(
            preflop_raise_threshold=_coerce_position_dict(
                data.get("preflop_raise_threshold"),
                cls().preflop_raise_threshold,
            ),
            preflop_call_threshold=_coerce_position_dict(
                data.get("preflop_call_threshold"),
                cls().preflop_call_threshold,
            ),
            preflop_3bet_threshold=_coerce_position_dict(
                data.get("preflop_3bet_threshold"),
                cls().preflop_3bet_threshold,
            ),
            cbet_frequency=float(data.get("cbet_frequency", cls().cbet_frequency)),
            cbet_size_pot_fraction=float(data.get("cbet_size_pot_fraction", cls().cbet_size_pot_fraction)),
            raise_size_pot_fraction=float(data.get("raise_size_pot_fraction", cls().raise_size_pot_fraction)),
            three_bet_size_pot_fraction=float(
                data.get("three_bet_size_pot_fraction", cls().three_bet_size_pot_fraction)
            ),
            bluff_frequency=float(data.get("bluff_frequency", cls().bluff_frequency)),
            semi_bluff_equity_threshold=float(
                data.get("semi_bluff_equity_threshold", cls().semi_bluff_equity_threshold)
            ),
            river_bluff_frequency=float(data.get("river_bluff_frequency", cls().river_bluff_frequency)),
            fold_to_raise_equity=float(data.get("fold_to_raise_equity", cls().fold_to_raise_equity)),
            check_raise_frequency=float(data.get("check_raise_frequency", cls().check_raise_frequency)),
            donk_bet_frequency=float(data.get("donk_bet_frequency", cls().donk_bet_frequency)),
            m_conservative=float(data.get("m_conservative", cls().m_conservative)),
            m_desperate=float(data.get("m_desperate", cls().m_desperate)),
            exploit_aggression=float(data.get("exploit_aggression", cls().exploit_aggression)),
            adapt_speed=float(data.get("adapt_speed", cls().adapt_speed)),
        )


def _coerce_position_dict(
    values: dict[str, float] | None,
    default_values: dict[str, float],
) -> dict[str, float]:
    if not isinstance(values, dict):
        return dict(default_values)

    return {
        position: float(values.get(position, default_values[position]))
        for position in DEFAULT_POSITIONS
    }


def calling_station_genome() -> StrategyGenome:
    return StrategyGenome(
        preflop_raise_threshold=_default_position_threshold(0.95),
        preflop_call_threshold=_default_position_threshold(0.50),
        preflop_3bet_threshold=_default_position_threshold(0.05),
        cbet_frequency=0.30,
        cbet_size_pot_fraction=0.55,
        raise_size_pot_fraction=1.0,
        three_bet_size_pot_fraction=1.0,
        bluff_frequency=0.05,
        semi_bluff_equity_threshold=0.25,
        river_bluff_frequency=0.03,
        fold_to_raise_equity=0.25,
        check_raise_frequency=0.02,
        donk_bet_frequency=0.02,
        m_conservative=15.0,
        m_desperate=5.0,
        exploit_aggression=0.10,
        adapt_speed=0.05,
    )
