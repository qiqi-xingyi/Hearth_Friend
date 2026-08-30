from __future__ import annotations

import sqlite3

import pytest

from hearth_friend.store import Store


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    path = tmp_path / "hearth.db"
    first = Store(path)
    assert first.applied_migrations == [1]
    assert first.schema_version == 1
    first.close()

    second = Store(path)
    assert second.applied_migrations == []
    assert second.schema_version == 1
    second.close()


def test_turn_is_append_only(store):
    session_id = store.open_session("local", "cli")
    turn_id = store.append_turn(session_id, "user", "hello")

    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE turn SET content = 'edited' WHERE id = ?", (turn_id,))
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("DELETE FROM turn WHERE id = ?", (turn_id,))

    row = store.conn.execute("SELECT content FROM turn WHERE id = ?", (turn_id,)).fetchone()
    assert row["content"] == "hello"


def test_role_is_constrained(store):
    session_id = store.open_session("local", "cli")
    with pytest.raises(sqlite3.IntegrityError):
        store.append_turn(session_id, "narrator", "nope")


def test_recent_turns_is_oldest_first_and_windowed(store):
    session_id = store.open_session("local", "cli")
    for index in range(5):
        store.append_turn(session_id, "user", f"m{index}")

    window = store.recent_turns("local", 3)
    assert [t.content for t in window] == ["m2", "m3", "m4"]


def test_recent_turns_spans_sessions_but_not_users(store):
    first = store.open_session("local", "cli")
    store.append_turn(first, "user", "before restart")
    store.close_session(first)

    second = store.open_session("local", "cli")
    store.append_turn(second, "user", "after restart")

    other = store.open_session("someone-else", "cli")
    store.append_turn(other, "user", "not mine")

    assert [t.content for t in store.recent_turns("local", 10)] == [
        "before restart",
        "after restart",
    ]


def test_stats_counts_only_the_given_user(store):
    mine = store.open_session("local", "cli")
    store.append_turn(mine, "user", "a")
    theirs = store.open_session("other", "cli")
    store.append_turn(theirs, "user", "b")

    assert store.stats("local")["turns"] == 1
    assert store.stats()["turns"] == 2
