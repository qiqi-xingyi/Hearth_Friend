"""Things she wants to understand.

A person does not search mid-conversation; they get curious about a topic and
read about it later, and what they carry away is the topic rather than what you
said. That abstraction is what curiosity is, and it happens to mean almost
nothing private can ride out on a query -- which is why this can be autonomous
instead of something approved one question at a time.
"""

from __future__ import annotations

from hearth_friend.core import Runtime
from hearth_friend.core.curiosity import as_prompt_block, check
from hearth_friend.core.extraction import extract_curiosity
from tests.conftest import StubProvider

PRIVATE = [
    "今天面试搞砸了",
    "字节的量子计算组",
    "我住在滨江区",
]


def test_a_question_about_the_world_is_allowed():
    assert check("量子计算为什么难", PRIVATE) is None
    assert check("为什么有人熬夜效率反而高", PRIVATE) is None


def test_a_question_about_the_person_is_not():
    """A friend who wants to know something about you asks you. Looking you up
    behind your back would not be alright even if it were safe."""
    assert "关于对方" in check("你为什么做量子计算", PRIVATE).reason


def test_a_quote_wearing_a_question_mark_is_not():
    assert "原话搬运" in check("今天面试搞砸了是什么感受", PRIVATE).reason


def test_a_name_only_he_mentioned_is_not():
    assert check("字节的量子计算组", PRIVATE) is not None


def test_identifiers_never_leave():
    assert "标识符" in check("13800138000 是谁的号", PRIVATE).reason
    assert "标识符" in check("https://x.com 是什么", PRIVATE).reason


def test_a_long_question_is_treated_as_a_quote():
    long_one = "为什么" + "很长的问题" * 6
    assert "太长" in check(long_one, PRIVATE).reason


def test_malformed_extraction_entries_are_dropped():
    provider = StubProvider(structured={"curious": [
        {"question": "量子计算为什么难", "cues": "量子计算"},
        {"question": "", "cues": "x"},
        {"cues": "no question"},
        "not a mapping",
    ]})
    assert extract_curiosity(provider, ["a: b"], []) == [
        {"question": "量子计算为什么难", "cues": "量子计算"}
    ]


def test_nothing_wondered_about_means_no_block():
    assert as_prompt_block([]) == ""


def test_she_is_told_not_to_pretend_she_knows_the_answer():
    block = as_prompt_block(["量子计算为什么难"])
    assert "还没去弄清楚" in block
    assert "不要假装已经知道答案" in block


# --- the whole path ---------------------------------------------------------


def build(store, persona, provider) -> Runtime:
    return Runtime(store, provider, persona, user_id="local", channel="cli")


def test_a_quiet_session_leaves_her_with_nothing_to_look_into(store, persona):
    """Fires on accumulated weight, not on a timer. Pleasantries should not
    make her curious about anything."""
    provider = StubProvider(
        ["嗯", "在的"],
        structured={"curious": [{"question": "不该出现的", "cues": "x"}]},
    )
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("在吗")
        list(runtime.reply())
        session_id = runtime.session_id

    assert store.session_salience(session_id) < 1.2
    runtime.extract_session(session_id)
    assert store.open_curiosity() == []


def test_a_rejected_question_is_kept_with_its_reason(store, persona):
    """A guard whose effect you cannot see is one you cannot tell is too tight."""
    provider = StubProvider(
        ["说了点什么，长度够触发抽取的那种"],
        structured={"curious": [{"question": "你为什么做量子计算", "cues": "量子"}]},
    )
    runtime = build(store, persona, provider)
    with runtime:
        turn_id = runtime.ingest("我在做量子计算")
        list(runtime.reply())
        session_id = runtime.session_id
        store.save_perception(turn_id, _salient())

    assert runtime._extract_curiosity(session_id) == 0
    assert store.open_curiosity() == []
    rejected = store.rejected_curiosity()
    assert len(rejected) == 1
    assert "关于对方" in rejected[0]["rejected_reason"]


def test_what_she_wonders_about_reaches_the_context(store, persona):
    provider = StubProvider(["ok"])
    store.add_curiosity("量子计算为什么难", "量子计算")
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("hello")
        list(runtime.reply())

    assert any(
        "量子计算为什么难" in m["content"]
        for m in provider.calls[-1]
        if m["role"] == "system"
    )


def _salient():
    from hearth_friend.core.perception import Perception

    return Perception(salience=1.0, emotion_intensity=0.8)
