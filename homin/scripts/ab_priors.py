"""R6 A/B — 두 priors 세트의 보정 오차(calibration error) 비교.

질문:
    현재 configs/class_priors.yaml (variant A) 와 configs/class_priors.bootstrap_backup.yaml
    (variant B) 중 어느 쪽이 bootstrap self-play 관측과 더 가까운 posterior 를 낸다.

측정:
    1. bootstrap_results.json 에서 각 strategy → (VPIP, PFR) 관측 rate 추출.
    2. 각 priors 세트를 로드.
    3. 해당 strategy 의 class (nitrock→NIT / tag→TAG / lag→LAG / callstation→Fish) 별
       class prior + population prior 로 shrinkage.
    4. n_personal = {0, 10, 30, 80} 각 단계에서 shrinkage-adjusted rate 계산.
    5. observed rate 와 absolute error 의 평균 → MAE.
    6. Welch t-test 로 유의성.

Usage:
    uv run python scripts/ab_priors.py
    uv run python scripts/ab_priors.py --a configs/class_priors.yaml --b configs/class_priors.bootstrap_backup.yaml

Out: 표 + Verdict.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml   # noqa: E402

from holdem.estimate.priors import ShrinkageHyperparams   # noqa: E402
from holdem.estimate.shrinkage import shrink   # noqa: E402
from holdem.state.player_profile import BetaCounter   # noqa: E402

STRATEGY_CLASS = {
    "nitrock": "NIT",
    "tag": "TAG",
    "lag": "LAG",
    "callstation": "Fish",
}

PROBE_N = (0, 10, 30, 80)
METRICS = ("VPIP", "PFR")


@dataclass
class CalibrationPoint:
    variant: str
    strategy: str
    metric: str
    n: int
    observed: float
    predicted: float
    abs_error: float


def _load_class_priors(path: Path) -> dict[str, dict[str, BetaCounter]]:
    with path.open() as f:
        data = yaml.safe_load(f)
    out: dict[str, dict[str, BetaCounter]] = {}
    for cls, block in data["server_class_priors"].items():
        out[cls] = {}
        for key, vals in block.items():
            if isinstance(vals, dict) and "alpha" in vals:
                out[cls][key] = BetaCounter(
                    alpha=float(vals["alpha"]), beta=float(vals["beta"]),
                )
    return out


def _load_population_priors(path: Path) -> dict[str, BetaCounter]:
    """priors.yaml → server_prior_9max blob 반환 (기본)."""
    with path.open() as f:
        data = yaml.safe_load(f)
    block = data.get("server_prior_9max") or data.get("server_prior_6max")
    out: dict[str, BetaCounter] = {}
    if not block:
        return out
    for key, vals in block.items():
        if isinstance(vals, dict) and "alpha" in vals:
            out[key] = BetaCounter(alpha=float(vals["alpha"]), beta=float(vals["beta"]))
    return out


def _extract_observed(bootstrap: dict) -> dict[str, dict[str, float]]:
    """전략별 VPIP/PFR 평균 rate. bootstrap pairs 를 가로질러 집계."""
    acc: dict[str, dict[str, float]] = {}
    for pair_key, pair in bootstrap.get("pairs", {}).items():
        for strat, row in pair.items():
            if strat == "_match":
                continue
            a = acc.setdefault(strat, {"opps": 0.0, "vpip_hits": 0.0, "pfr_hits": 0.0})
            opps = float(row.get("preflop_opps", 0))
            a["opps"] += opps
            a["vpip_hits"] += float(row.get("vpip_rate", 0)) * opps
            a["pfr_hits"] += float(row.get("pfr_rate", 0)) * opps
    out: dict[str, dict[str, float]] = {}
    for strat, a in acc.items():
        opps = max(1.0, a["opps"])
        out[strat] = {
            "VPIP": a["vpip_hits"] / opps,
            "PFR": a["pfr_hits"] / opps,
        }
    return out


def _synth_personal(observed_rate: float, n: int) -> BetaCounter:
    """n 관측의 personal posterior 를 rate 로 합성."""
    if n <= 0:
        return BetaCounter(alpha=0.0, beta=0.0)
    alpha = observed_rate * n
    beta = (1.0 - observed_rate) * n
    return BetaCounter(alpha=alpha, beta=beta)


def evaluate(
    class_priors_path: Path,
    population_priors_path: Path,
    bootstrap_path: Path,
    variant_name: str,
    hp: ShrinkageHyperparams,
) -> list[CalibrationPoint]:
    class_priors = _load_class_priors(class_priors_path)
    pop_priors = _load_population_priors(population_priors_path)
    with bootstrap_path.open() as f:
        bootstrap = json.load(f)
    observed_all = _extract_observed(bootstrap)

    points: list[CalibrationPoint] = []
    for strat, cls in STRATEGY_CLASS.items():
        if strat not in observed_all:
            continue
        if cls not in class_priors:
            continue
        obs_rates = observed_all[strat]
        for metric in METRICS:
            if metric not in class_priors[cls]:
                continue
            # population prior: VPIP/PFR 이 없을 수 있음 → default uniform.
            pop = pop_priors.get(metric, BetaCounter(alpha=20.0, beta=80.0))
            cls_prior = class_priors[cls][metric]
            observed = obs_rates[metric]
            for n in PROBE_N:
                personal = _synth_personal(observed, n)
                posterior = shrink(personal, cls_prior, pop, hp)
                predicted = posterior.rate(default=0.5)
                points.append(CalibrationPoint(
                    variant=variant_name,
                    strategy=strat,
                    metric=metric,
                    n=n,
                    observed=observed,
                    predicted=predicted,
                    abs_error=abs(predicted - observed),
                ))
    return points


def _welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch t-test → (t, approx p). 표본 작을 수 있어 p 는 근사."""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    na, nb = len(a), len(b)
    denom = math.sqrt(va / na + vb / nb)
    if denom == 0:
        return 0.0, 1.0
    t = (ma - mb) / denom
    # Welch-Satterthwaite df
    num = (va / na + vb / nb) ** 2
    d1 = (va / na) ** 2 / max(1, na - 1)
    d2 = (vb / nb) ** 2 / max(1, nb - 1)
    df = num / max(1e-9, d1 + d2)
    # 근사 p: |t| > 2 → p < 0.05, |t| > 3 → p < 0.01. (정규 근사)
    # 정확 계산은 scipy.stats 필요 — 외부 의존 최소화 목적으로 근사.
    z = abs(t)
    p_approx = 2 * (1 - _normal_cdf(z))
    return t, p_approx


def _normal_cdf(x: float) -> float:
    # erf 기반 표준 정규 CDF.
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, default=ROOT / "configs/class_priors.yaml",
                    help="variant A (현재 priors)")
    ap.add_argument("--b", type=Path, default=ROOT / "configs/class_priors.bootstrap_backup.yaml",
                    help="variant B (비교 대상 — 기본: 부트스트랩 이전 백업)")
    ap.add_argument("--population", type=Path, default=ROOT / "configs/priors.yaml")
    ap.add_argument("--bootstrap", type=Path, default=ROOT / "data/bootstrap_results.json")
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    for p in (args.a, args.b, args.population, args.bootstrap):
        if not p.exists():
            print(f"ERROR: missing {p}")
            return 1

    hp = ShrinkageHyperparams()
    pts_a = evaluate(args.a, args.population, args.bootstrap, "A", hp)
    pts_b = evaluate(args.b, args.population, args.bootstrap, "B", hp)

    print(f"=== A = {args.a.name}")
    print(f"=== B = {args.b.name}")
    print(f"=== bootstrap truth = {args.bootstrap.name}")
    print(f"probing n ∈ {PROBE_N}, metrics = {METRICS}, classes = {list(STRATEGY_CLASS.values())}\n")

    print(f"{'variant':<7s} {'strat':<12s} {'metric':<5s} {'n':>3s}  "
          f"{'observed':>9s}  {'predicted':>10s}  {'|err|':>7s}")
    for pt in (pts_a + pts_b):
        print(f"{pt.variant:<7s} {pt.strategy:<12s} {pt.metric:<5s} {pt.n:>3d}  "
              f"{pt.observed:>9.3f}  {pt.predicted:>10.3f}  {pt.abs_error:>7.3f}")

    err_a = [p.abs_error for p in pts_a]
    err_b = [p.abs_error for p in pts_b]
    mae_a = statistics.mean(err_a) if err_a else float("nan")
    mae_b = statistics.mean(err_b) if err_b else float("nan")
    t, p_val = _welch_t(err_a, err_b)

    print(f"\n=== 종합 ===")
    print(f"  MAE_A = {mae_a:.4f}  (n={len(err_a)})")
    print(f"  MAE_B = {mae_b:.4f}  (n={len(err_b)})")
    print(f"  Δ = {mae_a - mae_b:+.4f}  (음수 → A 우수)")
    print(f"  Welch t = {t:.3f}  p ≈ {p_val:.3f}")
    if p_val < 0.05:
        winner = "A" if mae_a < mae_b else "B"
        print(f"  Verdict: {winner} 유의 우수 (p<0.05)")
    else:
        print(f"  Verdict: 유의 차이 없음 (p≥0.05)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as f:
            json.dump({
                "config": {"a": str(args.a), "b": str(args.b)},
                "points_a": [vars(p) for p in pts_a],
                "points_b": [vars(p) for p in pts_b],
                "summary": {
                    "mae_a": mae_a, "mae_b": mae_b,
                    "welch_t": t, "p_approx": p_val,
                },
            }, f, indent=2)
        print(f"\n# saved → {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
