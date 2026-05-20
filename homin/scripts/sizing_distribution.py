"""J.5 — Sizing 분포 분석.

bluff_decisions.csv 에 이미 모든 bet/raise 의 (street, action, extra_bet, pot_before,
bet_to_pot, equity) 레코드가 있다. 재스캔 없이 통계만 산출.

산출:
- data/sizing_report.json : street × action × equity_bucket 별 사이즈 분포

BOT_GUIDE compliance:
- §6.2 raise amount = round total. 이 스크립트의 `extra_bet` 은 **이번 액션의 추가 베팅**
  (extra_bet = round_total - 기존 round_bet). pot 대비 비율은 pot_before 기준.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

DATA_CSV = Path(__file__).parent.parent / "data" / "bluff_decisions.csv"
OUT_JSON = Path(__file__).parent.parent / "data" / "sizing_report.json"


def load_records():
    with DATA_CSV.open() as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                bp = float(row["bet_to_pot"]) if row["bet_to_pot"] else None
            except ValueError:
                bp = None
            if bp is None or bp <= 0:
                continue
            try:
                eq = float(row["equity"]) if row["equity"] else None
            except ValueError:
                eq = None
            yield {
                "street": row["street"],
                "action": row["action"],
                "extra_bet": int(float(row["extra_bet"])) if row["extra_bet"] else 0,
                "pot_before": int(float(row["pot_before"])) if row["pot_before"] else 0,
                "bet_to_pot": bp,
                "equity": eq,
            }


def quantiles(xs: list[float], qs=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    n = len(xs)
    out = {"n": n, "mean": sum(xs) / n}
    for q in qs:
        idx = min(n - 1, int(q * n))
        out[f"p{int(q*100):02d}"] = xs[idx]
    return out


def histogram(xs: list[float], bins: list[float]) -> list[int]:
    """bin edges 기준 이산화."""
    counts = [0] * (len(bins) - 1)
    for x in xs:
        for i in range(len(bins) - 1):
            if bins[i] <= x < bins[i + 1]:
                counts[i] += 1
                break
        else:
            if x >= bins[-1]:
                counts[-1] += 1
    return counts


def mode_peaks(xs: list[float], bins: list[float]) -> list[dict]:
    """히스토그램 local maxima → 자연 모드."""
    h = histogram(xs, bins)
    peaks = []
    for i in range(1, len(h) - 1):
        if h[i] > h[i - 1] and h[i] > h[i + 1] and h[i] > sum(h) * 0.05:
            peaks.append({"bin_range": [bins[i], bins[i + 1]], "count": h[i],
                          "fraction": h[i] / sum(h)})
    return peaks


def analyze():
    recs = list(load_records())
    print(f"Loaded {len(recs)} records")

    # 1. 전체 사이즈 분포
    all_bp = [r["bet_to_pot"] for r in recs]
    bins = [0, 0.15, 0.25, 0.33, 0.40, 0.50, 0.60, 0.66, 0.75, 0.85, 1.00, 1.25, 1.50, 2.00, 3.00, 10.0]

    report = {
        "total_records": len(recs),
        "overall": {
            "quantiles": quantiles(all_bp),
            "histogram_bins": bins,
            "histogram_counts": histogram(all_bp, bins),
            "peaks": mode_peaks(all_bp, bins),
        },
    }

    # 2. street × action 별
    street_action = defaultdict(list)
    for r in recs:
        street_action[(r["street"], r["action"])].append(r["bet_to_pot"])

    report["by_street_action"] = {}
    for (s, a), xs in street_action.items():
        key = f"{s}_{a}"
        report["by_street_action"][key] = {
            "quantiles": quantiles(xs),
            "histogram_counts": histogram(xs, bins),
            "peaks": mode_peaks(xs, bins),
        }

    # 3. equity bucket 별 (value 성격 vs bluff 성격 사이즈)
    eq_buckets: dict[str, list[float]] = {
        "pure_bluff_eq_lt_0.20":  [],
        "weak_eq_0.20_0.40":      [],
        "marginal_eq_0.40_0.60":  [],
        "strong_eq_0.60_0.80":    [],
        "nuts_eq_gt_0.80":        [],
    }
    for r in recs:
        eq = r["equity"]
        if eq is None:
            continue
        bp = r["bet_to_pot"]
        if eq < 0.20:       eq_buckets["pure_bluff_eq_lt_0.20"].append(bp)
        elif eq < 0.40:     eq_buckets["weak_eq_0.20_0.40"].append(bp)
        elif eq < 0.60:     eq_buckets["marginal_eq_0.40_0.60"].append(bp)
        elif eq < 0.80:     eq_buckets["strong_eq_0.60_0.80"].append(bp)
        else:               eq_buckets["nuts_eq_gt_0.80"].append(bp)

    report["by_equity"] = {}
    for k, xs in eq_buckets.items():
        report["by_equity"][k] = {
            "quantiles": quantiles(xs),
            "histogram_counts": histogram(xs, bins),
        }

    # 4. street × equity (polarization 확인)
    report["by_street_equity"] = {}
    for s in ("flop", "turn", "river"):
        for label, eq_range in [("bluff", (0, 0.4)), ("value", (0.6, 1.01))]:
            xs = [r["bet_to_pot"] for r in recs
                  if r["street"] == s and r["equity"] is not None
                  and eq_range[0] <= r["equity"] < eq_range[1]]
            report["by_street_equity"][f"{s}_{label}"] = quantiles(xs)

    # 5. 시장에서 많이 쓰이는 peak size 상위 3
    all_hist = histogram(all_bp, bins)
    sorted_idx = sorted(range(len(all_hist)), key=lambda i: -all_hist[i])[:5]
    report["top_sizing_modes"] = [
        {"bin": [bins[i], bins[i + 1]], "count": all_hist[i],
         "fraction": all_hist[i] / sum(all_hist)}
        for i in sorted_idx
    ]

    return report


def main():
    rep = analyze()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    print(f"Wrote {OUT_JSON}")

    q = rep["overall"]["quantiles"]
    print(f"\n[Overall] n={q['n']} mean={q['mean']:.3f}")
    print(f"  p25={q['p25']:.3f} p50={q['p50']:.3f} p75={q['p75']:.3f} p90={q['p90']:.3f} p95={q['p95']:.3f}")
    print(f"\nTop sizing modes:")
    for m in rep["top_sizing_modes"]:
        print(f"  [{m['bin'][0]:.2f}-{m['bin'][1]:.2f}]  n={m['count']:8d}  {m['fraction']:.2%}")
    print(f"\nBy street x equity (bluff vs value median sizing):")
    for k, v in rep["by_street_equity"].items():
        if v:
            print(f"  {k:20s}  n={v['n']:8d}  p50={v['p50']:.3f}  p75={v['p75']:.3f}")


if __name__ == "__main__":
    main()
