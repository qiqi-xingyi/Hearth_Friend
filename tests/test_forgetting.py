"""Forgetting, and drawing conclusions.

Decay rather than deletion: what she can no longer bring to mind is not the same
as what never happened, and the row is the only place that difference lives.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hearth_friend.core.forgetting import (
    effective_strength,
    half_life_hours,
    is_forgotten,
)


def days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_something_that_mattered_lasts_far_longer_than_something_that_did_not():
    """A linear scale gave the most important memory a three-month life. The
    distance between small talk and something that mattered is orders of
    magnitude, not a factor of two."""
    assert half_life_hours(0.9) / half_life_hours(0.1) > 50


def test_small_talk_is_gone_within_a_month():
    assert is_forgotten(0.15, 0.15, 30 * 24)


def test_what_mattered_survives_a_year():
    assert not is_forgotten(0.9, 0.9, 365 * 24)
    assert effective_strength(0.9, 0.9, 365 * 24) > 0.3


def test_nothing_fades_before_any_time_has_passed():
    assert effective_strength(0.5, 0.5, 0) == 0.5


def test_time_passing_moves_things_out_of_reach_without_deleting_them(store):
    memory_id = store.add_memory("他今天吃了面", "面", importance=0.15)
    store.conn.execute(
        "UPDATE memory SET created_at = ? WHERE id = ?", (days_ago(60), memory_id)
    )

    gone, back = store.forget_pass()
    assert gone == 1
    row = store.conn.execute(
        "SELECT status, content FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()
    assert row["status"] == "forgotten"
    assert row["content"] == "他今天吃了面", "the row stays"


def test_a_direct_enough_cue_brings_something_back(store):
    """People do this. Something not thought about in years surfaces whole when
    the right thing is said."""
    memory_id = store.add_memory("他提过那家面馆", "面馆", importance=0.15)
    store.conn.execute(
        "UPDATE memory SET created_at = ? WHERE id = ?", (days_ago(60), memory_id)
    )
    store.forget_pass()

    assert store.forgotten_matching(["面馆"]) == [memory_id]
    assert store.revive_memories([memory_id]) == 1
    assert store.conn.execute(
        "SELECT status FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()["status"] == "active"


def test_a_forgotten_memory_is_out_of_the_ordinary_candidate_pool(store):
    memory_id = store.add_memory("很久以前的小事", "小事", importance=0.15)
    store.conn.execute(
        "UPDATE memory SET created_at = ? WHERE id = ?", (days_ago(60), memory_id)
    )
    store.forget_pass()
    assert store.memory_candidates(["小事"]) == []


# --- drawing conclusions ----------------------------------------------------


def test_one_occasion_is_an_event_and_three_is_the_start_of_a_claim(store):
    for index in range(2):
        store.add_memory(f"他第 {index} 次说在忙", "忙", importance=0.4)
    assert store.recurring_cues(minimum=3) == []

    store.add_memory("他又说在忙", "忙", importance=0.4)
    assert [cue for cue, _ in store.recurring_cues(minimum=3)] == ["忙"]


def test_a_conclusion_is_kept_with_what_it_was_drawn_from(store):
    """Attribution is where being wrong stops being annoying. A conclusion you
    cannot see the evidence for is one you cannot correct."""
    ids = [store.add_memory(f"第 {i} 次", "忙", importance=0.4) for i in range(3)]
    store.add_about_you(
        "pattern", "忙", "他最近好像一直很忙", source_memory_ids=ids
    )

    import json

    drawn = store.patterns()
    assert len(drawn) == 1
    assert json.loads(drawn[0]["source_json"]) == ids
    assert {m["id"] for m in store.memories_by_id(ids)} == set(ids)


def test_the_same_evidence_is_not_concluded_from_twice(store, persona):
    from hearth_friend.core import Runtime
    from tests.conftest import StubProvider

    provider = StubProvider(structured={"pattern": "他最近好像一直很忙"})
    runtime = Runtime(store, provider, persona, user_id="local", channel="cli")
    for index in range(3):
        store.add_memory(f"他第 {index} 次说在忙", "忙", importance=0.4)

    assert runtime.generalise() == "他最近好像一直很忙"
    assert runtime.generalise() is None, "the same three occasions are spent"
