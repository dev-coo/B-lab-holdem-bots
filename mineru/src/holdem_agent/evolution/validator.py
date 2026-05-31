from __future__ import annotations

from holdem_agent.strategy.genome import StrategyGenome


class StrategyValidator:
    """Validate generated strategies for basic sanity."""

    def validate(self, genome: StrategyGenome) -> list[str]:
        """Validate a genome. Returns list of issues (empty = valid)."""
        issues = []

        # Check all values are within valid ranges after clamping
        clamped = genome.clamp()

        # Check position dicts have all required keys
        required_positions = ("btn", "sb", "bb", "utg", "co")
        for field_name in (
            "preflop_raise_threshold",
            "preflop_call_threshold",
            "preflop_3bet_threshold",
        ):
            val = getattr(genome, field_name)
            if not isinstance(val, dict):
                issues.append(f"{field_name} is not a dict")
                continue
            for pos in required_positions:
                if pos not in val:
                    issues.append(f"{field_name} missing position {pos}")

        # Check thresholds are sensible: raise < call (tighter raise = higher threshold)
        for pos in required_positions:
            raise_t = genome.preflop_raise_threshold.get(pos, 0.5)
            call_t = genome.preflop_call_threshold.get(pos, 0.5)
            if raise_t < call_t * 0.3:
                issues.append(f"{pos}: raise threshold suspiciously low vs call threshold")

        # Check bluff frequency is reasonable
        if clamped.bluff_frequency > 0.3:
            issues.append("bluff_frequency too high after clamping")

        # Check M values make sense
        if clamped.m_desperate >= clamped.m_conservative:
            issues.append("m_desperate should be less than m_conservative")

        return issues

    def is_valid(self, genome: StrategyGenome) -> bool:
        """Quick check if genome passes validation."""
        return len(self.validate(genome)) == 0

    def sanitize(self, genome: StrategyGenome) -> StrategyGenome:
        """Clamp and return a valid genome."""
        return genome.clamp()
