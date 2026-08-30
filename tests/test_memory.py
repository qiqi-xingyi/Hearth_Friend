"""What happened between you, and what is true about him.

Before this existed she was asked her friend's name and said "章鱼小丸子", added
that she remembered him saying so, thought his cat was a person reading a novel,
and placed his doctorate in the wrong field. Not forgetting -- confabulation
delivered in the voice of memory, which is worse.
"""

from __future__ import annotations

from hearth_friend.core import Runtime
from hearth_friend.core.memory import Memory, as_prompt_block, cues_present
from tests.conftest import StubProvider


def build(store, persona, provider) -> Runtime:
    return Runtime(store, provider, persona, user_id="local", channel="cli")


def memory(id: int, content: str) -> Memory:
    return Memory(id, content, "", None, 0.5, 0.5, None, None)


def test_short_cues_match_where_a_tokeniser_would_not():
    """Chinese has no spaces, and what matters most -- a name, a pet, a field --
    is one or two characters. FTS5's trigram tokeniser matches none of them."""
    vocabulary = ["QB", "猫", "量子计算", "洛"]
    assert cues_present(vocabulary, "QB 最近怎么样") == ["QB"]
    assert cues_present(vocabulary, "我是做量子计算的") == ["量子计算"]
    assert cues_present(vocabulary, "今天天气不错") == []


def test_the_block_always_says_what_is_missing():
    """Told to admit uncertainty she invented three names in three tries. The
    instruction was already in the prompt; whether she remembers was not
    something she could check."""
    block = as_prompt_block([], [])
    assert "这里没有的，你就是没有" in block
    assert "不要用「我记得」" in block


def test_what_is_known_and_what_is_not_are_kept_apart():
    block = as_prompt_block([memory(1, "他上周三面试没考好")], [
        {"statement": "他养了一只猫，叫QB"}
    ])
    assert "他养了一只猫，叫QB" in block
    assert "他上周三面试没考好" in block


def test_facts_about_him_are_recalled_whole_and_never_sampled(store, persona):
    """His name must not depend on a draw. Sampling identity is how she came to
    believe he was called something else."""
    store.add_about_you("fact", "奇奇 名字", "他叫奇奇")
    store.add_about_you("fact", "QB 猫", "他养了一只猫，叫QB")

    provider = StubProvider(["ok"])
    with build(store, persona, provider) as runtime:
        runtime.ingest("你还记得我叫什么吗")
        list(runtime.reply())

    system = "\n".join(m["content"] for m in provider.calls[-1] if m["role"] == "system")
    assert "他叫奇奇" in system
    assert "他养了一只猫，叫QB" in system


def test_recall_reads_a_bounded_shortlist_whatever_the_table_holds(store, persona):
    """First stage is indexed and capped, so what recall costs does not depend
    on how much has ever happened."""
    for index in range(500):
        store.add_memory(f"第 {index} 件事", f"事{index % 7}", importance=0.3)

    candidates = store.memory_candidates(["事3"])
    assert 0 < len(candidates) <= 200


def test_a_memory_that_comes_to_mind_sticks_a_little_harder(store):
    memory_id = store.add_memory("他提过一次面试", "面试", importance=0.4)
    before = store.conn.execute(
        "SELECT strength, recall_count FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()

    store.touch_memories([memory_id])
    after = store.conn.execute(
        "SELECT strength, recall_count FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()

    assert after["strength"] > before["strength"]
    assert after["recall_count"] == before["recall_count"] + 1


def test_reinforcement_cannot_ratchet_something_into_permanence(store):
    memory_id = store.add_memory("一件小事", "小事", importance=0.2)
    for _ in range(200):
        store.touch_memories([memory_id])
    strength = store.conn.execute(
        "SELECT strength FROM memory WHERE id = ?", (memory_id,)
    ).fetchone()["strength"]
    assert strength <= 1.0


def test_the_transcript_says_who_said_what_in_the_prompts_own_language(store, persona):
    """Labelled "user:" and "assistant:" against a Chinese instruction, she read
    her own lines as his and came away believing he draws for a living."""
    provider = StubProvider(
        ["我今天画完了稿子，改来改去反而没了最初的感觉"],
        structured={"about_you": [], "episodes": []},
    )
    runtime = build(store, persona, provider)
    with runtime:
        runtime.ingest("我在改论文，卡在怎么组织结构上，头疼")
        list(runtime.reply())
        session_id = runtime.session_id

    runtime._extract_memories(session_id)
    sent = "\n".join(
        m["content"] for call in provider.calls for m in call if m["role"] == "user"
    )
    assert "他：我在改论文" in sent
    assert "你：我今天画完了稿子" in sent
