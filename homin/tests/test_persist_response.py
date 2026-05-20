from __future__ import annotations

from pathlib import Path

import pytest

from holdem.estimate.bayes import DirichletResponse
from holdem.persist.db import (
    connect,
    load_response_store,
    load_store,
    save_response_store,
    save_store,
)
from holdem.state.profile_store import ProfileStore
from holdem.transport.protocol import HistoryEntry


@pytest.fixture
def db_path(tmp_path: Path):
    return tmp_path / "rs.db"


def test_roundtrip_response_store(db_path):
    conn = connect(db_path)
    rs = ProfileStore().responses
    rs.table[("A", "preflop")] = DirichletResponse(alpha_fold=5, alpha_call=3, alpha_raise=2)
    rs.table[("B", "flop")] = DirichletResponse(alpha_fold=1, alpha_call=8, alpha_raise=1)
    n = save_response_store(conn, rs)
    assert n == 2

    loaded = load_response_store(conn)
    a = loaded.lookup("A", "preflop")
    assert a.alpha_fold == 5.0
    assert a.alpha_call == 3.0
    assert a.alpha_raise == 2.0
    b = loaded.lookup("B", "flop")
    assert b.alpha_call == 8.0


def test_profile_store_save_includes_responses(db_path):
    conn = connect(db_path)
    store = ProfileStore()
    store.get("villain").hands_seen = 10
    store.responses.observe_from_hand([
        HistoryEntry(phase="flop", player="villain", action="raise", amount=4),
        HistoryEntry(phase="flop", player="villain", action="raise", amount=8),
    ])
    save_store(conn, store)

    loaded = load_store(conn)
    assert loaded.get("villain").hands_seen == 10
    r = loaded.responses.lookup("villain", "flop")
    # baseline 1 + 2 raise obs = 3
    assert r.alpha_raise == 3.0


def test_response_upsert_overwrites(db_path):
    conn = connect(db_path)
    rs = ProfileStore().responses
    rs.table[("X", "turn")] = DirichletResponse(alpha_fold=1, alpha_call=1, alpha_raise=1)
    save_response_store(conn, rs)

    rs.table[("X", "turn")] = DirichletResponse(alpha_fold=10, alpha_call=2, alpha_raise=5)
    save_response_store(conn, rs)

    loaded = load_response_store(conn)
    x = loaded.lookup("X", "turn")
    assert x.alpha_fold == 10.0
    assert x.alpha_call == 2.0
    assert x.alpha_raise == 5.0


def test_load_empty_returns_empty_store(db_path):
    conn = connect(db_path)
    loaded = load_response_store(conn)
    # 관측 없는 상태는 default 1,1,1 로 랜덤 접근해도 문제 없음
    r = loaded.lookup("nobody", "preflop")
    assert r.alpha_fold == 1.0
