"""A/B priors validation harness unit tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ab_priors.py"


sys.path.insert(0, str(ROOT / "scripts"))

# --- direct function tests ---

from ab_priors import (  # noqa: E402
    _extract_observed,
    _synth_personal,
    _welch_t,
    evaluate,
)
from holdem.estimate.priors import ShrinkageHyperparams  # noqa: E402


def test_extract_observed_averages_across_pairs():
    boot = {
        "pairs": {
            "a vs b": {
                "alice": {"preflop_opps": 100, "vpip_rate": 0.3, "pfr_rate": 0.2},
                "bob":   {"preflop_opps": 100, "vpip_rate": 0.5, "pfr_rate": 0.4},
                "_match": {},
            },
            "a vs c": {
                "alice": {"preflop_opps": 100, "vpip_rate": 0.5, "pfr_rate": 0.4},
                "carol": {"preflop_opps": 100, "vpip_rate": 0.7, "pfr_rate": 0.5},
                "_match": {},
            },
        },
    }
    out = _extract_observed(boot)
    # alice 평균 = (0.3·100 + 0.5·100) / 200 = 0.4
    assert out["alice"]["VPIP"] == pytest.approx(0.4)
    assert out["alice"]["PFR"] == pytest.approx(0.3)
    assert out["bob"]["VPIP"] == pytest.approx(0.5)
    assert out["carol"]["VPIP"] == pytest.approx(0.7)


def test_synth_personal_zero_obs():
    bc = _synth_personal(0.5, 0)
    assert bc.alpha == 0 and bc.beta == 0


def test_synth_personal_rate_preserved():
    bc = _synth_personal(0.3, 100)
    assert bc.rate() == pytest.approx(0.3)


def test_welch_t_identical_samples():
    t, p = _welch_t([1.0, 1.1, 0.9], [1.0, 1.1, 0.9])
    assert abs(t) < 1e-6
    assert p == pytest.approx(1.0, abs=1e-6)


def test_welch_t_detects_shift():
    a = [0.10, 0.11, 0.09, 0.10, 0.12]
    b = [0.50, 0.52, 0.48, 0.51, 0.49]
    t, p = _welch_t(a, b)
    # 평균 차이 ≈ 0.4, 작은 분산 → |t| 매우 크고 p 극소.
    assert abs(t) > 10
    assert p < 0.001


# --- CLI smoke ---

def test_ab_priors_cli_runs():
    """전체 파이프라인이 에러 없이 완료."""
    boot = ROOT / "data/bootstrap_results.json"
    priors = ROOT / "configs/priors.yaml"
    a = ROOT / "configs/class_priors.yaml"
    b = ROOT / "configs/class_priors.bootstrap_backup.yaml"
    if not all(p.exists() for p in (boot, priors, a, b)):
        pytest.skip("fixtures missing")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--a", str(a), "--b", str(b),
         "--bootstrap", str(boot), "--population", str(priors)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stdout}\n{result.stderr}"
    assert "MAE_A" in result.stdout
    assert "MAE_B" in result.stdout
    assert "Verdict" in result.stdout


def test_ab_priors_produces_points():
    hp = ShrinkageHyperparams()
    boot = ROOT / "data/bootstrap_results.json"
    priors_pop = ROOT / "configs/priors.yaml"
    priors_cls = ROOT / "configs/class_priors.yaml"
    if not all(p.exists() for p in (boot, priors_pop, priors_cls)):
        pytest.skip("fixtures missing")
    pts = evaluate(priors_cls, priors_pop, boot, "test", hp)
    # 4 strategies × 2 metrics × 4 n-probes = 32 (callstation 포함 관측 없으면 일부 skip)
    assert len(pts) >= 16
    # 모든 error 가 [0,1]
    assert all(0 <= p.abs_error <= 1 for p in pts)
