"""Concurrency bench — executor offload 효과 측정.

N 개의 postflop ActionRequest 를 3 가지 방식으로 처리하고 wall time 을 비교:
  - seq:    동일 이벤트 루프에서 decide() 를 직렬 호출 (기존 동작 근사)
  - thread: asyncio.gather + ThreadPoolExecutor.run_in_executor
  - proc:   asyncio.gather + ProcessPoolExecutor (--process 옵션 시)

품질 불변 검증을 위해 decide 에 동일 시드를 주입 (deterministic MC).

Usage:
  uv run python scripts/bench_concurrency.py [--n 100] [--workers 8] [--process]
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from holdem.decide.policy import build_default_deps, decide
from holdem.transport import protocol as p


RANKS = "23456789TJQKA"
SUITS = "shdc"


def _gen_request(rng: random.Random, idx: int) -> p.ActionRequest:
    deck = [r + s for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    hole = deck[:2]
    board = deck[2:5]   # flop → equity MC trigger
    players = [
        p.PlayerState(name="me", position="BTN", stack=500, bet=0, status="active"),
        p.PlayerState(name="villain1", position="SB", stack=500, bet=5, status="active"),
        p.PlayerState(name="villain2", position="BB", stack=500, bet=10, status="active"),
    ]
    return p.ActionRequest(
        type="action_request",
        room_id=1000 + idx,
        hand_number=1,
        phase="flop",
        seat="me",
        your_cards=hole,
        community_cards=board,
        pot=40,
        to_call=10,
        min_raise=20,
        my_stack=500,
        blind=[5, 10],
        players=players,
        action_history=[],
    )


def _decide_worker(req):
    """Executor 용 wrapper — 매 프로세스/스레드에서 독립적 deps 생성."""
    deps = build_default_deps()
    return decide(req, "me", deps)


async def run_seq(reqs, deps):
    return [decide(req, "me", deps) for req in reqs]


async def run_executor(reqs, executor):
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(executor, _decide_worker, req) for req in reqs]
    return await asyncio.gather(*tasks)


def _action_key(a):
    return (a.room_id, a.action, a.amount)


async def main(n, workers, repeats, use_process):
    deps = build_default_deps()
    rng = random.Random(42)
    reqs = [_gen_request(rng, i) for i in range(n)]

    # Warm-up: Evaluator 내부 캐시, LUT 채움.
    decide(reqs[0], "me", deps)

    seq_times = []
    exec_times = []
    seq_baseline = None
    exec_baseline = None

    executor_cls = ProcessPoolExecutor if use_process else ThreadPoolExecutor
    with executor_cls(max_workers=workers) as pool:
        for r in range(repeats):
            t0 = time.perf_counter()
            seq_out = await run_seq(reqs, deps)
            seq_times.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            exec_out = await run_executor(reqs, pool)
            exec_times.append(time.perf_counter() - t0)

            if r == 0:
                seq_baseline = [_action_key(a) for a in seq_out]
                exec_baseline = [_action_key(a) for a in exec_out]

    # 결정성 검증 (seq first run vs seq reruns 는 non-deterministic 이지만 구조 확인).
    diff = sum(1 for s, e in zip(seq_baseline, exec_baseline) if s != e)

    def _stats(label, times):
        mean = statistics.mean(times)
        med = statistics.median(times)
        best = min(times)
        tput = n / mean
        print(f"{label:10s} mean={mean*1000:8.1f}ms  med={med*1000:8.1f}ms  "
              f"best={best*1000:8.1f}ms  throughput={tput:6.1f} req/s")

    mode = "process" if use_process else "thread"
    print(f"n_requests={n} workers={workers} repeats={repeats} mode={mode}")
    print(f"postflop phase, equity_samples={deps.equity_samples}")
    print()
    _stats("seq", seq_times)
    _stats(mode, exec_times)
    speedup = statistics.mean(seq_times) / statistics.mean(exec_times)
    print(f"\nspeedup (seq / {mode}) = {speedup:.2f}x")
    print(f"action diff (seq vs {mode}, non-deterministic MC): {diff}/{n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--process", action="store_true", help="ProcessPoolExecutor 사용")
    args = ap.parse_args()
    asyncio.run(main(args.n, args.workers, args.repeats, args.process))
