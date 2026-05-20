"""mode_selector 경계 검증."""
from __future__ import annotations

from holdem.decide.mode_selector import ModeThresholds, select_mode


def _defaults_or(override: ModeThresholds | None = None) -> ModeThresholds:
    return override or ModeThresholds(push_fold_max=8.0, hybrid_max=15.0, mid_max=30.0)


def test_deep_above_30():
    t = _defaults_or()
    assert select_mode(100.0, t) == "deep"
    assert select_mode(30.1, t) == "deep"


def test_mid_range():
    t = _defaults_or()
    assert select_mode(30.0, t) == "mid"
    assert select_mode(20.0, t) == "mid"
    assert select_mode(15.1, t) == "mid"


def test_hybrid_range():
    t = _defaults_or()
    assert select_mode(15.0, t) == "hybrid"
    assert select_mode(10.0, t) == "hybrid"
    assert select_mode(8.1, t) == "hybrid"


def test_push_fold_range():
    t = _defaults_or()
    assert select_mode(8.0, t) == "push_fold"
    assert select_mode(1.0, t) == "push_fold"
    assert select_mode(0.0, t) == "push_fold"


def test_loads_from_yaml():
    # config 파일이 실제로 로드되는지 (D1 런타임 경로).
    assert select_mode(100.0) == "deep"
    assert select_mode(5.0) == "push_fold"
