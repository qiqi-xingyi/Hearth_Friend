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


def test_the_turn_block_renders_a_decision_rather_than_a_mood(persona):
    """It used to threshold her mood: engagement under 0.25 meant short. Those
    thresholds were the personality, written as constants in the middle of a
    prompt builder. The block now renders a decision that was made with weights."""
    from hearth_friend.core.deciding import Decision
    from hearth_friend.core.prompt import state_note

    def note(**kwargs):
        base = dict(
            speak=True, length=0.5, ask=False, disclose=False,
            push_back=False, temperature=0.8, scores={},
        )
        return state_note(Decision(**{**base, **kwargs}), None, persona)

    assert "别反问" in note(ask=False)
    assert "可以问一句" in note(ask=True)
    assert "不用讲自己" in note(disclose=False)
    assert "可以说点你自己的事" in note(disclose=True)
    assert "直接说出来" in note(push_back=True)


def test_a_longer_decision_asks_for_more_words(persona):
    from hearth_friend.core.deciding import Decision
    from hearth_friend.core.prompt import state_note

    def target(length):
        base = dict(
            speak=True, ask=False, disclose=False, push_back=False,
            temperature=0.8, scores={},
        )
        text = state_note(Decision(length=length, **base), None, persona)
        return int(text.split("大概 ")[1].split(" 字")[0])

    assert target(0.9) > target(0.1)


def test_she_is_never_handed_words_for_how_she_feels(persona):
    """An earlier version described her mood in the prompt and she read it out
    loud. The block carries instructions, not something to recite."""
    from hearth_friend.core.deciding import Decision
    from hearth_friend.core.prompt import state_note

    note = state_note(
        Decision(True, 0.1, False, False, False, 1.6, {}), None, persona
    )
    assert "心情不太好" not in note
    assert "没太进入状态" in note


def test_the_context_is_bounded_by_size_not_only_by_count(store, persona):
    """Forty one-word turns and forty pasted documents are the same count and
    very different prompts."""
    provider = StubProvider(["ok"])
    runtime = build(store, persona, provider, context_turns=40, context_chars=500)
    with runtime:
        for index in range(12):
            runtime.ingest("x" * 200 + str(index))
        list(runtime.reply())

    history = "".join(spoken(provider.calls[-1]))
    assert len(history) <= 800, "the window has to hold"
    assert "11" in history, "and what survives is the most recent"


def test_a_decision_not_to_ask_is_enforced_and_not_merely_requested(persona):
    """Told not to ask anything this turn, it asked anyway. A decision the thing
    downstream may decline is a suggestion, and the point of moving the choosing
    out of the model is that the choosing is not the model's."""
    from hearth_friend.core.deciding import Decision
    from hearth_friend.core.prompt import enforce

    said = ["那就先放着吧", "不急着赶", "论文卡在哪了？"]
    quiet = Decision(True, 0.5, False, False, False, 0.8, {})
    curious = Decision(True, 0.5, True, False, False, 0.8, {})

    assert enforce(said, quiet) == ["那就先放着吧", "不急着赶"]
    assert enforce(said, curious) == said


def test_enforcement_does_not_cut_into_what_she_actually_said(persona):
    from hearth_friend.core.deciding import Decision
    from hearth_friend.core.prompt import enforce

    said = ["卡住的时候硬写也没用，我以前也这样，后来发现放一放反而顺了？"]
    quiet = Decision(True, 0.5, False, False, False, 0.8, {})
    assert enforce(said, quiet) == said, "a single message is never dropped"
