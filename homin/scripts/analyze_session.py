"""세션 로그 → 토너먼트 결과 / 의사결정 trace 집계.

사용:
  uv run python scripts/analyze_session.py path/to/session.log
  uv run python scripts/analyze_session.py data/logs/cli/   # 디렉토리 → 모든 .log 합산

파싱 대상 (P-Obs1 로그 형식):
  game_end room=X my_rank=R/N my_chips=C
  room=X hand=H phase=P → ACT amount=A | stage=S m=M mode=MD n_active=N facing_raise=B

리포트:
  - 토너먼트 수, 1등률, ITM 비율 (top-3), 평균 순위
  - 스테이지 × 액션 분포 (raw count + pct)
  - 모드 × 액션 분포 (push_fold / hybrid / mid / deep)
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

GAME_END_RE = re.compile(
    r"game_end room=(?P<room>\S+) my_rank=(?P<rank>\d+)/(?P<total>\d+) my_chips=(?P<chips>\d+)"
)
GAME_END_NORANK_RE = re.compile(
    r"game_end room=(?P<room>\S+) ranks=(?P<total>\d+) \(bot not in rankings\)"
)
DECISION_RE = re.compile(
    r"phase=(?P<phase>\w+) → (?P<action>\w+) amount=(?P<amount>\S+)"
    r" \| stage=(?P<stage>\w+) m=(?P<m>[\d.]+) mode=(?P<mode>\w+)"
    r" n_active=(?P<n>\d+) facing_raise=(?P<fr>\w+)"
)


def iter_log_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(path.glob("*.log"))
    else:
        yield path


def analyze(paths: list[Path]) -> dict:
    games: list[dict] = []
    games_norank = 0
    decisions = []

    for log_path in paths:
        with log_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                m = GAME_END_RE.search(line)
                if m:
                    games.append({
                        "room": m["room"],
                        "rank": int(m["rank"]),
                        "total": int(m["total"]),
                        "chips": int(m["chips"]),
                    })
                    continue
                m2 = GAME_END_NORANK_RE.search(line)
                if m2:
                    games_norank += 1
                    continue
                m3 = DECISION_RE.search(line)
                if m3:
                    decisions.append({
                        "phase": m3["phase"],
                        "action": m3["action"],
                        "stage": m3["stage"],
                        "mode": m3["mode"],
                        "n_active": int(m3["n"]),
                        "facing_raise": m3["fr"] == "True",
                    })

    return {
        "games": games,
        "games_norank": games_norank,
        "decisions": decisions,
    }


_SIZE_BREAKDOWN_MIN = 10


def _summarize(games: list[dict]) -> dict:
    n = len(games)
    firsts = sum(1 for g in games if g["rank"] == 1)
    itm = sum(1 for g in games if g["rank"] <= 3)
    avg_rank = sum(g["rank"] for g in games) / n
    rank_hist = Counter(g["rank"] for g in games)
    return {
        "n": n,
        "firsts": firsts,
        "itm": itm,
        "avg_rank": avg_rank,
        "rank_hist": rank_hist,
    }


def report_games(games: list[dict], norank: int) -> str:
    if not games:
        return f"## 토너먼트 결과\n(game_end 라인 0 — P-Obs1 변경 후 운영 로그 필요)\n"

    overall = _summarize(games)
    table_size = Counter(g["total"] for g in games).most_common(3)

    lines = [
        "## 토너먼트 결과",
        f"- 토너먼트 수: {overall['n']}  (rankings 누락 게임: {norank})",
        f"- 1등률: {overall['firsts']}/{overall['n']} = {overall['firsts']/overall['n']:.1%}",
        f"- ITM (top-3): {overall['itm']}/{overall['n']} = {overall['itm']/overall['n']:.1%}",
        f"- 평균 순위: {overall['avg_rank']:.2f}",
        f"- 순위 분포: " + ", ".join(f"{r}={c}" for r, c in sorted(overall["rank_hist"].items())),
        f"- 테이블 사이즈 (상위 3): " + ", ".join(f"{t}p×{c}" for t, c in table_size),
    ]

    by_size: dict[int, list[dict]] = defaultdict(list)
    for g in games:
        by_size[g["total"]].append(g)

    breakdown_sizes = [s for s in sorted(by_size) if len(by_size[s]) >= _SIZE_BREAKDOWN_MIN]
    if len(breakdown_sizes) >= 2 or (
        len(breakdown_sizes) == 1 and len(by_size[breakdown_sizes[0]]) < overall["n"]
    ):
        lines.append("")
        lines.append(f"### 테이블 사이즈별 분해 (n ≥ {_SIZE_BREAKDOWN_MIN})")
        for size in breakdown_sizes:
            grp = by_size[size]
            s = _summarize(grp)
            ranks = ", ".join(f"{r}={c}" for r, c in sorted(s["rank_hist"].items()))
            lines.append(
                f"- **{size}p** ({s['n']}): 1등 {s['firsts']/s['n']:.1%}, "
                f"ITM {s['itm']/s['n']:.1%}, 평균 {s['avg_rank']:.2f}, [{ranks}]"
            )
    return "\n".join(lines) + "\n"


def report_decisions(decisions: list[dict]) -> str:
    if not decisions:
        return "## 의사결정 분포\n(decision trace 라인 0)\n"

    by_stage = defaultdict(Counter)
    by_mode = defaultdict(Counter)
    by_phase = defaultdict(Counter)
    for d in decisions:
        by_stage[d["stage"]][d["action"]] += 1
        by_mode[d["mode"]][d["action"]] += 1
        by_phase[d["phase"]][d["action"]] += 1

    out = [f"## 의사결정 분포 (총 {len(decisions)} 건)"]

    out.append("\n### Phase × Action")
    for phase in ("preflop", "flop", "turn", "river"):
        c = by_phase.get(phase)
        if not c:
            continue
        total = sum(c.values())
        parts = ", ".join(f"{a}={n} ({n/total:.0%})" for a, n in c.most_common())
        out.append(f"- **{phase}** ({total}): {parts}")

    out.append("\n### Stage × Action")
    for stage in ("early", "mid", "near_final", "final_table", "heads_up"):
        c = by_stage.get(stage)
        if not c:
            continue
        total = sum(c.values())
        parts = ", ".join(f"{a}={n} ({n/total:.0%})" for a, n in c.most_common())
        out.append(f"- **{stage}** ({total}): {parts}")

    out.append("\n### Mode × Action")
    for mode in ("push_fold", "hybrid", "mid", "deep"):
        c = by_mode.get(mode)
        if not c:
            continue
        total = sum(c.values())
        parts = ", ".join(f"{a}={n} ({n/total:.0%})" for a, n in c.most_common())
        out.append(f"- **{mode}** ({total}): {parts}")

    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Holdem session log analyzer (P-Obs1)")
    ap.add_argument("path", nargs="+", help="로그 파일 또는 디렉토리")
    args = ap.parse_args()

    paths: list[Path] = []
    for raw in args.path:
        p = Path(raw)
        if not p.exists():
            print(f"warning: {p} does not exist, skip")
            continue
        paths.extend(iter_log_files(p))

    if not paths:
        print("no log files found")
        return 1

    print(f"# 세션 분석 — {len(paths)} 파일\n")
    for p in paths:
        print(f"- {p}")
    print()

    result = analyze(paths)
    print(report_games(result["games"], result["games_norank"]))
    print(report_decisions(result["decisions"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
