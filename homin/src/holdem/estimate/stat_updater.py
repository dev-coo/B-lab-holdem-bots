"""Event → stat updater — action_history 파싱해 PlayerProfile metric 갱신.

근거: plan H.1 (metric 정의), D3 Day 16.

설계:
  - 핸드 완료 후 `update_from_hand(...)` 호출. hand_result / action_request 시점
    모두 사용 가능 (action_history 만 있으면 됨).
  - 플레이어별 "이번 핸드 동안의 state" 를 1-pass 로 만들고, 끝에서
    BetaCounter.observe 로 한 번에 반영.
  - 블라인드 post 는 action_history 에 포함되지 않음 (BOT_GUIDE §5.4). VPIP 는
    voluntary action 만 집계.

지원 metric (우선순위 순):
  VPIP, PFR, THREE_BET, FOLD_TO_THREE_BET, CBET, FOLD_TO_CBET,
  BARREL_TURN, BARREL_RIVER, CHECK_RAISE, aggression factor (bet+raise vs call)

미지원 (별도 쇼다운 라벨러에서):
  BLUFF_AT_SHOWDOWN — hand_result.showdown 으로 처리.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..state.player_profile import PlayerProfile
from ..transport import protocol as p


@dataclass
class _StreetContext:
    phase: str
    n_raises: int = 0
    aggressor: str | None = None           # 마지막 raise 한 자
    last_bettor: str | None = None         # 마지막 bet/raise — check-raise 판정용
    players_acted: set[str] = field(default_factory=set)
    checked_this_street: set[str] = field(default_factory=set)


@dataclass
class _PerPlayer:
    vpip: bool = False
    pfr: bool = False
    three_bet_opp: bool = False            # 2bet 상황에서 액션 기회가 있었는가
    three_bet: bool = False
    faced_three_bet: bool = False
    folded_to_three_bet: bool = False
    # Postflop — 프리플롭 최종 aggressor 역할
    was_pfr_aggressor: bool = False
    cbet_opp: bool = False                 # flop 도달 AND pfr aggressor
    cbet: bool = False
    turn_barrel_opp: bool = False          # cbet 한 자가 turn 에 도달
    turn_barrel: bool = False
    river_barrel_opp: bool = False
    river_barrel: bool = False
    # CBET 수비
    faced_cbet: bool = False
    folded_to_cbet: bool = False
    # Check-raise — 동일 스트릿 내
    check_then_raise: list[str] = field(default_factory=list)  # phase 기록
    # Aggression (postflop bet+raise vs call)
    agg_bet_raise: int = 0
    agg_call: int = 0


def update_from_hand(
    profiles: dict[str, PlayerProfile],
    history: Iterable[p.HistoryEntry],
    participants: Iterable[str],
    hands_seen_weight: float = 1.0,
) -> dict[str, _PerPlayer]:
    """완료된 핸드의 action_history 를 파싱해 각 참여자 프로필 갱신.

    Returns per-player 중간 집계 (테스트·디버깅 용).
    """
    participants = list(participants)
    per: dict[str, _PerPlayer] = {n: _PerPlayer() for n in participants}

    streets: dict[str, _StreetContext] = {}
    pfr_aggressor: str | None = None  # 프리플롭 마지막 raiser

    for entry in history:
        ph = entry.phase
        player = entry.player
        action = entry.action
        if player not in per:
            per[player] = _PerPlayer()
        pp = per[player]
        sc = streets.setdefault(ph, _StreetContext(phase=ph))

        # --- preflop metrics ---
        if ph == "preflop":
            if action in ("call", "raise", "allin"):
                pp.vpip = True
            if action == "raise":
                pp.pfr = True
                sc.n_raises += 1
                if sc.n_raises == 1:
                    # 오프너. 3-bet 대상이 될 수 있음.
                    pass
                elif sc.n_raises == 2:
                    # 이 raise 가 3bet.
                    pp.three_bet = True
                    # 이전 오프너는 faced_three_bet
                    if sc.aggressor is not None and sc.aggressor != player:
                        per.setdefault(sc.aggressor, _PerPlayer()).faced_three_bet = True
                sc.aggressor = player
                pfr_aggressor = player
            elif action == "fold":
                # 3-bet 을 마주친 후 폴드?
                if sc.n_raises >= 2 and per.get(player) and per[player].faced_three_bet:
                    pp.folded_to_three_bet = True
            elif action == "allin":
                # allin 을 raise 성격으로 취급 (이번 라운드 베팅 증가 가정).
                sc.n_raises += 1
                if sc.n_raises == 2:
                    pp.three_bet = True
                    if sc.aggressor is not None and sc.aggressor != player:
                        per.setdefault(sc.aggressor, _PerPlayer()).faced_three_bet = True
                sc.aggressor = player
                pfr_aggressor = player

        # --- postflop metrics ---
        else:
            is_first_bet_on_street = sc.n_raises == 0 and sc.last_bettor is None
            if action == "raise" or action == "allin":
                if is_first_bet_on_street:
                    # CBET 판정 — 프리플롭 aggressor 의 첫 베팅
                    if ph == "flop" and pfr_aggressor == player:
                        pp.cbet_opp = True
                        pp.cbet = True
                    elif ph == "turn" and pfr_aggressor == player:
                        # turn_barrel 은 cbet 한 사람이 다시 bet 할 때
                        if per.get(player) and per[player].cbet:
                            pp.turn_barrel_opp = True
                            pp.turn_barrel = True
                    elif ph == "river" and pfr_aggressor == player:
                        if per.get(player) and per[player].turn_barrel:
                            pp.river_barrel_opp = True
                            pp.river_barrel = True
                # check-raise: 본인이 같은 스트릿에 check 이력 있음 + 이미 bet/raise 가 있음
                if player in sc.checked_this_street and sc.last_bettor is not None:
                    pp.check_then_raise.append(ph)
                sc.n_raises += 1
                sc.aggressor = player
                sc.last_bettor = player
                pp.agg_bet_raise += 1
            elif action == "call":
                pp.agg_call += 1
                # faced_cbet?
                if ph == "flop" and sc.last_bettor is not None:
                    aggressor_prof = per.get(sc.last_bettor)
                    if aggressor_prof and aggressor_prof.cbet:
                        pp.faced_cbet = True
            elif action == "check":
                sc.checked_this_street.add(player)
            elif action == "fold":
                if ph == "flop" and sc.last_bettor is not None:
                    aggressor_prof = per.get(sc.last_bettor)
                    if aggressor_prof and aggressor_prof.cbet:
                        pp.faced_cbet = True
                        pp.folded_to_cbet = True

        sc.players_acted.add(player)

    # Preflop 기회 판정 — VPIP/PFR 은 모든 참여자 대상 (fold 든 아니든)
    # THREE_BET opp: 프리플롭에서 n_raises >= 1 도달했을 때 그 이후 액션한 자
    # 간단화: 참여자 모두에게 기회 부여 (noise tolerable).
    # CBET opp: flop 도달 여부 — streets dict 에 flop 있는가
    flop_reached = "flop" in streets
    turn_reached = "turn" in streets
    river_reached = "river" in streets

    # --- BetaCounter 업데이트 ---
    for name, data in per.items():
        prof = profiles.setdefault(name, PlayerProfile(name=name))
        prof.hands_seen += hands_seen_weight if name in participants else 0

        # VPIP / PFR — 모든 preflop 참가자에게 기회 부여
        if name in participants:
            prof.get("VPIP").observe(data.vpip)
            prof.get("PFR").observe(data.pfr)

        # THREE_BET — preflop 참여 AND 2bet 상황에 직면한 경우만 opp. 간단화: VPIP 한 자에게 부여.
        if data.vpip:
            prof.get("THREE_BET").observe(data.three_bet)

        # FOLD_TO_THREE_BET
        if data.faced_three_bet:
            prof.get("FOLD_TO_THREE_BET").observe(data.folded_to_three_bet)

        # CBET (only preflop aggressor who reached flop)
        if flop_reached and pfr_aggressor == name:
            prof.get("CBET").observe(data.cbet)
            if turn_reached and data.cbet:
                prof.get("BARREL_TURN").observe(data.turn_barrel)
                if river_reached and data.turn_barrel:
                    prof.get("BARREL_RIVER").observe(data.river_barrel)

        # FOLD_TO_CBET
        if data.faced_cbet:
            prof.get("FOLD_TO_CBET").observe(data.folded_to_cbet)

        # CHECK_RAISE — streets 를 본 횟수 만큼 기회. 최소 이 플레이어가 check 한 스트릿 수.
        check_opps = 0
        for ph, sc in streets.items():
            if ph == "preflop":
                continue
            if name in sc.checked_this_street:
                check_opps += 1
        if check_opps > 0:
            hits = len(data.check_then_raise)
            prof.get("CHECK_RAISE").observe(hits > 0)  # 핸드당 1회 기회로 집계

        # Aggression factor
        if data.agg_bet_raise > 0:
            prof.aggression.observe_aggressive(weight=data.agg_bet_raise)
        if data.agg_call > 0:
            prof.aggression.observe_passive(weight=data.agg_call)

    return per
