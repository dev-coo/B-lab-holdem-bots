from __future__ import annotations

from pathlib import Path

import pytest

from holdem.persist.db import (
    connect,
    load_profile,
    load_store,
    save_profile,
    save_store,
)
from holdem.state.player_profile import PlayerProfile
from holdem.state.profile_store import ProfileStore


@pytest.fixture
def db_path(tmp_path: Path):
    return tmp_path / "test.db"


def test_save_and_load_single_profile(db_path):
    conn = connect(db_path)
    prof = PlayerProfile(name="villain", hands_seen=25)
    prof.get("VPIP").alpha = 6
    prof.get("VPIP").beta = 19
    prof.aggression.aggressive = 5
    prof.aggression.passive = 3

    save_profile(conn, prof)
    loaded = load_profile(conn, "villain")

    assert loaded is not None
    assert loaded.name == "villain"
    assert loaded.hands_seen == 25
    assert loaded.get("VPIP").alpha == 6.0
    assert loaded.get("VPIP").beta == 19.0
    assert loaded.aggression.aggressive == 5.0
    assert loaded.aggression.passive == 3.0


def test_load_missing_returns_none(db_path):
    conn = connect(db_path)
    assert load_profile(conn, "nobody") is None


def test_save_and_load_store(db_path):
    conn = connect(db_path)
    store = ProfileStore()
    a = store.get("A")
    a.hands_seen = 10
    a.get("PFR").alpha = 3
    a.get("PFR").beta = 7
    b = store.get("B")
    b.hands_seen = 15

    n = save_store(conn, store)
    assert n == 2

    loaded = load_store(conn)
    assert set(loaded.profiles) == {"A", "B"}
    assert loaded.get("A").get("PFR").rate(default=0) == 0.3
    assert loaded.get("B").hands_seen == 15


def test_upsert_on_second_save(db_path):
    conn = connect(db_path)
    prof = PlayerProfile(name="x", hands_seen=5)
    prof.get("VPIP").alpha = 1
    save_profile(conn, prof)

    # 값 수정 후 재저장
    prof.hands_seen = 8
    prof.get("VPIP").alpha = 3
    save_profile(conn, prof)

    loaded = load_profile(conn, "x")
    assert loaded is not None
    assert loaded.hands_seen == 8
    assert loaded.get("VPIP").alpha == 3.0


def test_metrics_json_survives_all_keys(db_path):
    conn = connect(db_path)
    prof = PlayerProfile(name="all", hands_seen=100)
    for i, key in enumerate(("VPIP", "PFR", "CBET", "FOLD_TO_CBET", "CHECK_RAISE")):
        prof.get(key).alpha = float(i + 1)
        prof.get(key).beta = 1.0

    save_profile(conn, prof)
    loaded = load_profile(conn, "all")
    assert loaded is not None
    for i, key in enumerate(("VPIP", "PFR", "CBET", "FOLD_TO_CBET", "CHECK_RAISE")):
        assert loaded.get(key).alpha == float(i + 1)
        assert loaded.get(key).beta == 1.0
