"""HU 토너먼트 시뮬레이터 — blind 레벨 상승 + stack 연속성.

근거:
    - configs/blind_schedule.yaml (BOT_GUIDE §8)
    - r4 dev_log §5 limitations — 고정 blind → 레벨 상승 지원 필요.

핸드 엔진 `run_hand` 을 반복 호출하면서:
    1. Hand counter 증분.
    2. 현 레벨의 `hands` 를 넘으면 다음 레벨로.
    3. SB/BB 자리 교대 (HU: alternating).
    4. 한쪽 스택 ≤ 0 이면 종료.

미지원 (후속):
    - 3+ player 토너먼트 (engine.py 가 HU only).
    - Side pot (단일 pot 만 처리).
    - ICM / 상금 구조.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml

from .engine import HandResult, run_hand
from .engine_multi import MultiHandResult, run_hand_multi
from .strategies import BaselineStrategy

_SCHEDULE_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "blind_schedule.yaml"
)


@dataclass(frozen=True)
class BlindLevel:
    level: int
    sb: int
    bb: int
    hands: int | None   # None → infinite (최종 레벨)


@dataclass(frozen=True)
class BlindSchedule:
    starting_stack: int
    levels: tuple[BlindLevel, ...]

    @classmethod
    def from_yaml(cls, path: Path = _SCHEDULE_PATH) -> "BlindSchedule":
        with path.open() as f:
            data = yaml.safe_load(f)
        levels = tuple(
            BlindLevel(
                level=int(l["level"]),
                sb=int(l["sb"]),
                bb=int(l["bb"]),
                hands=(None if l.get("hands") is None else int(l["hands"])),
            )
            for l in data["levels"]
        )
        return cls(starting_stack=int(data["starting_stack"]), levels=levels)

    def level_at(self, hand_number: int) -> BlindLevel:
        """1-indexed hand_number → 해당 레벨. 초과 시 최종 레벨 반환."""
        elapsed = 0
        for lv in self.levels:
            if lv.hands is None:
                return lv
            next_elapsed = elapsed + lv.hands
            if hand_number <= next_elapsed:
                return lv
            elapsed = next_elapsed
        return self.levels[-1]


@dataclass
class TournamentResult:
    n_hands: int
    winner_name: str | None        # None = cap 초과로 중단
    final_stacks: dict[str, int]   # 이름 → 최종 스택
    final_level: int
    hand_results: list[HandResult] = field(default_factory=list)
    level_history: list[tuple[int, int]] = field(default_factory=list)  # (hand_no, level)


def run_tournament(
    strategy_a: BaselineStrategy,
    strategy_b: BaselineStrategy,
    schedule: BlindSchedule | None = None,
    max_hands: int = 2000,
    rng: random.Random | None = None,
    record_hands: bool = False,
) -> TournamentResult:
    """HU 토너먼트 — 스택 0 또는 `max_hands` 도달까지.

    record_hands=True 면 모든 HandResult 를 결과에 포함 (메모리 ↑).
    """
    schedule = schedule or BlindSchedule.from_yaml()
    rng = rng or random.Random()

    # 자리 배치: 매 핸드 SB/BB 교대. 핸드 1 은 A=SB, B=BB.
    name_a = strategy_a.name
    name_b = strategy_b.name
    stack_a = schedule.starting_stack
    stack_b = schedule.starting_stack

    hand_results: list[HandResult] = []
    level_history: list[tuple[int, int]] = []
    current_level = schedule.levels[0].level
    level_history.append((1, current_level))

    hand_no = 0
    winner: str | None = None
    while hand_no < max_hands:
        hand_no += 1
        lv = schedule.level_at(hand_no)
        if lv.level != current_level:
            current_level = lv.level
            level_history.append((hand_no, current_level))

        # HU 자리 교대: odd hand → A=SB, even hand → B=SB.
        if hand_no % 2 == 1:
            sb_strat, bb_strat = strategy_a, strategy_b
            sb_stack, bb_stack = stack_a, stack_b
        else:
            sb_strat, bb_strat = strategy_b, strategy_a
            sb_stack, bb_stack = stack_b, stack_a

        if sb_stack <= 0 or bb_stack <= 0:
            # 앞 핸드에서 이미 결판 — break (아래 체크 중복 방지).
            break

        res = run_hand(
            sb_strategy=sb_strat,
            bb_strategy=bb_strat,
            sb_stack=sb_stack,
            bb_stack=bb_stack,
            bb=lv.bb,
            sb_amount=lv.sb,
            rng=rng,
        )
        if record_hands:
            hand_results.append(res)

        # 결과 스택 흡수
        new_sb, new_bb = res.final_stacks
        if hand_no % 2 == 1:
            stack_a, stack_b = new_sb, new_bb
        else:
            stack_b, stack_a = new_sb, new_bb

        # 종료 조건
        if stack_a <= 0 and stack_b > 0:
            winner = name_b
            break
        if stack_b <= 0 and stack_a > 0:
            winner = name_a
            break
        if stack_a <= 0 and stack_b <= 0:
            # 동시 0 (split all-in 후 나누기 로직의 정수 잔차) — 더 큰 쪽 없음, break.
            winner = None
            break

    return TournamentResult(
        n_hands=hand_no,
        winner_name=winner,
        final_stacks={name_a: stack_a, name_b: stack_b},
        final_level=current_level,
        hand_results=hand_results,
        level_history=level_history,
    )


def round_robin(
    strategies: Sequence[BaselineStrategy],
    schedule: BlindSchedule | None = None,
    tournaments_per_pair: int = 10,
    max_hands: int = 2000,
    base_seed: int = 0,
) -> dict[tuple[str, str], dict]:
    """전략쌍 round-robin. 각 쌍 `tournaments_per_pair` 회 반복 → winrate.

    Returns:
        {(a, b): {"wins_a": n, "wins_b": n, "splits": n, "avg_hands": f, "avg_final_level": f}}
    """
    schedule = schedule or BlindSchedule.from_yaml()
    out: dict[tuple[str, str], dict] = {}
    for i, a in enumerate(strategies):
        for b in strategies[i + 1:]:
            wins_a = wins_b = splits = 0
            total_hands = total_level = 0
            for t in range(tournaments_per_pair):
                rng = random.Random(base_seed + hash((a.name, b.name, t)) & 0xFFFF)
                res = run_tournament(a, b, schedule, max_hands=max_hands, rng=rng)
                if res.winner_name == a.name:
                    wins_a += 1
                elif res.winner_name == b.name:
                    wins_b += 1
                else:
                    splits += 1
                total_hands += res.n_hands
                total_level += res.final_level
            out[(a.name, b.name)] = {
                "wins_a": wins_a,
                "wins_b": wins_b,
                "splits": splits,
                "avg_hands": total_hands / tournaments_per_pair,
                "avg_final_level": total_level / tournaments_per_pair,
            }
    return out


# --- 멀티웨이 (N=2~9) 토너먼트 ---

@dataclass
class MultiTournamentResult:
    n_hands: int
    n_players: int
    finishing_order: list[str]     # 탈락 순서의 역순 (index 0 = 우승자)
    final_stacks: dict[str, int]
    final_level: int
    level_history: list[tuple[int, int]] = field(default_factory=list)
    hand_results: list[MultiHandResult] = field(default_factory=list)
    # alive 플레이어 수가 임계치(예: 6,4,3,2) 로 떨어지는 시점의 스택 스냅샷.
    # 키 = 도달 시점의 alive 수, 값 = {player_name: stack}. P4 메트릭(bubble
    # survival rate / mean chips at final table) 계산용.
    chips_at_n_players: dict[int, dict[str, int]] = field(default_factory=dict)


def run_tournament_multi(
    strategies: Sequence[BaselineStrategy],
    schedule: BlindSchedule | None = None,
    max_hands: int = 2000,
    rng: random.Random | None = None,
    record_hands: bool = False,
) -> MultiTournamentResult:
    """N-way 토너먼트 — 마지막 1인 남거나 `max_hands` 도달까지.

    dealer button 은 매 핸드 시계방향 1칸 이동. 탈락자는 자리에서 제거.
    finishing_order 는 탈락 순 역순 (우승자 첫 원소).

    주의:
      - strategy.name 중복 지원 위해 내부적으로 "{name}#{idx}" 표식 사용.
      - 이름 충돌 시 final_stacks dict 는 마지막 값이 덮어씀 — suffix 사용 권장.
    """
    schedule = schedule or BlindSchedule.from_yaml()
    rng = rng or random.Random()
    n = len(strategies)
    if n < 2:
        raise ValueError("need at least 2 players")

    # 이름 충돌 방지: 같은 이름 전략이 여러 개면 suffix.
    name_counts: dict[str, int] = {}
    player_names: list[str] = []
    for s in strategies:
        name_counts[s.name] = name_counts.get(s.name, 0) + 1
    seen: dict[str, int] = {}
    for s in strategies:
        if name_counts[s.name] > 1:
            seen[s.name] = seen.get(s.name, 0) + 1
            player_names.append(f"{s.name}#{seen[s.name]}")
        else:
            player_names.append(s.name)

    stacks = [schedule.starting_stack] * n
    # alive_idx: 아직 살아있는 플레이어 idx (초기 전원).
    alive: list[int] = list(range(n))
    dealer_pos = 0   # alive 내 dealer index (SB 기준)

    hand_no = 0
    current_level = schedule.levels[0].level
    level_history: list[tuple[int, int]] = [(1, current_level)]
    hand_results: list[MultiHandResult] = []
    finishing_order_reverse: list[str] = []   # 탈락 순 (우승자 제외)

    # 임계치 기준 칩 스냅샷. n 명 → (n-1)/...→2 로 alive 가 처음 떨어지는 시점에 기록.
    # 예: 9명 시작 → alive==6 도달 첫 시점, 4 도달 첫 시점, 3, 2.
    snapshot_thresholds = sorted({k for k in (6, 4, 3, 2) if k < n}, reverse=True)
    chips_at_n_players: dict[int, dict[str, int]] = {}

    while hand_no < max_hands and len(alive) >= 2:
        hand_no += 1
        lv = schedule.level_at(hand_no)
        if lv.level != current_level:
            current_level = lv.level
            level_history.append((hand_no, current_level))

        # 현재 alive 플레이어들만 참가.
        active_strategies = [strategies[i] for i in alive]
        active_stacks = [stacks[i] for i in alive]
        sb_local = dealer_pos % len(alive)

        res = run_hand_multi(
            strategies=active_strategies,
            stacks=active_stacks,
            sb_idx=sb_local,
            bb=lv.bb,
            sb_amount=lv.sb,
            rng=rng,
        )
        if record_hands:
            hand_results.append(res)

        # 스택 업데이트
        for local_i, new_stack in enumerate(res.final_stacks):
            global_i = alive[local_i]
            stacks[global_i] = new_stack

        # 탈락 처리
        survivors = []
        eliminated = []
        for local_i, global_i in enumerate(alive):
            if stacks[global_i] > 0:
                survivors.append(global_i)
            else:
                eliminated.append(global_i)

        # 탈락 기록 (이번 핸드 여러 명 동시 탈락 가능)
        for global_i in eliminated:
            finishing_order_reverse.append(player_names[global_i])

        alive = survivors

        # 임계치 칩 스냅샷: alive 수가 thresholds 중 하나 이하로 처음 떨어졌을 때.
        # 한 핸드에서 다중 탈락으로 임계치 여러 개를 한꺼번에 통과할 수 있음.
        n_alive = len(alive)
        for th in list(snapshot_thresholds):
            if n_alive <= th and th not in chips_at_n_players:
                chips_at_n_players[th] = {
                    player_names[gi]: stacks[gi] for gi in alive
                }

        # dealer 이동: 다음 alive 의 다음 인덱스.
        if alive:
            dealer_pos = (dealer_pos + 1) % len(alive)

    # 우승자 (남은 사람)
    if len(alive) == 1:
        winner = player_names[alive[0]]
    elif len(alive) == 0:
        winner = None
    else:
        # max_hands 도달 후 2+ 생존 — 최대 스택을 우승자로.
        winner = player_names[max(alive, key=lambda i: stacks[i])]

    # finishing_order = [winner] + 탈락 역순
    finishing_order: list[str] = []
    if winner is not None:
        finishing_order.append(winner)
    # 추가 생존자 (max_hands 도달 시)
    for global_i in alive:
        nm = player_names[global_i]
        if nm != winner and nm not in finishing_order:
            finishing_order.append(nm)
    # 탈락 순 역순 추가
    for nm in reversed(finishing_order_reverse):
        if nm not in finishing_order:
            finishing_order.append(nm)

    final_stacks = {player_names[i]: stacks[i] for i in range(n)}

    return MultiTournamentResult(
        n_hands=hand_no,
        n_players=n,
        finishing_order=finishing_order,
        final_stacks=final_stacks,
        final_level=current_level,
        level_history=level_history,
        hand_results=hand_results,
        chips_at_n_players=chips_at_n_players,
    )
