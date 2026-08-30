from __future__ import annotations

import sqlite3

import pytest

from hearth_friend.store import Store


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    """Deliberately not pinned to a version: migrations will keep arriving, and
    a test that has to be edited every time one lands stops being a check."""
    path = tmp_path / "hearth.db"
    first = Store(path)
    assert first.applied_migrations, "no migrations were applied"
    version = first.schema_version
    assert version == max(first.applied_migrations)
    first.close()

    second = Store(path)
    assert second.applied_migrations == []
    assert second.schema_version == version
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


def test_backup_is_complete_on_its_own(tmp_path):
    """Copying the database file is not a backup: in WAL mode the recent writes
    are in a side file, and `cp hearth.db` can silently produce an empty
    database. This is the check that the supported path does not."""
    store = Store(tmp_path / "live.db")
    session_id = store.open_session("local", "cli")
    for index in range(20):
        store.append_turn(session_id, "user", f"message {index}")

    destination = store.backup(tmp_path / "out" / "copy.db")
    store.close()

    # Deliberately no -wal or -shm alongside it: the one file must be enough.
    assert not (tmp_path / "out" / "copy.db-wal").exists()
    restored = Store(destination)
    assert restored.stats()["turns"] == 20
    restored.close()


def test_a_plain_file_copy_after_a_clean_close_is_also_complete(tmp_path):
    import shutil

    store = Store(tmp_path / "live.db")
    session_id = store.open_session("local", "cli")
    store.append_turn(session_id, "user", "hello")
    store.close()  # checkpoints the WAL back into the main file

    shutil.copyfile(tmp_path / "live.db", tmp_path / "copied.db")
    copied = Store(tmp_path / "copied.db")
    assert copied.stats()["turns"] == 1
    copied.close()


def test_turns_from_before_the_column_existed_are_not_treated_as_unanswered(tmp_path):
    """The column recording how far she had read was added late, and the turn
    log cannot be rewritten, so older rows carry NULL. Read naively, the first
    launch after that migration finds the whole history unanswered and she opens
    by replying to a week-old conversation."""
    store = Store(tmp_path / "hearth.db")
    session_id = store.open_session("local", "cli")

    # A conversation from before the column: strictly alternating, no record.
    store.append_turn(session_id, "user", "old question")
    store.append_turn(session_id, "assistant", "old answer")  # answers_through NULL

    assert store.unanswered_turns("local", 40) == []

    store.append_turn(session_id, "user", "something new")
    assert [t.content for t in store.unanswered_turns("local", 40)] == ["something new"]
    store.close()
