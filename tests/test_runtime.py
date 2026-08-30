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


def spoken(messages) -> list[str]:
    """Just the conversation. The system blocks around it are asserted
    separately, so these tests do not break every time one is added."""
    return [m["content"] for m in messages if m["role"] != "system"]


def test_a_reply_is_a_run_of_messages_not_one_block(store, persona):
    """How someone breaks up what they say is part of who they are, so a reply
    is several messages and each is recorded as its own turn."""
    runtime = build(store, persona, StubProvider(["hey", "just got in", "you up?"]))
    with runtime:
        assert list(runtime.respond("are you there")) == ["hey", "just got in", "you up?"]

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "are you there"),
        ("assistant", "hey"),
        ("assistant", "just got in"),
        ("assistant", "you up?"),
    ]


def test_user_turn_survives_a_provider_failure(store, persona):
    runtime = build(store, persona, StubProvider(["x"], fail=True))
    with runtime:
        with pytest.raises(ProviderError):
            list(runtime.respond("this must not be lost"))

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [("user", "this must not be lost")]


def test_messages_already_sent_are_kept_when_the_reader_stops(store, persona):
    """She sends a run of messages with pauses between them. If the reader walks
    away halfway through, what was already sent still happened."""
    runtime = build(store, persona, StubProvider(["one", "two", "three"]))
    with runtime:
        stream = runtime.reply.__self__.respond("say three things")
        assert next(stream) == "one"
        assert next(stream) == "two"
        stream.close()

    sent = [
        r["content"]
        for r in store.conn.execute(
            "SELECT content FROM turn WHERE role = 'assistant' ORDER BY id"
        )
    ]
    assert sent == ["one", "two"]


def test_context_is_persona_plus_history(store, persona):
    provider = StubProvider(["ok"])
    runtime = build(store, persona, provider)
    with runtime:
        list(runtime.respond("first"))
        list(runtime.respond("second"))

    messages = provider.calls[-1]
    assert messages[0]["role"] == "system"
    assert persona.name in messages[0]["content"]
    assert spoken(messages) == ["first", "ok", "second"]


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

    assert spoken(provider.calls[-1]) == [
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

    history = spoken(provider.calls[-1])
    assert len(history) == 3
    assert history[-1] == "m3"


# --- Chinese, which is what this is actually used in ------------------------


def test_chinese_survives_splitting_and_storage(store, chinese_persona):
    """Multi-byte text must come back byte-identical after being split into
    messages and written to the database."""
    said = ["我下周也有面试", "一起紧张吧", "别熬太晚"]
    runtime = build(store, chinese_persona, StubProvider(said))
    with runtime:
        assert list(runtime.respond("我下周三面试")) == said

    rows = store.conn.execute("SELECT role, content FROM turn ORDER BY id").fetchall()
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "我下周三面试"),
        *[("assistant", m) for m in said],
    ]


def test_chinese_context_and_persona_reach_the_model(store, chinese_persona):
    provider = StubProvider(["嗯"])
    runtime = build(store, chinese_persona, provider)
    with runtime:
        list(runtime.respond("在吗"))
        list(runtime.respond("还记得吗"))

    messages = provider.calls[-1]
    assert "二十六岁，住在杭州" in messages[0]["content"]
    assert spoken(messages) == ["在吗", "嗯", "还记得吗"]


# --- her interior -----------------------------------------------------------


def test_how_she_is_goes_last_not_into_the_system_prompt(store, persona):
    """Placed after the history so the cacheable prefix stays intact, and so a
    persona stated only at the top does not fade over a long conversation."""
    provider = StubProvider(["ok"])
    with build(store, persona, provider) as runtime:
        list(runtime.respond("hello"))

    messages = provider.calls[-1]
    assert messages[-1]["role"] == "system"
    assert "这一轮怎么说" in messages[-1]["content"]
    assert "这一轮怎么说" not in messages[0]["content"]


def test_state_persists_across_a_restart(tmp_path, persona):
    path = tmp_path / "hearth.db"
    first = Store(path)
    with build(first, persona, StubProvider(["ok"])) as runtime:
        list(runtime.respond("hello"))
        engagement = runtime.current_state().engagement
    first.close()

    second = Store(path)
    with build(second, persona, StubProvider(["ok"])) as runtime:
        # Some decay is expected; what must not happen is starting from nothing.
        assert runtime.current_state().engagement == pytest.approx(engagement, abs=0.05)
    second.close()


def test_a_flat_mood_and_a_lively_one_produce_different_instructions(store, persona):
    from hearth_friend.core.prompt import state_note
    from hearth_friend.core.state import State

    withdrawn = State(engagement=0.05, energy=0.2, mood_valence=-0.6)
    engaged = State(engagement=0.9, energy=0.9, mood_valence=0.5)

    assert state_note(withdrawn, None, persona) != state_note(engaged, None, persona)
    assert "没太投入" in state_note(withdrawn, None, persona)
    assert "真的有兴趣" in state_note(engaged, None, persona)


def test_she_is_never_handed_words_for_how_she_feels(persona):
    """An earlier version described her mood in the prompt and she read it out
    loud. The block gives instructions now, not something to recite."""
    from hearth_friend.core.prompt import state_note
    from hearth_friend.core.state import State

    note = state_note(State(mood_valence=-0.8, energy=0.2, engagement=0.05), None, persona)
    assert "心情不太好" not in note
    assert "不用为了对方强撑着轻松" in note


# --- a shared timeline rather than question and answer ----------------------


def test_a_burst_gets_one_reply_covering_all_of_it(store, persona):
    """You can keep talking without waiting. Three lines in a row are one thing
    you were saying, and get one answer, not three."""
    provider = StubProvider(["got it"])
    with build(store, persona, provider) as runtime:
        runtime.ingest("hey")
        runtime.ingest("so the thing happened today")
        runtime.ingest("and I still don't know what to do about it")
        assert list(runtime.reply()) == ["got it"]

    assert spoken(provider.calls[-1]) == [
        "hey",
        "so the thing happened today",
        "and I still don't know what to do about it",
    ]


def test_unanswered_is_everything_since_she_last_spoke(store, persona):
    with build(store, persona, StubProvider(["ok"])) as runtime:
        runtime.ingest("one")
        runtime.ingest("two")
        assert [t.content for t in runtime.unanswered()] == ["one", "two"]

        list(runtime.reply())
        assert runtime.unanswered() == []

        runtime.ingest("three")
        assert [t.content for t in runtime.unanswered()] == ["three"]


def test_replying_with_nothing_pending_says_nothing(store, persona):
    provider = StubProvider(["ok"])
    with build(store, persona, provider) as runtime:
        assert list(runtime.reply()) == []
    assert provider.calls == []


def test_the_store_takes_writes_from_more_than_one_thread(tmp_path):
    """She answers on a different thread from the one reading you in, so both
    have to be able to write."""
    import threading

    store = Store(tmp_path / "hearth.db")
    session_id = store.open_session("local", "cli")
    errors: list[Exception] = []

    def write(tag: str) -> None:
        try:
            for index in range(25):
                store.append_turn(session_id, "user", f"{tag}{index}")
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(t,)) for t in ("a", "b", "c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.stats()["turns"] == 75
    store.close()


def test_you_can_keep_talking_while_she_is_composing(store, persona):
    """The whole point of the split between ingest and reply. If sending a
    message blocked until she answered, there would be no way to say two things
    in a row, which is most of what talking to someone is."""
    import threading
    import time as _time

    class SlowProvider(StubProvider):
        def generate(self, messages, *, temperature=None):
            _time.sleep(0.4)
            return super().generate(messages, temperature=temperature)

    provider = SlowProvider(["thinking about it"])
    with build(store, persona, provider) as runtime:
        runtime.ingest("here is the first thing")

        said: list[str] = []
        thread = threading.Thread(target=lambda: said.extend(runtime.reply()))
        thread.start()

        _time.sleep(0.1)  # she is mid-call
        started = _time.monotonic()
        runtime.ingest("and another thing")
        assert _time.monotonic() - started < 0.2, "sending blocked on her reply"

        thread.join(timeout=5)
        assert said == ["thinking about it"]
        # What arrived mid-reply is still owed an answer.
        assert [t.content for t in runtime.unanswered()] == ["and another thing"]
