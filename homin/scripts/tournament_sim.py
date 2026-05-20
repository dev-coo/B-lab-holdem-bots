"""실제 서버 블라인드 스케줄로 토너먼트 round-robin.

두 모드:
    - --mode hu : HU round-robin (쌍당 N 토너먼트)
    - --mode multi : N-way (전체 전략을 한 테이블에 모아 tournament 반복)

bootstrap_sim.py (고정 blind cash-style) 과 달리 BOT_GUIDE §8 테이블 급상승 반영.

Usage:
    uv run python scripts/tournament_sim.py
    uv run python scripts/tournament_sim.py --mode multi --tourns 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import random   # noqa: E402

from holdem.simulate.strategies import all_strategies   # noqa: E402
from holdem.simulate.bot_strategy import make_bot_strategy   # noqa: E402
from holdem.simulate.tournament import (   # noqa: E402
    BlindSchedule, round_robin, run_tournament_multi,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["hu", "multi"], default="hu",
                    help="hu=쌍별 round-robin, multi=전원 한 테이블")
    ap.add_argument("--per-pair", type=int, default=10, help="(hu) 쌍당 토너먼트 횟수")
    ap.add_argument("--tourns", type=int, default=20, help="(multi) 반복 토너먼트 수")
    ap.add_argument("--max-hands", type=int, default=500, help="토너먼트 당 최대 핸드")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--include-bot", action="store_true",
                    help="실제 holdem.decide.policy.decide() 봇을 strategies 에 추가")
    ap.add_argument("--bot-mode", choices=["safe", "ev-tree"], default="safe",
                    help="봇 모드 — safe (pot-odds) | ev-tree (D6 postflop)")
    ap.add_argument("--final-table-size", type=int, default=4,
                    help="bubble survival / final-table chips 임계 alive 수")
    args = ap.parse_args()

    schedule = BlindSchedule.from_yaml()
    strategies = all_strategies()
    if args.include_bot:
        bot_label = f"bot-{args.bot_mode}"
        strategies = strategies + [make_bot_strategy(
            name=bot_label,
            use_ev_tree=(args.bot_mode == "ev-tree"),
        )]
    names = [s.name for s in strategies]
    print(f"# schedule: starting={schedule.starting_stack} levels={len(schedule.levels)}")
    print(f"# strategies={names}")
    print(f"# mode={args.mode} max_hands={args.max_hands}")

    start = time.perf_counter()
    if args.mode == "multi":
        return _run_multi(args, schedule, strategies, names, start)

    print(f"# pairs={len(names) * (len(names) - 1) // 2} per_pair={args.per_pair}")
    results = round_robin(
        strategies, schedule=schedule,
        tournaments_per_pair=args.per_pair,
        max_hands=args.max_hands,
        base_seed=args.seed,
    )
    elapsed = time.perf_counter() - start

    # 전략별 통계 집계
    agg = {n: {"wins": 0, "losses": 0, "splits": 0, "tourns": 0,
               "total_hands": 0.0, "total_level": 0.0} for n in names}
    for (a, b), row in results.items():
        agg[a]["wins"] += row["wins_a"]
        agg[a]["losses"] += row["wins_b"]
        agg[a]["splits"] += row["splits"]
        agg[a]["tourns"] += args.per_pair
        agg[a]["total_hands"] += row["avg_hands"] * args.per_pair
        agg[a]["total_level"] += row["avg_final_level"] * args.per_pair

        agg[b]["wins"] += row["wins_b"]
        agg[b]["losses"] += row["wins_a"]
        agg[b]["splits"] += row["splits"]
        agg[b]["tourns"] += args.per_pair
        agg[b]["total_hands"] += row["avg_hands"] * args.per_pair
        agg[b]["total_level"] += row["avg_final_level"] * args.per_pair

    print(f"\n=== 쌍별 win-rate ===")
    for (a, b), row in sorted(results.items()):
        wr_a = row["wins_a"] / max(1, args.per_pair)
        print(f"  {a:12s} vs {b:12s}  {row['wins_a']:3d}/{row['wins_b']:3d}/{row['splits']:2d}  "
              f"avg_hands={row['avg_hands']:5.1f}  avg_level={row['avg_final_level']:4.1f}  "
              f"({wr_a*100:.0f}% A-win)")

    print(f"\n=== 전략별 종합 (n={names[0] and args.per_pair * (len(names)-1)} tourn) ===")
    print(f"{'strategy':12s}  {'wins':>5s}/{'loss':>5s}/{'split':>5s}  "
          f"{'winrate':>8s}  {'avg_hands':>10s}  {'avg_level':>10s}")
    rows = []
    for n in names:
        a = agg[n]
        t = max(1, a["tourns"])
        rows.append({
            "name": n,
            "wins": a["wins"], "losses": a["losses"], "splits": a["splits"],
            "winrate": a["wins"] / t,
            "avg_hands": a["total_hands"] / t,
            "avg_level": a["total_level"] / t,
        })
    rows.sort(key=lambda r: -r["winrate"])
    for r in rows:
        print(f"  {r['name']:12s}  {r['wins']:5d}/{r['losses']:5d}/{r['splits']:5d}  "
              f"{r['winrate']*100:7.1f}%  {r['avg_hands']:10.1f}  {r['avg_level']:10.1f}")

    print(f"\n# elapsed {elapsed:.1f}s")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as f:
            json.dump({
                "schedule": {"starting_stack": schedule.starting_stack,
                             "n_levels": len(schedule.levels)},
                "config": vars(args),
                "pairs": {f"{a} vs {b}": row for (a, b), row in results.items()},
                "totals": rows,
            }, f, indent=2, default=str)
        print(f"# saved → {args.output}")


def _run_multi(args, schedule, strategies, names, start):
    """Multi-way 전원 한 테이블. N=len(strategies) 명 참가, tourns 회 반복."""
    n = len(strategies)
    # ITM 점수표: 1위=n-1점, 최하=0점 → 평균은 정규화 지표.
    scores = {nm: 0.0 for nm in names}
    ranks = {nm: [] for nm in names}
    total_hands = 0
    total_level = 0
    itm_cut = max(1, n // 3)   # 상위 1/3 = ITM 정의

    itm_counts = {nm: 0 for nm in names}
    win_counts = {nm: 0 for nm in names}

    # P4 신규 메트릭: bubble survival + final-table chips.
    # final_table_size 이하로 alive 가 떨어진 시점에 strategy 가 살아있었나?
    ft_size = args.final_table_size
    ft_reach_counts = {nm: 0 for nm in names}        # 도달 횟수
    ft_chip_sum = {nm: 0 for nm in names}            # 도달 시 누적 스택
    ft_applicable = ft_size < n   # ft 임계가 시작 인원 미만이어야 의미.

    print(f"# tourns={args.tourns}  ITM_cut=top{itm_cut}  ft_size={ft_size}")
    for t in range(args.tourns):
        rng = random.Random(args.seed + t * 1000)
        res = run_tournament_multi(
            strategies=strategies, schedule=schedule,
            max_hands=args.max_hands, rng=rng,
        )
        total_hands += res.n_hands
        total_level += res.final_level
        for rank, nm in enumerate(res.finishing_order):
            base = nm.split("#")[0]  # suffix 제거 — 고유 이름 전략만 사용.
            if base not in scores:
                continue
            rank_points = (n - 1) - rank
            scores[base] += rank_points
            ranks[base].append(rank)
            if rank < itm_cut:
                itm_counts[base] += 1
            if rank == 0:
                win_counts[base] += 1

        # final-table snapshot: alive==ft_size 도달 첫 시점 ─ chips_at_n_players[ft_size].
        if ft_applicable and ft_size in res.chips_at_n_players:
            snap = res.chips_at_n_players[ft_size]
            for raw_name, stack in snap.items():
                base = raw_name.split("#")[0]
                if base not in scores:
                    continue
                ft_reach_counts[base] += 1
                ft_chip_sum[base] += stack

    elapsed = time.perf_counter() - start

    print(f"\n=== Multi-way round-robin ({args.tourns} 토너먼트) ===")
    if ft_applicable:
        header = (f"{'strategy':14s}  {'1st':>5s}  {'1st%':>6s}  "
                  f"{'ITM':>5s}  {'ITM%':>6s}  {'avg_rank':>9s}  {'avg_pts':>8s}  "
                  f"{'ft_rate':>8s}  {'ft_chips':>9s}")
    else:
        header = (f"{'strategy':14s}  {'1st':>5s}  {'1st%':>6s}  "
                  f"{'ITM':>5s}  {'ITM%':>6s}  {'avg_rank':>9s}  {'avg_pts':>8s}")
    print(header)

    rows = []
    for nm in names:
        rlist = ranks[nm]
        avg_rank = sum(rlist) / max(1, len(rlist))
        avg_pts = scores[nm] / max(1, args.tourns)
        first_pct = win_counts[nm] / max(1, args.tourns) * 100
        itm_pct = itm_counts[nm] / max(1, args.tourns) * 100
        ft_rate = (ft_reach_counts[nm] / max(1, args.tourns) * 100) if ft_applicable else None
        ft_chips_avg = (
            ft_chip_sum[nm] / ft_reach_counts[nm]
            if (ft_applicable and ft_reach_counts[nm] > 0) else None
        )
        rows.append({
            "name": nm,
            "wins": win_counts[nm],
            "first_place_rate": first_pct,
            "itm": itm_counts[nm],
            "itm_pct": itm_pct,
            "avg_rank": avg_rank,
            "avg_pts": avg_pts,
            "bubble_survival_rate": ft_rate,
            "mean_chips_at_final_table": ft_chips_avg,
        })
    rows.sort(key=lambda r: -r["first_place_rate"])
    for r in rows:
        if ft_applicable:
            ft_rate_s = f"{r['bubble_survival_rate']:6.1f}%" if r['bubble_survival_rate'] is not None else "    —"
            ft_ch_s = f"{r['mean_chips_at_final_table']:9.0f}" if r['mean_chips_at_final_table'] is not None else "        —"
            print(f"  {r['name']:14s}  {r['wins']:5d}  {r['first_place_rate']:5.1f}%  "
                  f"{r['itm']:5d}  {r['itm_pct']:5.1f}%  {r['avg_rank']:9.2f}  {r['avg_pts']:8.2f}  "
                  f"{ft_rate_s}  {ft_ch_s}")
        else:
            print(f"  {r['name']:14s}  {r['wins']:5d}  {r['first_place_rate']:5.1f}%  "
                  f"{r['itm']:5d}  {r['itm_pct']:5.1f}%  {r['avg_rank']:9.2f}  {r['avg_pts']:8.2f}")
    print(f"\n# avg_hands={total_hands/args.tourns:.1f}  avg_final_level={total_level/args.tourns:.1f}")
    print(f"# elapsed {elapsed:.1f}s")

    if args.output:
        import json
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as f:
            json.dump({
                "mode": "multi",
                "schedule": {"starting_stack": schedule.starting_stack,
                             "n_levels": len(schedule.levels)},
                "config": vars(args),
                "totals": rows,
                "avg_hands": total_hands / args.tourns,
                "avg_final_level": total_level / args.tourns,
            }, f, indent=2, default=str)
        print(f"# saved → {args.output}")


if __name__ == "__main__":
    main()
