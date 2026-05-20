"""Sizing optimizer — SizingGrid 의 허용 사이즈를 enumerate 해 EV 비교.

근거: plan 4-1 (sizing grid), I.1 (보수 grid), C1 (log-utility), D6.

입력:
    - ConservatismProfile (sizing_grid, allow_allin, bluff_factor 등)
    - EVInputs (pot, to_call, my_stack, my_bet, equity, bb)
    - DirichletResponse (상대 반응)
    - kind: "value" | "bluff" (사용할 grid 필드 결정)

반환:
    - candidate list: fold, check/call, raise@S1, raise@S2, ..., allin (허용 시)
    - 각 후보의 EVCandidate (chip_ev, log_util, variance)

보수 장치 (I.8):
    - allow_allin=False → all-in 후보 제거 (단, forced commit 제외: my_stack ≤ to_call).
"""
from __future__ import annotations

import random
from typing import Literal

from ..estimate.bayes import DirichletResponse
from .conservatism import ConservatismProfile
from .ev import EVCandidate, EVInputs, ev_call, ev_check, ev_fold, ev_raise

SizeKind = Literal["value", "bluff"]


def _grid_sizes(cons: ConservatismProfile, kind: SizeKind) -> tuple[float, ...]:
    if kind == "value":
        return cons.sizing_grid.value_bet
    return cons.sizing_grid.bluff_bet


def _raise_amount_from_ratio(ratio: float, pot_before: int, my_bet: int) -> int:
    """pot_before 대비 ratio 배의 사이즈를 총 베팅액으로 환산."""
    # delta = ratio · pot_before. 총 베팅 = my_bet + delta.
    delta = max(1, int(round(ratio * max(1, pot_before))))
    return my_bet + delta


def enumerate_candidates(
    cons: ConservatismProfile,
    response: DirichletResponse,
    inputs: EVInputs,
    *,
    kind: SizeKind = "value",
    rng: random.Random | None = None,
    include_allin: bool | None = None,
) -> list[EVCandidate]:
    """후보 EV 목록. grid 기반 raise 사이즈 + fold + call/check + 조건부 all-in."""
    out: list[EVCandidate] = [ev_fold(inputs)]

    if inputs.to_call == 0:
        out.append(ev_check(inputs))
    else:
        out.append(ev_call(inputs))

    if include_allin is None:
        include_allin = cons.allow_allin
    # forced commit: stack 이 to_call 이하면 colllin 이 바로 jam.
    forced_jam = inputs.my_stack <= max(1, inputs.to_call)

    # bluff 후보에는 conservatism 의 bluff_factor 적용 (fold equity 보수화).
    # value 후보는 1.0 (보수화 없음).
    bf = cons.bluff_factor if kind == "bluff" else 1.0

    for ratio in _grid_sizes(cons, kind):
        amount = _raise_amount_from_ratio(ratio, inputs.pot, inputs.my_bet)
        # server min_raise / my_stack 경계는 호출자가 보정. 여기서는 유효 범위만 체크.
        if amount <= inputs.my_bet:
            continue
        # to_call > 0 이면 raise 는 콜 금액(= my_bet + to_call) 을 초과해야 유효.
        # 작은 bluff 사이즈가 to_call 보다 낮으면 실제 raise 가 아닌 invalid bet 이라
        # EV tree 에서 잘못된 후보로 들어가지 않도록 제거.
        if inputs.to_call > 0 and amount <= inputs.my_bet + inputs.to_call:
            continue
        if amount > inputs.my_bet + inputs.my_stack:
            amount = inputs.my_bet + inputs.my_stack  # all-in 으로 캡
        c = ev_raise(amount=amount, response=response, inputs=inputs, rng=rng,
                     bluff_factor=bf)
        out.append(c)

    if include_allin or forced_jam:
        allin_amount = inputs.my_bet + inputs.my_stack
        # 이미 grid 에서 포함됐을 수 있음 — 중복 제거.
        if not any(c.action == "allin" for c in out):
            c = ev_raise(amount=allin_amount, response=response, inputs=inputs, rng=rng,
                         bluff_factor=bf)
            out.append(c)

    return out


def optimize(
    cons: ConservatismProfile,
    response: DirichletResponse,
    inputs: EVInputs,
    *,
    kind: SizeKind = "value",
    objective: Literal["chip_ev", "log_util"] = "log_util",
    rng: random.Random | None = None,
) -> EVCandidate:
    cands = enumerate_candidates(cons, response, inputs, kind=kind, rng=rng)
    key = (lambda c: c.chip_ev) if objective == "chip_ev" else (lambda c: c.log_util)
    return max(cands, key=key)
