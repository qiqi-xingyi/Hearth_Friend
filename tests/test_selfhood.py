"""What she can recall about herself.

Asked six times whether she played a particular game, she said she owned a
console, had never owned one, played it on a PC, and that it gathered dust.
Nothing about her survived the sentence it was said in. These tests are about
the layer that fixed that.
"""

from __future__ import annotations

from hearth_friend.core.selfhood import SelfFact, as_prompt_block, parse_cues, recall
from hearth_friend.persona import Persona


def fact(id: int, kind: str, cues: str, statement: str) -> SelfFact:
    return SelfFact(id, kind, parse_cues(cues), statement)


FACTS = [
    fact(1, "fact", "NS switch 塞尔达 游戏机", "我没有 NS，顶多手机上玩点小的"),
    fact(2, "view", "灵感 状态 拖延", "觉得等灵感是废话，画不出来是练得不够"),
    fact(3, "dislike", "香菜", "不吃香菜"),
]


def test_a_topic_brings_the_right_thing_to_mind():
    assert [f.id for f in recall(FACTS, "你喜欢玩NS吗？塞尔达之类的")] == [1]
    assert [f.id for f in recall(FACTS, "这家店香菜放太多了")] == [3]


def test_nothing_relevant_is_recalled_for_an_unrelated_topic():
    assert recall(FACTS, "今天天气不错") == []


def test_a_specific_cue_outranks_a_general_one():
    facts = FACTS + [fact(4, "fact", "游戏", "我玩游戏很菜")]
    assert recall(facts, "塞尔达和游戏")[0].id == 1


def test_with_nothing_recalled_she_is_told_not_to_invent():
    """The whole point. Left to fill the silence she invents, and the invention
    is different every time."""
    block = as_prompt_block([])
    assert "不要临时编一个" in block


def test_recalled_facts_reach_the_block_verbatim():
    block = as_prompt_block(recall(FACTS, "聊聊灵感这回事"))
    assert "觉得等灵感是废话，画不出来是练得不够" in block
    assert "不要改口" in block


def test_seeding_from_the_persona_file_is_idempotent(store, persona):
    """Editing the persona file later has to take effect, and it must not
    duplicate or overwrite what she has settled since."""
    from hearth_friend.core import Runtime

    loaded = Persona.load("persona/example.yaml")
    runtime = Runtime(store, None, loaded, user_id="local", channel="cli")

    assert runtime.seed_self() == len(loaded.self_facts)
    assert runtime.seed_self() == 0
    assert len(store.self_facts()) == len(loaded.self_facts)


def test_the_shipped_personas_disagree_with_each_other():
    """Two people, not one voice with two names."""
    warm = Persona.load("persona/example.yaml")
    quiet = Persona.load("persona/quiet.yaml")
    assert warm.self_facts and quiet.self_facts
    assert {f["statement"] for f in warm.self_facts} != {
        f["statement"] for f in quiet.self_facts
    }
