"""analyze_session.report_games — 테이블 사이즈별 분해 출력 검증."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "analyze_session_mod",
        Path(__file__).parent.parent / "scripts" / "analyze_session.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["analyze_session_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _g(rank: int, total: int, room: str = "1", chips: int = 0) -> dict:
    return {"rank": rank, "total": total, "room": room, "chips": chips}


def test_breakdown_emits_per_size_when_mixed():
    mod = _load()
    games = (
        [_g(rank=(i % 5) + 1, total=5) for i in range(50)]
        + [_g(rank=(i % 6) + 1, total=6) for i in range(40)]
    )
    out = mod.report_games(games, norank=0)
    assert "테이블 사이즈별 분해" in out
    assert "**5p** (50)" in out
    assert "**6p** (40)" in out


def test_breakdown_skipped_for_single_size():
    """한 사이즈만 있으면 분해 섹션 생략 (전체 요약과 중복)."""
    mod = _load()
    games = [_g(rank=(i % 6) + 1, total=6) for i in range(100)]
    out = mod.report_games(games, norank=0)
    assert "테이블 사이즈별 분해" not in out
    assert "토너먼트 수: 100" in out


def test_breakdown_min_threshold():
    """n < 10 인 사이즈는 분해에서 제외."""
    mod = _load()
    games = (
        [_g(rank=(i % 6) + 1, total=6) for i in range(100)]
        + [_g(rank=1, total=4) for _ in range(5)]   # 4p × 5 (< 10)
    )
    out = mod.report_games(games, norank=0)
    # 6p 분해 등장, 4p 분해 미등장.
    assert "**6p** (100)" in out
    assert "**4p**" not in out


def test_summary_metrics_match_overall():
    mod = _load()
    games = [_g(rank=1, total=5)] * 3 + [_g(rank=4, total=5)] * 2
    out = mod.report_games(games, norank=0)
    assert "1등률: 3/5 = 60.0%" in out
    assert "ITM (top-3): 3/5 = 60.0%" in out
    assert "평균 순위: 2.20" in out
