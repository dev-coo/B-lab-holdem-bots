"""Stage enum + identifier + bluff multiplier 단위 테스트."""
from __future__ import annotations

from holdem.decide.conservatism import compute_profile
from holdem.decide.stage import (
    Stage,
    apply_stage_to_conservatism,
    identify_stage,
    stage_bluff_multiplier,
)
from holdem.transport import protocol as p


def _req(n_named: int) -> p.ActionRequest:
    """n_named 명의 활성 플레이어로 구성된 ActionRequest. 카드/스택 등은 더미."""
    players = [
        p.PlayerState(name=f"p{i}", position="btn" if i == 0 else "bb",
                      stack=100, bet=0, status="active")
        for i in range(n_named)
    ]
    return p.ActionRequest(
        type="action_request",
        room_id=1, hand_number=1,
        your_cards=["Ah", "Ad"],
        community_cards=[],
        phase="preflop",
        pot=3, my_stack=100, to_call=2, min_raise=4,
        blind=[1, 2], seat="btn",
        players=players, action_history=[],
    )


def test_heads_up_at_two_players():
    assert identify_stage(_req(2)) == Stage.HEADS_UP


def test_final_table_at_three_to_four_players():
    assert identify_stage(_req(3)) == Stage.FINAL_TABLE
    assert identify_stage(_req(4)) == Stage.FINAL_TABLE


def test_near_final_at_five_to_six_players():
    assert identify_stage(_req(5)) == Stage.NEAR_FINAL
    assert identify_stage(_req(6)) == Stage.NEAR_FINAL


def test_mid_at_seven_to_eight_players():
    assert identify_stage(_req(7)) == Stage.MID
    assert identify_stage(_req(8)) == Stage.MID


def test_early_at_nine_plus_players():
    assert identify_stage(_req(9)) == Stage.EARLY


def test_empty_name_player_filtered_out():
    """빈 이름 더미 슬롯은 카운트 제외."""
    req = _req(2)
    # 더미 슬롯 2 개 추가하더라도 stage 는 여전히 HU.
    req.players.extend([
        p.PlayerState(name="", position=None, stack=0, bet=0, status="active"),
        p.PlayerState(name="   ", position=None, stack=0, bet=0, status="active"),
    ])
    assert identify_stage(req) == Stage.HEADS_UP


def test_stage_enum_has_string_value():
    """직렬화/로깅용으로 str enum 사용."""
    assert Stage.HEADS_UP.value == "heads_up"
    assert str(Stage.FINAL_TABLE.value) == "final_table"


def test_stage_bluff_multiplier_values():
    """early/mid = 1.0, near_final/final_table < 1.0 (보수), HU > 1.0 (공격).

    table_size 미지정 시 default flat. NEAR_FINAL ↔ FINAL_TABLE 의 상호 순서는
    table-size 별로 다르므로 flat 단조성 가정 안 함."""
    assert stage_bluff_multiplier(Stage.EARLY) == 1.0
    assert stage_bluff_multiplier(Stage.MID) == 1.0
    assert stage_bluff_multiplier(Stage.NEAR_FINAL) < 1.0
    assert stage_bluff_multiplier(Stage.FINAL_TABLE) < 1.0
    assert stage_bluff_multiplier(Stage.HEADS_UP) > 1.0


def test_stage_bluff_multiplier_5p_bubble_strong():
    """v7: 5p NEAR_FINAL = 4-handed bubble (3 paid) → 강한 보수 (0.85)."""
    assert stage_bluff_multiplier(Stage.NEAR_FINAL, table_size=5) == 0.85
    # 5p FINAL_TABLE = 3-handed ITM → 0.93
    assert stage_bluff_multiplier(Stage.FINAL_TABLE, table_size=5) == 0.93


def test_stage_bluff_multiplier_6p_chip_priority():
    """v7: 6p NEAR_FINAL = 5-handed pre-bubble → chip 누적 우선 (0.97).

    6p FINAL_TABLE = 4-handed bubble → 약한 보수 (0.93)."""
    assert stage_bluff_multiplier(Stage.NEAR_FINAL, table_size=6) == 0.97
    assert stage_bluff_multiplier(Stage.FINAL_TABLE, table_size=6) == 0.93


def test_stage_bluff_multiplier_default_when_size_none_or_unknown():
    """v7 회귀 보호: table_size None 또는 7+ 는 flat default."""
    default_nf = stage_bluff_multiplier(Stage.NEAR_FINAL)  # None
    assert default_nf == stage_bluff_multiplier(Stage.NEAR_FINAL, table_size=7)
    assert default_nf == stage_bluff_multiplier(Stage.NEAR_FINAL, table_size=9)
    # default 값 자체도 [0.85, 0.97] 사이에 위치 (메타 강건성).
    assert 0.85 < default_nf < 0.97


def test_apply_stage_to_conservatism_uses_table_size():
    """v7: apply_stage_to_conservatism 가 table_size 를 stage_bluff_multiplier 에 전달."""
    cons = compute_profile(None)
    base_bf = cons.bluff_factor
    # 5p NEAR_FINAL → 0.85 곱셈
    new_5p = apply_stage_to_conservatism(cons, Stage.NEAR_FINAL, table_size=5)
    assert abs(new_5p.bluff_factor - max(0.0, min(1.0, base_bf * 0.85))) < 1e-9
    # 6p NEAR_FINAL → 0.97 곱셈 (5p 보다 덜 보수)
    new_6p = apply_stage_to_conservatism(cons, Stage.NEAR_FINAL, table_size=6)
    assert new_6p.bluff_factor > new_5p.bluff_factor


def test_apply_stage_to_conservatism_no_op_for_early_mid():
    cons = compute_profile(None)   # hard_conservative bluff_factor=0.5
    new = apply_stage_to_conservatism(cons, Stage.EARLY)
    assert new is cons   # 변경 없음 → 원본 그대로 (할당 회피).


def test_apply_stage_to_conservatism_tightens_at_final_table():
    cons = compute_profile(None)
    new = apply_stage_to_conservatism(cons, Stage.FINAL_TABLE)
    assert new is not cons
    assert new.bluff_factor < cons.bluff_factor


def test_apply_stage_to_conservatism_loosens_at_heads_up():
    cons = compute_profile(None)   # bluff_factor=0.5
    new = apply_stage_to_conservatism(cons, Stage.HEADS_UP)
    # multiplier 1.15 — 0.5 * 1.15 = 0.575
    assert new.bluff_factor > cons.bluff_factor
    assert new.bluff_factor <= 1.0   # 상한 클램프


# --- P5-2: 5-max 토너먼트 분기 ---

def test_5max_5players_is_mid_not_near_final():
    """5-max 토너먼트의 5명 = 정상 게임 (MID), NEAR_FINAL 아님."""
    assert identify_stage(_req(5), original_table_size=5) == Stage.MID


def test_5max_4players_is_near_final():
    assert identify_stage(_req(4), original_table_size=5) == Stage.NEAR_FINAL


def test_5max_3players_is_final_table():
    assert identify_stage(_req(3), original_table_size=5) == Stage.FINAL_TABLE


def test_5max_2players_is_heads_up():
    assert identify_stage(_req(2), original_table_size=5) == Stage.HEADS_UP


def test_9max_default_when_size_none():
    """original_table_size 미지정 시 9-max 기존 임계 (5명 = NEAR_FINAL)."""
    assert identify_stage(_req(5)) == Stage.NEAR_FINAL


def test_9max_explicit():
    assert identify_stage(_req(5), original_table_size=9) == Stage.NEAR_FINAL
    assert identify_stage(_req(9), original_table_size=9) == Stage.EARLY


# --- P-6max: 6-max 토너먼트 분기 ---

def test_6max_6players_is_mid():
    """6-max 의 6명 = full game (MID)."""
    assert identify_stage(_req(6), original_table_size=6) == Stage.MID


def test_6max_5players_is_near_final():
    """6-max 에서 1명 빠지면 NEAR_FINAL."""
    assert identify_stage(_req(5), original_table_size=6) == Stage.NEAR_FINAL


def test_6max_4players_is_final_table():
    """6-max 에서 2명+ 빠지면 FT."""
    assert identify_stage(_req(4), original_table_size=6) == Stage.FINAL_TABLE
    assert identify_stage(_req(3), original_table_size=6) == Stage.FINAL_TABLE


def test_6max_2players_is_heads_up():
    assert identify_stage(_req(2), original_table_size=6) == Stage.HEADS_UP


def test_4max_3players_is_near_final():
    """4-max 의 3명도 small-table 룰 적용."""
    assert identify_stage(_req(3), original_table_size=4) == Stage.NEAR_FINAL
    assert identify_stage(_req(4), original_table_size=4) == Stage.MID
