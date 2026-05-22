from __future__ import annotations

import pytest


@pytest.fixture
def sample_hole_cards() -> list[str]:
    return ["Ah", "Kh"]


@pytest.fixture
def sample_community_flop() -> list[str]:
    return ["2s", "7d", "Kc"]


@pytest.fixture
def sample_community_turn() -> list[str]:
    return ["2s", "7d", "Kc", "4h"]


@pytest.fixture
def sample_community_river() -> list[str]:
    return ["2s", "7d", "Kc", "4h", "9d"]
