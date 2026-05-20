"""Nash push/fold 차트 regression 테스트.

scripts/validate_nash_charts.py 의 단조성·앵커·loadability 검증을 테스트로 고정.
R5 의 공식 ICMIZER 값으로 교체 시에도 이 테스트는 통과해야 한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from holdem.decide.push_fold_chart import PushFoldChart

ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = ROOT / "configs/nash_charts/simple_push_9max.yaml"
VALIDATOR = ROOT / "scripts/validate_nash_charts.py"


def test_default_chart_loads():
    chart = PushFoldChart.from_yaml(CHART_PATH)
    assert chart.jam, "jam buckets 비어 있음"
    assert chart.call_vs_jam, "call_vs_jam buckets 비어 있음"


def test_chart_jam_monotonicity():
    """더 낮은 M 의 jam range 는 더 높은 M 의 range 의 상위집합이어야."""
    chart = PushFoldChart.from_yaml(CHART_PATH)
    sorted_b = sorted(chart.jam, key=lambda b: b.max_M)
    for i in range(len(sorted_b) - 1):
        low_hands: set = set()
        for hands in sorted_b[i].ranges.values():
            low_hands |= set(hands)
        high_hands: set = set()
        for hands in sorted_b[i + 1].ranges.values():
            high_hands |= set(hands)
        missing = high_hands - low_hands
        assert not missing, (
            f"M≤{sorted_b[i].max_M} 에 없는데 M≤{sorted_b[i+1].max_M} 에 있는 핸드: {sorted(missing)[:5]}"
        )


def test_chart_call_vs_jam_has_premium():
    chart = PushFoldChart.from_yaml(CHART_PATH)
    for b in chart.call_vs_jam:
        all_hands: set = set()
        for hands in b.ranges.values():
            all_hands |= set(hands)
        for anchor in ("QQ", "KK", "AA", "AKs"):
            assert anchor in all_hands, f"{anchor} 가 call_vs_jam M≤{b.max_M} 에 없음"


def test_chart_jam_has_aces():
    chart = PushFoldChart.from_yaml(CHART_PATH)
    for b in chart.jam:
        all_hands: set = set()
        for hands in b.ranges.values():
            all_hands |= set(hands)
        assert "AA" in all_hands, f"AA 가 jam M≤{b.max_M} 에 없음"


def test_chart_deep_stack_no_trash():
    """M>8 jam 에는 72o 같은 쓰레기 핸드 없어야."""
    chart = PushFoldChart.from_yaml(CHART_PATH)
    for b in chart.jam:
        if b.max_M > 8.0:
            for pos, hands in b.ranges.items():
                assert "72o" not in hands, f"72o 가 deep jam M≤{b.max_M}({pos}) 에 포함"


def test_validator_script_passes():
    """검증 스크립트도 CLI 실행 시 통과."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--quiet"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"validate_nash_charts.py failed:\n{result.stdout}\n{result.stderr}"
    )
