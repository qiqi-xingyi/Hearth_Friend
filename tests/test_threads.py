"""Things of his that are not finished.

The most friend-shaped behaviour there is: he mentions on Tuesday something
that will have happened by Thursday, and on Friday she asks how it went.
Nothing else here produces that -- facts about him are standing and never come
due, memories are things that already happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hearth_friend.core.threads import Thread, as_prompt_block, due_now, overdue


def at(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def thread(id: int, what: str, days: float, status: str = "open") -> Thread:
    return Thread(id, what, "面试", at(days), status)


def test_something_still_ahead_is_not_asked_about_yet():
    assert not due_now(at(3))


def test_something_that_has_happened_is_worth_asking_about():
    assert due_now(at(-1))


def test_something_long_past_is_stale_rather_than_pending():
    """Bringing up a fortnight-old interview is not attentive, it is odd."""
    assert not due_now(at(-40))
    assert overdue(at(-40))


def test_she_is_told_to_raise_it_rather_than_wait_to_be_reminded():
    """Written as "if the subject comes up" she waited to be reminded, which is
    the opposite of the behaviour. He not mentioning it does not mean he stopped
    caring; it usually means he did not expect anyone to remember."""
    block = as_prompt_block([thread(1, "他昨天有个面试", -1)])
    assert "主动问一句" in block
    assert "不用等他提起" in block


def test_asking_once_is_the_instruction_not_asking_daily():
    block = as_prompt_block([thread(1, "他昨天有个面试", -1)])
    assert "问过一次就够了" in block


def test_what_is_not_due_is_held_quietly():
    block = as_prompt_block([thread(1, "他下周三有个面试", 3)])
    assert "还没到时候" in block
    assert "不用现在问" in block


def test_the_stale_ones_are_not_put_in_front_of_her_at_all():
    block = as_prompt_block([thread(1, "他上个月说要搬家", -40)])
    assert "搬家" not in block


def test_a_thread_is_marked_asked_and_then_left_alone(store):
    thread_id = store.add_thread("他昨天有个面试", "面试 字节", due_at=at(-1))
    assert [row["id"] for row in store.open_threads()] == [thread_id]

    store.mark_asked([thread_id])
    assert store.open_threads() == [], "asked, and now she waits"


def test_something_asked_about_and_never_answered_is_let_go(store):
    thread_id = store.add_thread("他昨天有个面试", "面试", due_at=at(-1))
    store.mark_asked([thread_id])
    store.conn.execute(
        "UPDATE thread SET asked_at = ? WHERE id = ?", (at(-30), thread_id)
    )

    assert store.drop_stale_threads() == 1
    status = store.conn.execute(
        "SELECT status FROM thread WHERE id = ?", (thread_id,)
    ).fetchone()["status"]
    assert status == "dropped"


def test_the_same_pending_thing_is_not_carried_twice(store):
    store.add_thread("他下周三有个面试", "面试", due_at=at(3))
    assert store.has_thread("他下周三有个面试")
