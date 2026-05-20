"""Nash push/fold 차트 sanity 검증 — R5 정식 교체 전 regression 방어.

검증 항목:
  1. 모든 M bucket 이 load 가능 + ranges 파싱 성공.
  2. JAM 단조성: M 이 작을수록 jam range 가 넓다 (≥).
  3. CALL_VS_JAM 반단조: M 이 클수록 call range 가 좁다 (≤).
  4. 핵심 앵커:
     - AA 는 모든 jam bucket 에 포함.
     - 72o 는 M>8 jam 에 없음.
     - QQ+ / AK 는 모든 call_vs_jam bucket 에 포함.
     - 44-22 는 M>20 call bucket 에 없음.
  5. Coverage 리포트 — bucket 별 jam hand 개수 / 169.

실행:
    uv run python scripts/validate_nash_charts.py
    uv run python scripts/validate_nash_charts.py --chart configs/nash_charts/simple_push_9max.yaml

exit 0: 통과, 1: 실패.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from holdem.decide.push_fold_chart import Bucket, PushFoldChart

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHART = ROOT / "configs/nash_charts/simple_push_9max.yaml"

POS = ("EP", "MP", "LP", "BLIND")


def _all_hands_in_bucket(bucket: Bucket) -> set[str]:
    out: set[str] = set()
    for k, hands in bucket.ranges.items():
        out |= set(hands)
    return out


def _check_jam_monotonicity(buckets: list[Bucket]) -> list[str]:
    """낮은 M → 넓은 range (superset)."""
    errs: list[str] = []
    sorted_b = sorted(buckets, key=lambda b: b.max_M)
    # 각 연속 쌍에 대해: 낮은 M 의 hands ⊇ 높은 M 의 hands
    for i in range(len(sorted_b) - 1):
        low = _all_hands_in_bucket(sorted_b[i])
        high = _all_hands_in_bucket(sorted_b[i + 1])
        missing = high - low
        if missing:
            errs.append(
                f"JAM 단조성 위반: M≤{sorted_b[i].max_M} 에 없는데 M≤{sorted_b[i+1].max_M} 에 있는 핸드: "
                f"{sorted(missing)[:5]}{'…' if len(missing) > 5 else ''}"
            )
    return errs


def _check_call_monotonicity(buckets: list[Bucket]) -> list[str]:
    """낮은 M → 넓은 call range (상대가 jam 빈도 높으므로)."""
    errs: list[str] = []
    sorted_b = sorted(buckets, key=lambda b: b.max_M)
    for i in range(len(sorted_b) - 1):
        low = _all_hands_in_bucket(sorted_b[i])
        high = _all_hands_in_bucket(sorted_b[i + 1])
        missing = high - low
        if missing:
            errs.append(
                f"CALL 단조성 위반: M≤{sorted_b[i].max_M} 에 없는데 M≤{sorted_b[i+1].max_M} 에 있는 핸드: "
                f"{sorted(missing)[:5]}{'…' if len(missing) > 5 else ''}"
            )
    return errs


def _check_anchors(chart: PushFoldChart) -> list[str]:
    errs: list[str] = []

    # AA는 전 jam bucket 에 있어야.
    for b in chart.jam:
        ok = any("AA" in hands for hands in b.ranges.values())
        if not ok:
            errs.append(f"AA 가 jam M≤{b.max_M} bucket 에 없음")

    # 72o 는 M>8 에는 없어야 (매우 약한 핸드 → 깊은 스택 jam 안 함)
    for b in chart.jam:
        if b.max_M > 8.0:
            for pos, hands in b.ranges.items():
                if "72o" in hands:
                    errs.append(f"72o 가 jam M≤{b.max_M}({pos}) bucket 에 포함 — 너무 넓음")

    # QQ+ 와 AKs 는 모든 call_vs_jam 에 있어야 (premium only).
    # AKo 는 깊은 M 에서 coin flip 회피로 제외 가능 — Nash 관점.
    for b in chart.call_vs_jam:
        for anchor in ("QQ", "KK", "AA", "AKs"):
            ok = any(anchor in hands for hands in b.ranges.values())
            if not ok:
                errs.append(f"{anchor} 가 call_vs_jam M≤{b.max_M} 에 없음")
    # AKo 는 최소 M≤10 까지는 있어야.
    for b in chart.call_vs_jam:
        if b.max_M <= 10.0:
            ok = any("AKo" in hands for hands in b.ranges.values())
            if not ok:
                errs.append(f"AKo 가 call_vs_jam M≤{b.max_M} 에 없음 (얕은 구간 필수)")

    # M>20 에서 22-44 는 call 하지 않는다 (넓은 범위 상대에 코인플립 회피)
    for b in chart.call_vs_jam:
        if b.max_M > 20.0 or b.max_M == float("inf"):
            for pair in ("22", "33", "44"):
                for pos, hands in b.ranges.items():
                    if pair in hands:
                        errs.append(f"{pair} 가 call_vs_jam M≤{b.max_M}({pos}) 에 포함 — 너무 넓음")

    return errs


def _coverage(chart: PushFoldChart) -> None:
    print("\n=== 커버리지 (169 핸드 중) ===")
    print(f"{'kind':14s} {'max_M':>8s}  EP   MP   LP   BLIND  any")
    for kind, buckets in (("jam", chart.jam), ("hybrid_open", chart.hybrid_open),
                          ("call_vs_jam", chart.call_vs_jam)):
        for b in buckets:
            sizes = {p: len(b.ranges.get(p, set())) for p in POS}
            any_n = len(b.ranges.get("any", set()))
            m_str = "inf" if b.max_M == float("inf") else f"{b.max_M:.1f}"
            print(f"{kind:14s} {m_str:>8s}  "
                  f"{sizes['EP']:<4d} {sizes['MP']:<4d} {sizes['LP']:<4d} {sizes['BLIND']:<6d} {any_n}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", type=Path, default=DEFAULT_CHART)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        chart = PushFoldChart.from_yaml(args.chart)
    except Exception as e:
        print(f"LOAD FAILED: {e}")
        return 1

    errs: list[str] = []
    errs += _check_jam_monotonicity(chart.jam)
    errs += _check_call_monotonicity(chart.call_vs_jam)
    errs += _check_anchors(chart)

    if not args.quiet:
        _coverage(chart)

    print("\n=== 검증 ===")
    if errs:
        print(f"FAIL — {len(errs)} 위반:")
        for e in errs:
            print(f"  · {e}")
        return 1
    print("PASS — 단조성·앵커·loadability 통과")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
