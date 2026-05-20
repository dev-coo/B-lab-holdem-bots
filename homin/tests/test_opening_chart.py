from __future__ import annotations

from holdem.decide.opening_chart import OpeningChart, default_opening_chart


def test_loads_from_yaml():
    chart = default_opening_chart()
    assert "EP" in chart.ranges
    assert "LP" in chart.ranges


def test_AA_in_all_positions():
    chart = default_opening_chart()
    for pos in ("EP", "MP", "LP", "BLIND"):
        assert chart.in_rfi_range("AA", pos), f"AA missing from {pos}"


def test_EP_tight_excludes_weak_hands():
    chart = default_opening_chart()
    # EP 는 77+ 이므로 22 는 제외
    assert not chart.in_rfi_range("22", "EP")
    # 그러나 LP 는 22+ 포함
    assert chart.in_rfi_range("22", "LP")


def test_72o_not_in_any():
    chart = default_opening_chart()
    for pos in ("EP", "MP", "LP", "BLIND"):
        assert not chart.in_rfi_range("72o", pos)


def test_rfi_size_bb_varies():
    chart = default_opening_chart()
    assert chart.rfi_size_bb("EP") == 3.0
    assert chart.rfi_size_bb("LP") == 2.5
    assert chart.rfi_size_bb("unknown", default=2.5) == 2.5


# --- P-Adapt2: loose_meta_ranges ---

def test_loose_meta_lp_wider_than_default():
    """LP loose meta range 가 기본보다 넓음 — 87s, 75s 같은 핸드 추가 포함."""
    chart = default_opening_chart()
    # 기본 LP 에는 75s 가 없음.
    assert not chart.in_rfi_range("75s", "LP")
    # loose meta 에는 75s 포함.
    assert chart.in_rfi_range("75s", "LP", meta_loose=True)


def test_loose_meta_ep_unchanged():
    """EP 는 reverse-implied odds 위험으로 loose meta 에서도 그대로."""
    chart = default_opening_chart()
    # 22 는 EP 기본 chart 에 없음.
    assert not chart.in_rfi_range("22", "EP")
    # loose meta 에서도 EP 는 보수 → 22 여전히 제외.
    assert not chart.in_rfi_range("22", "EP", meta_loose=True)


def test_loose_meta_default_off():
    """meta_loose 인자 누락 시 기본 chart 사용 (기존 동작 보존)."""
    chart = default_opening_chart()
    assert chart.in_rfi_range("75s", "LP") is False
    assert chart.in_rfi_range("75s", "LP", meta_loose=False) is False


# --- P5-1: 5-max 분기 ---

def test_5max_lp_wider_than_9max():
    """5-max BTN (LP) 은 9-max BTN/CO (LP) 보다 wider — 53s 같은 핸드 추가 포함."""
    chart = default_opening_chart()
    # 9-max LP 에는 53s 없음.
    assert not chart.in_rfi_range("53s", "LP")
    assert not chart.in_rfi_range("53s", "LP", n_players=9)
    # 5-max LP (BTN) 에는 53s 포함.
    assert chart.in_rfi_range("53s", "LP", n_players=5)
    assert chart.in_rfi_range("53s", "LP", n_players=4)


def test_5max_mp_is_5max_co_range():
    """5-max CO 는 MP 로 분류 — 5-max MP range 가 9-max MP 보다 wider."""
    chart = default_opening_chart()
    # 76s 는 9-max MP 없음, 5-max MP 포함.
    assert not chart.in_rfi_range("76s", "MP", n_players=9)
    assert chart.in_rfi_range("76s", "MP", n_players=5)


def test_5max_default_n_players_is_9max():
    """n_players 미지정 시 9-max chart 사용 (호환)."""
    chart = default_opening_chart()
    # 5-max LP 에 53s 있지만 n_players None 이면 9-max → 없음.
    assert not chart.in_rfi_range("53s", "LP")


def test_5max_loose_meta_lp_widest():
    """5-max LP loose meta 는 가장 wide — 32s 같은 핸드까지 포함."""
    chart = default_opening_chart()
    # 5-max LP 일반: 32s 없음.
    assert not chart.in_rfi_range("32s", "LP", n_players=5)
    # 5-max LP loose meta: 32s 포함.
    assert chart.in_rfi_range("32s", "LP", n_players=5, meta_loose=True)


def test_6max_uses_6max_chart_distinct_from_5max():
    """v5-A: 6-max 는 5-max 보다 약간 tight, 9-max 보다는 wider."""
    chart = default_opening_chart()
    # 53s 는 5-max LP 에 있지만 6-max LP 에는 없음 (5-max ~60% / 6-max ~50% 차이).
    assert chart.in_rfi_range("53s", "LP", n_players=5)
    assert not chart.in_rfi_range("53s", "LP", n_players=6)
    # 75s 는 6-max LP 에 있고 9-max LP 에 없음 (6-max wider than 9-max).
    assert chart.in_rfi_range("75s", "LP", n_players=6)
    assert not chart.in_rfi_range("75s", "LP", n_players=9)


def test_5max_still_uses_5max_chart():
    """v5-A 회귀 보호: 5-max 동작 변화 없음."""
    chart = default_opening_chart()
    assert chart.in_rfi_range("53s", "LP", n_players=5)
    assert chart.in_rfi_range("76s", "MP", n_players=5)


def test_6max_loose_meta_wider_than_6max_baseline():
    """v5-A: meta_loose=True + n_players=6 → loose_meta_ranges_6max."""
    chart = default_opening_chart()
    # 53s 는 6-max LP baseline 에 없지만 6-max loose meta 에 있음.
    assert not chart.in_rfi_range("53s", "LP", n_players=6)
    assert chart.in_rfi_range("53s", "LP", n_players=6, meta_loose=True)


def test_9max_unaffected_by_6max_branch():
    """v5-A 회귀 보호: 7+ 명은 여전히 9-max chart."""
    chart = default_opening_chart()
    # 9-max EP 의 77+ 만 (55 없음).
    assert chart.in_rfi_range("77", "EP", n_players=9)
    assert not chart.in_rfi_range("55", "EP", n_players=9)
    # 6-max EP 에는 55 있음 (분기 정확).
    assert chart.in_rfi_range("55", "EP", n_players=6)
