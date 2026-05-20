from __future__ import annotations

from holdem.estimate.range_inference import (
    filter_after_raise,
    infer_open_range,
)
from holdem.state.player_profile import PlayerProfile


def test_unknown_opener_gets_default_chart():
    r = infer_open_range("LP", profile=None)
    assert "AA" in r.hands
    assert "KK" in r.hands
    assert r.confidence == 0.0


def test_loose_opener_range_expands():
    # VPIP 40% → tag/loose 로 분류, range 확장
    loose = PlayerProfile(name="loose", hands_seen=100)
    loose.get("VPIP").alpha = 40
    loose.get("VPIP").beta = 60
    loose_r = infer_open_range("LP", profile=loose)
    tight = PlayerProfile(name="tight", hands_seen=100)
    tight.get("VPIP").alpha = 15
    tight.get("VPIP").beta = 85
    tight_r = infer_open_range("LP", profile=tight)
    assert len(loose_r.hands) >= len(tight_r.hands)


def test_confidence_grows_with_hands_seen():
    low = PlayerProfile(name="low", hands_seen=5)
    med = PlayerProfile(name="med", hands_seen=40)
    high = PlayerProfile(name="high", hands_seen=120)
    r_low = infer_open_range("LP", profile=low)
    r_med = infer_open_range("LP", profile=med)
    r_high = infer_open_range("LP", profile=high)
    assert r_low.confidence < r_med.confidence < r_high.confidence
    assert r_high.confidence == 1.0


def test_filter_after_raise_narrows_to_strong():
    base = infer_open_range("LP", profile=None)
    narrowed = filter_after_raise(base)
    # 72o 는 narrow 에 없어야
    assert "72o" not in narrowed.hands
    assert len(narrowed.hands) < len(base.hands)
    # premium 은 유지
    assert "AA" in narrowed.hands


def test_ep_range_tighter_than_lp():
    ep = infer_open_range("EP", profile=None)
    lp = infer_open_range("LP", profile=None)
    # 실제 chart 상 EP 가 더 좁음
    assert len(ep.hands) <= len(lp.hands)
