from __future__ import annotations

import json

import pytest

from hearth_friend.core import Runtime
from hearth_friend.providers.base import ProviderError
from hearth_friend.store import Store
from tests.conftest import StubProvider


def build(store, persona, provider, **kwargs) -> Runtime:
    return Runtime(
        store, provider, persona, user_id="local", channel="cli", **kwargs
    )


def test_reply_is_streamed_and_both_turns_persisted(store, persona):
    runtime = build(store, persona, StubProvider(["你", "好"]))
    with runtime:
        assert "".join(runtime.respond("在吗")) == "你好"

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "在吗"),
        ("assistant", "你好"),
    ]


def test_user_turn_survives_a_provider_failure(store, persona):
    runtime = build(store, persona, StubProvider(["x"], fail_after=0))
    with runtime:
        with pytest.raises(ProviderError):
            list(runtime.respond("这句话不能丢"))

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [("user", "这句话不能丢")]


def test_partial_reply_is_kept_when_the_provider_dies_midway(store, persona):
    runtime = build(store, persona, StubProvider(["半", "句"], fail_after=1))
    with runtime:
        with pytest.raises(ProviderError):
            list(runtime.respond("说点什么"))

    row = store.conn.execute(
        "SELECT content, meta_json FROM turn WHERE role = 'assistant'"
    ).fetchone()
    assert row["content"] == "半"
    assert json.loads(row["meta_json"])["truncated"] is True


def test_partial_reply_is_kept_when_the_reader_stops(store, persona):
    runtime = build(store, persona, StubProvider(["一", "二", "三"]))
    with runtime:
        stream = runtime.respond("说三个字")
        assert next(stream) == "一"
        stream.close()

    row = store.conn.execute(
        "SELECT content, meta_json FROM turn WHERE role = 'assistant'"
    ).fetchone()
    assert row["content"] == "一"
    assert json.loads(row["meta_json"])["interrupted"] is True


def test_context_is_persona_plus_history(store, persona):
    provider = StubProvider(["ok"])
    runtime = build(store, persona, provider)
    with runtime:
        list(runtime.respond("第一句"))
        list(runtime.respond("第二句"))

    messages = provider.calls[-1]
    assert messages[0]["role"] == "system"
    assert persona.name in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["第一句", "ok", "第二句"]


def test_conversation_resumes_after_restart(tmp_path, persona):
    path = tmp_path / "hearth.db"

    first_store = Store(path)
    with build(first_store, persona, StubProvider(["记住了"])) as runtime:
        list(runtime.respond("我下周面试"))
    first_store.close()

    # A new process: new store, new runtime, nothing carried in memory.
    second_store = Store(path)
    provider = StubProvider(["嗯"])
    with build(second_store, persona, provider) as runtime:
        list(runtime.respond("还记得吗"))
    second_store.close()

    assert [m["content"] for m in provider.calls[-1][1:]] == [
        "我下周面试",
        "记住了",
        "还记得吗",
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
