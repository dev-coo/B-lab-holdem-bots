"""Bootstrap self-play — N 핸드 HU 자기대전 후 strategy 별 통계 집계.

사용:
    uv run python scripts/bootstrap_sim.py --hands 5000 --seed 42
    uv run python scripts/bootstrap_sim.py --hands 1000 --output data/bootstrap.jsonl

산출:
    - strategy 별 VPIP/PFR/aggression/showdown 빈도.
    - 매치업 별 win rate (각 전략 쌍 대전 결과).
    - optional: 핸드별 history JSONL 저장.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from holdem.simulate.engine import run_hand   # noqa: E402
from holdem.simulate.strategies import all_strategies   # noqa: E402


def _safe_af(aggressive: float, passive: float, max_af: float = 10.0) -> float:
    """Laplace-smoothed AF — passive 희소 시 폭주 방지. AggressionCounter.factor 와 동일 공식."""
    if aggressive + passive <= 0:
        return 1.0
    if passive < 1.0:
        af = (aggressive + 1.0) / (passive + 1.0)
    else:
        af = aggressive / passive
    return min(af, max_af)


def aggregate_metrics(history: list[dict], strategy_name_by_idx: list[str]) -> dict[str, dict]:
    """매치에서 각 플레이어의 metric 증분."""
    stats = {n: defaultdict(float) for n in set(strategy_name_by_idx)}
    for entry in history:
        name = strategy_name_by_idx[entry["player"]]
        stats[name]["n_actions"] += 1
        if entry["phase"] == "preflop":
            if entry["action"] in ("call", "raise", "allin"):
                stats[name]["vpip_hit"] += 1
            if entry["action"] == "raise":
                stats[name]["pfr_hit"] += 1
            # 준비: denom 은 "첫 액션 기회" — 여기선 근사적으로 preflop 한번 등장한 것.
            # 간단화: 플레이어별 첫 preflop action 만 집계.
        if entry["action"] in ("raise", "allin"):
            stats[name]["aggr"] += 1
        elif entry["action"] == "call":
            stats[name]["passive"] += 1
    return stats


def run_pair(name_a: str, name_b: str, n_hands: int, seed: int) -> dict:
    strategies = {s.name: s for s in all_strategies()}
    a = strategies[name_a]
    b = strategies[name_b]
    rng = random.Random(seed)
    stacks = [300, 300]
    totals = defaultdict(lambda: defaultdict(float))
    wins = {name_a: 0, name_b: 0, "split": 0}
    showdowns = 0
    preflop_opps = {name_a: 0, name_b: 0}
    preflop_vpip = {name_a: 0, name_b: 0}
    preflop_pfr = {name_a: 0, name_b: 0}

    for i in range(n_hands):
        # HU: SB 과 BB 교대 — 매 핸드 strategy 자리 스왑
        if i % 2 == 0:
            sb, bb = a, b
            idx_names = [a.name, b.name]
            stacks_in = stacks
        else:
            sb, bb = b, a
            idx_names = [b.name, a.name]
            stacks_in = [stacks[1], stacks[0]]

        # 스택 리셋 (토너먼트 아닌 cash 방식) — 학습 데이터 생성이 목적
        stacks_in = [300, 300]

        res = run_hand(sb, bb, sb_stack=stacks_in[0], bb_stack=stacks_in[1], rng=rng)
        if res.showdown_reached:
            showdowns += 1
        if res.winner_idx == -1:
            wins["split"] += 1
        else:
            wins[idx_names[res.winner_idx]] += 1

        # preflop opportunity 각 1회씩 (각 핸드당 각 플레이어 한번 preflop 결정)
        preflop_opps[idx_names[0]] += 1
        preflop_opps[idx_names[1]] += 1

        # first preflop action 추출
        seen = {0: False, 1: False}
        for entry in res.history:
            if entry["phase"] != "preflop":
                continue
            p_idx = entry["player"]
            if seen[p_idx]:
                continue
            seen[p_idx] = True
            nm = idx_names[p_idx]
            if entry["action"] in ("call", "raise", "allin"):
                preflop_vpip[nm] += 1
            if entry["action"] == "raise":
                preflop_pfr[nm] += 1

        ms = aggregate_metrics(res.history, idx_names)
        for nm, m in ms.items():
            for k, v in m.items():
                totals[nm][k] += v

    out = {}
    for nm in (name_a, name_b):
        n = max(1, preflop_opps[nm])
        aggr = totals[nm]["aggr"]
        pas = totals[nm]["passive"]
        out[nm] = {
            "preflop_opps": preflop_opps[nm],
            "vpip_rate": preflop_vpip[nm] / n,
            "pfr_rate": preflop_pfr[nm] / n,
            "aggression_factor": _safe_af(aggr, pas),
            "n_aggressive_actions": int(aggr),
            "n_passive_actions": int(pas),
        }
    out["_match"] = {
        "n_hands": n_hands,
        "showdown_rate": showdowns / n_hands,
        "wins": wins,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=2000, help="전략쌍당 핸드 수")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pairs", choices=["round_robin", "all"], default="round_robin")
    ap.add_argument("--output", type=Path, default=None, help="결과 JSON 저장 경로")
    args = ap.parse_args()

    names = [s.name for s in all_strategies()]
    start = time.perf_counter()
    results: dict = {"pairs": {}}

    combos = list(itertools.combinations(names, 2))
    print(f"# strategies={names}")
    print(f"# pairs={len(combos)} hands_per_pair={args.hands}")

    for (a, b) in combos:
        sub = run_pair(a, b, args.hands, args.seed)
        key = f"{a} vs {b}"
        results["pairs"][key] = sub
        m = sub["_match"]
        print(f"\n== {key}  n={m['n_hands']}  showdown={m['showdown_rate']:.2f}  wins={m['wins']}")
        for nm in (a, b):
            row = sub[nm]
            print(f"  {nm:12s}  VPIP={row['vpip_rate']*100:5.1f}%  PFR={row['pfr_rate']*100:5.1f}%  AF={row['aggression_factor']:.2f}")

    # 전략별 통합 집계 (모든 match 기여 합)
    combined: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for key, sub in results["pairs"].items():
        for nm, row in sub.items():
            if nm == "_match":
                continue
            for mk, mv in row.items():
                combined[nm][mk] += mv if isinstance(mv, (int, float)) else 0
    print("\n=== 전략별 평균 (모든 매치업 종합) ===")
    for nm in names:
        row = combined[nm]
        opps = row.get("preflop_opps", 1) or 1
        vpip_hits = int(row.get("vpip_rate", 0) * opps / len(combos) * len(combos))
        # 가중 평균 — 각 match 의 rate 평균
        n_match = sum(1 for k in results["pairs"] if nm in k)
        avg_vpip = sum(results["pairs"][k][nm]["vpip_rate"]
                       for k in results["pairs"] if nm in k) / max(1, n_match)
        avg_pfr = sum(results["pairs"][k][nm]["pfr_rate"]
                      for k in results["pairs"] if nm in k) / max(1, n_match)
        avg_af = sum(results["pairs"][k][nm]["aggression_factor"]
                     for k in results["pairs"] if nm in k) / max(1, n_match)
        print(f"  {nm:12s}  VPIP={avg_vpip*100:5.1f}%  PFR={avg_pfr*100:5.1f}%  AF={avg_af:.2f}")

    elapsed = time.perf_counter() - start
    print(f"\n# elapsed {elapsed:.1f}s")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as f:
            json.dump(results, f, indent=2)
        print(f"# saved → {args.output}")


if __name__ == "__main__":
    main()
