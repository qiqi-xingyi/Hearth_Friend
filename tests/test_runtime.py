"""Runtime behaviour.

Assertions use English text so they stay readable, with one section covering
Chinese explicitly: the product is used in Chinese, so encoding, streaming and
storage need to be exercised against it rather than assumed.
"""

from __future__ import annotations

import json

import pytest

from hearth_friend.core import Runtime
from hearth_friend.providers.base import ProviderError
from hearth_friend.store import Store
from tests.conftest import StubProvider


def build(store, persona, provider, **kwargs) -> Runtime:
    return Runtime(store, provider, persona, user_id="local", channel="cli", **kwargs)


def test_reply_is_streamed_and_both_turns_persisted(store, persona):
    runtime = build(store, persona, StubProvider(["he", "llo"]))
    with runtime:
        assert "".join(runtime.respond("are you there")) == "hello"

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "are you there"),
        ("assistant", "hello"),
    ]


def test_user_turn_survives_a_provider_failure(store, persona):
    runtime = build(store, persona, StubProvider(["x"], fail_after=0))
    with runtime:
        with pytest.raises(ProviderError):
            list(runtime.respond("this must not be lost"))

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [("user", "this must not be lost")]


def test_partial_reply_is_kept_when_the_provider_dies_midway(store, persona):
    runtime = build(store, persona, StubProvider(["half ", "a sentence"], fail_after=1))
    with runtime:
        with pytest.raises(ProviderError):
            list(runtime.respond("say something"))

    row = store.conn.execute(
        "SELECT content, meta_json FROM turn WHERE role = 'assistant'"
    ).fetchone()
    assert row["content"] == "half "
    assert json.loads(row["meta_json"])["truncated"] is True


def test_partial_reply_is_kept_when_the_reader_stops(store, persona):
    runtime = build(store, persona, StubProvider(["one", "two", "three"]))
    with runtime:
        stream = runtime.respond("count to three")
        assert next(stream) == "one"
        stream.close()

    row = store.conn.execute(
        "SELECT content, meta_json FROM turn WHERE role = 'assistant'"
    ).fetchone()
    assert row["content"] == "one"
    assert json.loads(row["meta_json"])["interrupted"] is True


def test_context_is_persona_plus_history(store, persona):
    provider = StubProvider(["ok"])
    runtime = build(store, persona, provider)
    with runtime:
        list(runtime.respond("first"))
        list(runtime.respond("second"))

    messages = provider.calls[-1]
    assert messages[0]["role"] == "system"
    assert persona.name in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["first", "ok", "second"]


def test_conversation_resumes_after_restart(tmp_path, persona):
    path = tmp_path / "hearth.db"

    first_store = Store(path)
    with build(first_store, persona, StubProvider(["noted"])) as runtime:
        list(runtime.respond("I have an interview next week"))
    first_store.close()

    # A new process: new store, new runtime, nothing carried in memory.
    second_store = Store(path)
    provider = StubProvider(["mm"])
    with build(second_store, persona, provider) as runtime:
        list(runtime.respond("do you remember"))
    second_store.close()

    assert [m["content"] for m in provider.calls[-1][1:]] == [
        "I have an interview next week",
        "noted",
        "do you remember",
    ]


def test_context_window_is_respected(store, persona):
    provider = StubProvider(["ok"])
    runtime = build(store, persona, provider, context_turns=3)
    with runtime:
        for index in range(4):
            list(runtime.respond(f"m{index}"))

    history = provider.calls[-1][1:]
    assert len(history) == 3
    assert history[-1]["content"] == "m3"


# --- Chinese, which is what this is actually used in ------------------------


def test_chinese_survives_streaming_and_storage(store, chinese_persona):
    """Multi-byte text must reassemble from chunks and store byte-identical."""
    reply = ["我下周", "也有面试", "，一起紧张"]
    runtime = build(store, chinese_persona, StubProvider(reply))
    with runtime:
        assert "".join(runtime.respond("我下周三面试")) == "".join(reply)

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "我下周三面试"),
        ("assistant", "我下周也有面试，一起紧张"),
    ]


def test_chinese_context_and_persona_reach_the_model(store, chinese_persona):
    provider = StubProvider(["嗯"])
    runtime = build(store, chinese_persona, provider)
    with runtime:
        list(runtime.respond("在吗"))
        list(runtime.respond("还记得吗"))

    system, *history = provider.calls[-1]
    assert "二十六岁，住在杭州" in system["content"]
    assert [m["content"] for m in history] == ["在吗", "嗯", "还记得吗"]
