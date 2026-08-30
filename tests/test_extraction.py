"""Folding what she said back into what is true about her.

Seeded facts held, but anything outside the persona file was still invented
fresh: asked about ice cream in four separate sessions she was indifferent,
enthusiastic, undemanding and fussy, the last two contradicting each other.
Without this the persona file is the only real part of her, and it is all
written by someone else.
"""

from __future__ import annotations

from hearth_friend.core import Runtime
from hearth_friend.core.extraction import extract_self_facts
from tests.conftest import StubProvider


def build(store, persona, provider) -> Runtime:
    return Runtime(store, provider, persona, user_id="local", channel="cli")


def test_malformed_entries_are_dropped_rather_than_stored():
    provider = StubProvider(structured={"facts": [
        {"kind": "fact", "cues": "猫", "say": "养了一只猫"},
        {"kind": "nonsense", "cues": "x", "say": "y"},
        {"kind": "view", "cues": "", "say": "no cues"},
        {"kind": "view", "cues": "书", "say": ""},
        "not even a mapping",
    ]})
    assert extract_self_facts(provider, ["said something"], []) == [
        {"kind": "fact", "cues": "猫", "say": "养了一只猫"}
    ]


def test_a_provider_failure_costs_nothing_but_the_extraction():
    provider = StubProvider(fail=True)
    assert extract_self_facts(provider, ["said something"], []) == []


def test_what_she_said_becomes_something_she_can_recall(store, persona):
    provider = StubProvider(
        ["我怕蟑螂", "会直接弹起来", "但蚂蚁还行"],
        structured={"facts": [
            {"kind": "dislike", "cues": "蟑螂 虫子", "say": "怕蟑螂，会直接弹起来"}
        ]},
    )
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("你怕虫子吗")
        list(runtime.reply())
        session_id = runtime.session_id

    assert runtime.extract_session(session_id) == 1
    assert any(
        row["statement"] == "怕蟑螂，会直接弹起来" for row in store.self_facts()
    )
    assert [f.statement for f in runtime.remembered_self("说说蟑螂")] == [
        "怕蟑螂，会直接弹起来"
    ]


def test_the_same_thing_is_not_stored_twice(store, persona):
    provider = StubProvider(
        ["我怕蟑螂 看到会直接弹起来", "但蚂蚁那种反而觉得好看"],
        structured={"facts": [
            {"kind": "dislike", "cues": "蟑螂", "say": "怕蟑螂，会直接弹起来"}
        ]},
    )
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("你怕虫子吗")
        list(runtime.reply())
        session_id = runtime.session_id

    assert runtime.extract_session(session_id) == 1
    store.conn.execute("UPDATE session SET extracted_at = NULL WHERE id = ?", (session_id,))
    assert runtime.extract_session(session_id) == 0


def test_a_session_with_nothing_in_it_is_marked_done_anyway(store, persona):
    """Otherwise it is reconsidered on every launch, forever."""
    provider = StubProvider(["嗯"])
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("在吗")
        list(runtime.reply())
        session_id = runtime.session_id

    assert runtime.extract_session(session_id) == 0
    assert store.unextracted_sessions("local") == []


def test_the_session_still_being_talked_in_is_left_alone(store, persona):
    provider = StubProvider(["something long enough to be worth reading later"])
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("hello")
        list(runtime.reply())
        assert runtime.catch_up_extraction() == 0


def test_a_reply_too_short_to_hold_anything_is_not_worth_a_call(store, persona):
    """A floor, not a filter: a call costs a fraction of a cent, so it is set
    low enough that a single real answer still gets read."""
    provider = StubProvider(["嗯"], structured={"facts": [
        {"kind": "fact", "cues": "x", "say": "should not be reached"}
    ]})
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("在吗")
        list(runtime.reply())
        session_id = runtime.session_id

    assert runtime.extract_session(session_id) == 0
    assert store.self_facts() == []
