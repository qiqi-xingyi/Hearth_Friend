"""What happened between you, and what is true about him.

Split in two because they are recalled differently. Asked his name she should
not have to be reminded of it by association: she answered "章鱼小丸子" and said
she remembered him saying so, which is worse than forgetting. What happened last
week should come to mind the way things come to mind, or not at all.

The block below always says what is absent. Told to admit uncertainty, she
invented three names in three tries; the instruction was already in the prompt
and did nothing, because whether she remembers is not something she can check.
Given a list and told that what is not on it she does not have, it becomes
something she can check.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_RECALLED = 8


@dataclass(frozen=True)
class Memory:
    id: int
    content: str
    cues: str
    event_time: str | None
    importance: float
    strength: float
    embedding: bytes | None
    embedding_model: str | None


def cues_present(vocabulary: list[str], text: str) -> list[str]:
    """Which of the things she has ever been reminded by are in front of her.

    Substring rather than token match: Chinese has no spaces, and the terms that
    matter most -- a name, a pet, a field -- are one or two characters, which no
    tokeniser here will separate reliably.
    """
    return [cue for cue in vocabulary if cue and cue in text]


def as_prompt_block(memories: list[Memory], about_you: list[dict]) -> str:
    blocks: list[str] = []

    if about_you:
        lines = "\n".join(f"- {row['statement']}" for row in about_you)
        blocks.append(f"【关于他，你确定的】\n{lines}")
    else:
        blocks.append("【关于他，你确定的】\n（还没有。）")

    if memories:
        lines = "\n".join(f"- {m.content}" for m in memories)
        blocks.append(f"【你想起来的事】\n{lines}")
    else:
        blocks.append("【你想起来的事】\n（这会儿没想起什么。）")

    blocks.append(
        "以上就是你手上全部的记录。这里没有的，你就是没有——\n"
        "他问起你没有记录的事，直接说不记得、或者问他，"
        "不要编一个，更不要用「我记得」「你之前提过」这种说法。"
    )
    return "\n\n".join(blocks)
