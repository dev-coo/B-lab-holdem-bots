"""1-ply EV tree — candidate action 별 기대값 계산.

근거: plan 부록 C, C1 (log-utility 단일화), D6.

모델:
    fold  : EV = 0 (기준점, 이미 투입된 금액은 sunk)
    call  : EV = eq · (pot + to_call) − to_call
    raise@S:
        ΔS = S − my_current_bet
        pot_after_raise = pot + ΔS (상대 pre-action 기준)
        villain_call_pot = pot + 2·ΔS
        EV = p_fold · pot
           + p_call · (eq · villain_call_pot − ΔS)
           + p_reraise · reraise_outcome_approx
    allin : raise@S 의 특수화 (S = my_stack).

단순화 (1-ply):
    - `p_reraise` 는 fold 또는 "call with jam" 로 흡수 (미세 effect).
    - Future street realization factor 0.9 는 부록 C 의 매직 — 현 구현은 1.0
      (평가 C3 에 따라 매직 넘버 제거, D6 단계는 realization=1.0).
    - Dirichlet response sample 은 "한 번의 decision 호출 내 1회" 로 일관 유지.

log-utility (평가 C1):
    U(s) = log(s + ε), ε = max(1, 5·BB − n_obs/20·BB)
    (n 커질수록 ε 작아져 보수성 완화)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..estimate.bayes import DirichletResponse


@dataclass(frozen=True)
class EVInputs:
    pot: int                       # 현재 팟 (to_call 투입 전)
    to_call: int                   # 내가 따라가야 할 콜 금액
    my_stack: int                  # 내 남은 스택
    my_bet: int                    # 이 라운드 이미 투입한 금액
    equity: float                  # vs 상대 range 승률 [0,1]
    bb: int                        # 블라인드 (log-utility 의 ε 계산용)
    # 상대 re-raise (3-bet/jam) range 대비 우리 equity.
    # None 일 때 `max(0.30, equity - 0.15)` 로 근사 (range narrowing penalty).
    equity_vs_reraise: float | None = None


@dataclass(frozen=True)
class EVCandidate:
    action: str                    # "fold" | "check" | "call" | "raise" | "allin"
    amount: int | None             # raise 총 베팅액, 외의 경우 None
    chip_ev: float                 # chip 단위 기대값
    log_util: float                # log-utility 값 (risk-adjusted)
    variance: float                # 추정 분산 (안전장치/튜닝 용)


def _stack_after(action: str, amount: int | None, inputs: EVInputs) -> tuple[float, float]:
    """action 수행 후 스택의 (win_case, lose_case) 근사.

    Returns (win_stack, lose_stack): equity prob 로 가중해 U 를 계산할 수치.
    """
    if action == "fold" or action == "check":
        return float(inputs.my_stack), float(inputs.my_stack)
    if action == "call":
        win = inputs.my_stack - inputs.to_call + (inputs.pot + inputs.to_call)
        lose = inputs.my_stack - inputs.to_call
        return float(win), float(lose)
    # raise / allin
    a = amount or 0
    delta = max(0, a - inputs.my_bet)
    # villain call assumption for log-utility 계산:
    villain_pot = inputs.pot + 2 * delta
    win = inputs.my_stack - delta + villain_pot
    lose = inputs.my_stack - delta
    return float(win), float(lose)


def _log_utility(win_stack: float, lose_stack: float, equity: float, epsilon: float) -> float:
    """U = eq · log(win+ε) + (1−eq) · log(lose+ε). stack=0 에서 −∞ 발산."""
    eps = max(1e-9, epsilon)
    win_u = math.log(max(eps, win_stack + eps))
    lose_u = math.log(max(eps, lose_stack + eps))
    return equity * win_u + (1.0 - equity) * lose_u


def _variance(win_stack: float, lose_stack: float, equity: float) -> float:
    mean = equity * win_stack + (1.0 - equity) * lose_stack
    return equity * (win_stack - mean) ** 2 + (1.0 - equity) * (lose_stack - mean) ** 2


def ev_fold(inputs: EVInputs) -> EVCandidate:
    u = _log_utility(*_stack_after("fold", None, inputs), equity=1.0, epsilon=inputs.bb)
    return EVCandidate(action="fold", amount=None, chip_ev=0.0, log_util=u, variance=0.0)


def ev_check(inputs: EVInputs) -> EVCandidate:
    assert inputs.to_call == 0, "check requires to_call == 0"
    # check 는 현재 스트릿 종료 근사; 다음 스트릿 기회값은 기본 0 (후속 EV tree 가 보완).
    u = _log_utility(*_stack_after("check", None, inputs), equity=1.0, epsilon=inputs.bb)
    return EVCandidate(action="check", amount=None, chip_ev=0.0, log_util=u, variance=0.0)


def ev_call(inputs: EVInputs) -> EVCandidate:
    # chip EV (부록 C 4-1): eq · (pot + to_call) − to_call
    chip = inputs.equity * (inputs.pot + inputs.to_call) - inputs.to_call
    win, lose = _stack_after("call", None, inputs)
    u = _log_utility(win, lose, inputs.equity, inputs.bb)
    var = _variance(win, lose, inputs.equity)
    return EVCandidate(action="call", amount=None, chip_ev=chip, log_util=u, variance=var)


def ev_raise(
    amount: int,
    response: DirichletResponse,
    inputs: EVInputs,
    rng: random.Random | None = None,
    *,
    bluff_factor: float = 1.0,
) -> EVCandidate:
    """raise 사이즈 S 에 대한 1-ply EV.

    상대 반응은 Dirichlet sample (Thompson). 한 호출에서 1회 뽑아 일관 사용.

    bluff_factor (∈ (0, 1]) — bluff 후보에 대한 보수성 스케일러. 1.0 이면 GTO
    가정, < 1.0 이면 fold equity 를 그만큼 깎아 보수적으로 평가 (ConservatismProfile
    의 bluff_factor 가 sizing.enumerate_candidates(kind="bluff") 경유로 전달).
    """
    delta = max(0, amount - inputs.my_bet)
    if delta <= 0:
        # ineffective raise; treat as check
        return ev_check(inputs)
    sample = response.sample(rng=rng)
    # bluff_factor: fold equity 를 깎아서 bluff 의 EV 를 conservative 하게 평가.
    # 깎인 만큼은 call 쪽으로 흡수 (re-raise 확률은 보존 — 위험은 그대로).
    bf = max(0.0, min(1.0, bluff_factor))
    p_fold = sample["fold"] * bf
    absorbed = sample["fold"] - p_fold
    p_call = sample["call"] + absorbed
    p_raise = sample["raise"]

    # p_fold: 상대 fold → pot 획득 (my chips 투입 없음).
    win_if_fold = float(inputs.pot)
    # p_call: 상대 call → villain_pot 에서 equity 경쟁.
    villain_pot = inputs.pot + 2 * delta
    ev_vs_call = inputs.equity * villain_pot - delta

    # p_raise (reraise): 상대가 3bet/jam → 우리는 pot-odds 게이트로 call/fold.
    # 가정: reraise 는 전체 스택까지의 commit (보수적). 상대 추가 투입 = my_stack_capable.
    #   - 상대 reraise_to ≈ pot + 3·delta (pot-sized 3bet 근사), 단 my_stack 상한.
    #   - 우리 추가 콜 금액 extra_call = reraise_to − delta.
    #   - pot_after_reraise_call = pot_after_reraise + extra_call.
    #   - eq_vs_reraise: 좁아진 range 대비 — range narrowing penalty.
    eq_vs_rr = inputs.equity_vs_reraise
    if eq_vs_rr is None:
        eq_vs_rr = max(0.30, inputs.equity - 0.15)
    reraise_commit = min(inputs.my_stack, inputs.pot + 3 * delta)
    extra_call = max(0, reraise_commit - delta)
    pot_after_reraise = inputs.pot + delta + reraise_commit  # 상대 투입 = reraise_commit
    pot_if_we_call = pot_after_reraise + extra_call
    # 우리 call 시 pot odds 필요 equity
    required_eq_rr = extra_call / max(1, pot_if_we_call) if extra_call > 0 else 0.0
    call_reraise_is_plus = eq_vs_rr >= required_eq_rr and extra_call <= inputs.my_stack

    if call_reraise_is_plus:
        ev_vs_reraise = eq_vs_rr * pot_if_we_call - (delta + extra_call)
    else:
        ev_vs_reraise = -float(delta)  # fold: 이미 투입된 delta 손실

    chip = p_fold * win_if_fold + p_call * ev_vs_call + p_raise * ev_vs_reraise

    # log-utility — p_call 경로 기준으로 win/lose 스택 산출
    win, lose = _stack_after("raise", amount, inputs)
    # fold 시나리오에서는 스택은 my_stack + pot
    win_if_fold_stack = inputs.my_stack + inputs.pot
    # reraise 경로의 스택 분포 (eq_vs_rr 로 평균):
    if call_reraise_is_plus:
        reraise_win_stack = inputs.my_stack - (delta + extra_call) + pot_if_we_call
        reraise_lose_stack = inputs.my_stack - (delta + extra_call)
        u_reraise = _log_utility(reraise_win_stack, reraise_lose_stack, eq_vs_rr, inputs.bb)
    else:
        reraise_fold_stack = inputs.my_stack - delta
        u_reraise = math.log(max(1e-9, reraise_fold_stack + inputs.bb))

    u_fold = math.log(max(1e-9, win_if_fold_stack + inputs.bb))
    u_call = _log_utility(win, lose, inputs.equity, inputs.bb)
    u = p_fold * u_fold + p_call * u_call + p_raise * u_reraise

    var = _variance(win, lose, inputs.equity)
    is_allin = amount >= inputs.my_bet + inputs.my_stack
    return EVCandidate(
        action="allin" if is_allin else "raise",
        amount=amount,
        chip_ev=chip,
        log_util=u,
        variance=var,
    )


def pick_best(candidates: list[EVCandidate], objective: str = "log_util") -> EVCandidate:
    """objective ∈ {chip_ev, log_util} — log_util 이 기본 (평가 C1)."""
    if not candidates:
        raise ValueError("no candidates")
    key = (lambda c: c.chip_ev) if objective == "chip_ev" else (lambda c: c.log_util)
    return max(candidates, key=key)
