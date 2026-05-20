from __future__ import annotations

from holdem.decide.conservatism import (
    compute_profile,
    load_schedule,
    load_sizing_grid,
)
from holdem.state.player_profile import PlayerProfile


def test_schedule_loads_with_sorted_buckets():
    sch = load_schedule()
    names = [b.name for b in sch.buckets]
    assert names[0] == "hard_conservative"
    assert names[-1] == "exploit_ready"
    # None 은 catchall → 마지막에 정렬됨
    assert sch.buckets[-1].max_n is None


def test_sizing_grids_load():
    cons = load_sizing_grid("conservative")
    bal = load_sizing_grid("balanced")
    exp = load_sizing_grid("exploit")
    assert cons.max_bet_to_pot <= bal.max_bet_to_pot <= exp.max_bet_to_pot
    # conservative 는 value_bet 상한이 작아야 함
    assert max(cons.value_bet) <= max(bal.value_bet)


def test_unknown_opponent_is_hard_conservative():
    prof = compute_profile(None)
    assert prof.mode == "hard_conservative"
    assert prof.sizing_grid.name == "conservative"
    assert prof.allow_allin is False
    assert prof.bluff_factor <= 0.55


def test_small_data_is_conservative():
    # profile 몇 핸드만 관측 → conservative
    player = PlayerProfile(name="small", hands_seen=8)
    player.get("VPIP").alpha = 2
    player.get("VPIP").beta = 6
    prof = compute_profile(player)
    # n_personal=8, n_class=8, n_pop=100 → n_eff = 8 + 0.3*8 + 5 = 15.4 → conservative
    assert prof.mode in ("hard_conservative", "conservative")
    assert prof.sizing_grid.name == "conservative"


def test_moderate_data_is_transitional_or_higher():
    player = PlayerProfile(name="mid", hands_seen=100)
    player.get("VPIP").alpha = 25
    player.get("VPIP").beta = 75
    prof = compute_profile(player)
    # n_personal=100, n_class=100, n_pop=100 → n_eff = 100 + 30 + 5 = 135 → near_balanced
    assert prof.mode in ("transitional", "near_balanced")
    assert prof.sizing_grid.name == "balanced"
    assert prof.allow_allin is True


def test_heavy_data_reaches_exploit_ready():
    player = PlayerProfile(name="heavy", hands_seen=1000)
    player.get("VPIP").alpha = 250
    player.get("VPIP").beta = 750
    prof = compute_profile(player)
    # n_personal=1000, n_class=1000, n_pop=100 → n_eff = 1000 + 300 + 5 = 1305 → exploit_ready
    assert prof.mode == "exploit_ready"
    assert prof.sizing_grid.name == "exploit"


def test_bluff_factor_monotonically_increases_with_data():
    prof_cold = compute_profile(None)
    prof_mid_p = PlayerProfile(name="m", hands_seen=80)
    prof_mid_p.get("VPIP").alpha = 20
    prof_mid_p.get("VPIP").beta = 60
    prof_mid = compute_profile(prof_mid_p)
    assert prof_cold.bluff_factor <= prof_mid.bluff_factor


def test_lambda_multiplier_decreases_with_data():
    prof_cold = compute_profile(None)
    prof_heavy_p = PlayerProfile(name="h", hands_seen=500)
    prof_heavy_p.get("VPIP").alpha = 125
    prof_heavy_p.get("VPIP").beta = 375
    prof_heavy = compute_profile(prof_heavy_p)
    assert prof_cold.lambda_multiplier > prof_heavy.lambda_multiplier


def test_effective_n_components():
    sch = load_schedule()
    assert sch.effective_n(0, 0) == sch.w_pop * sch.pop_ess
    assert sch.effective_n(10, 0) == sch.w_personal * 10 + sch.w_pop * sch.pop_ess
