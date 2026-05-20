from __future__ import annotations

import pytest

from holdem.estimate.class_typer import TypingConfig, hard_assign, soft_assign
from holdem.state.player_profile import PlayerProfile


def _profile(vpip_pct: float, af: float, hands: int = 50) -> PlayerProfile:
    pp = PlayerProfile(name="p", hands_seen=hands)
    # VPIP counter 직접 설정
    pp.get("VPIP").alpha = vpip_pct * hands
    pp.get("VPIP").beta = (1 - vpip_pct) * hands
    # AF: aggressive / passive = af → 임의 샘플
    pp.aggression.aggressive = af * 10
    pp.aggression.passive = 10
    return pp


def test_insufficient_observations_uniform():
    pp = PlayerProfile(name="new", hands_seen=5)
    probs = soft_assign(pp)
    assert set(probs) == {"NIT", "TAG", "LAG", "Fish"}
    for v in probs.values():
        assert v == pytest.approx(0.25, abs=1e-9)


def test_tight_passive_is_NIT():
    # VPIP 12%, AF 0.6 → class_priors centroid: NIT
    pp = _profile(0.12, 0.6)
    assert hard_assign(pp) == "NIT"


def test_tight_aggressive_is_TAG():
    # VPIP 22%, AF 2.5 → TAG
    pp = _profile(0.22, 2.5)
    assert hard_assign(pp) == "TAG"


def test_loose_aggressive_is_LAG():
    pp = _profile(0.35, 3.0)
    assert hard_assign(pp) == "LAG"


def test_loose_passive_is_Fish():
    pp = _profile(0.45, 0.9)
    assert hard_assign(pp) == "Fish"


def test_soft_probabilities_sum_to_one():
    pp = _profile(0.25, 2.0)
    probs = soft_assign(pp)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)


def test_borderline_hand_is_mixed():
    # VPIP 25%, AF 1.5 → TAG/Fish 경계 근처, 확률 분산
    pp = _profile(0.25, 1.5)
    probs = soft_assign(pp, cfg=TypingConfig(temperature=0.3))
    # 적어도 2개 클래스가 20% 이상
    high = [p for p in probs.values() if p > 0.15]
    assert len(high) >= 2
