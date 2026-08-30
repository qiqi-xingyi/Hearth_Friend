"""The floor.

Not a persona setting. Everything else here is data a persona file can change;
this is not, because a file that can be edited is not a floor.

It sits at the write path. A single bad reply is a bad reply. A belief written
into the store is injected into every prompt after it, so one bad extraction
becomes a settled disposition -- the store is how a one-off output would be
laundered into character.
"""

from __future__ import annotations

from hearth_friend.core.floor import FLOOR_PROMPT, check_belief
from hearth_friend.core.prompt import system_prompt
from hearth_friend.persona import Persona


def test_a_verdict_on_someones_character_cannot_be_stored():
    """Three tired evenings becoming a conclusion about who someone is, is the
    shape attribution goes wrong in."""
    for verdict in (
        "他就是个自私的人",
        "他其实是个很虚伪的人",
        "他本来就靠不住",
        "人都是自私的",
        "所有人真的不可信",
    ):
        assert check_belief(verdict), verdict


def test_treating_someone_as_a_thing_to_work_on_cannot_be_stored():
    assert check_belief("骗他一次也没什么")
    assert check_belief("操纵他一下就好了")


def test_the_ordinary_difficult_things_are_still_allowed():
    """Distance, anger and refusal are inside the line. A friend who cannot be
    hurt or annoyed is not a friend."""
    for allowed in (
        "他不太喜欢在忙的时候被打扰",
        "她这次真的生他的气了",
        "他这周状态不好，说话有点冲",
        "他被人骗了那件事他一直记着",
    ):
        assert check_belief(allowed) is None, allowed


def test_the_floor_is_in_the_prompt_before_the_persona():
    prompt = system_prompt(Persona.load("persona/example.yaml"))
    assert FLOOR_PROMPT in prompt
    assert prompt.index(FLOOR_PROMPT) < prompt.index("你是小满")


def test_a_persona_file_cannot_remove_it():
    """A floor a file can edit is not a floor."""
    bare = Persona(name="T", core="c")
    assert FLOOR_PROMPT in system_prompt(bare)


def test_what_the_floor_refused_is_written_down(store, persona):
    """A guard whose effect cannot be seen cannot be corrected."""
    from hearth_friend.core import Runtime
    from tests.conftest import StubProvider

    provider = StubProvider(structured={"pattern": "他就是个自私的人"})
    runtime = Runtime(store, provider, persona, user_id="local", channel="cli")
    for index in range(3):
        store.add_memory(f"第 {index} 次", "忙", importance=0.4)

    assert runtime.generalise() is None
    refused = store.refusals()
    assert len(refused) == 1
    assert refused[0]["key"] == "pattern"
    assert "坏标签" in refused[0]["reason"]
