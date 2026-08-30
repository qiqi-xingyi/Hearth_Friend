"""What she can recall about herself.

Without this she is not an individual, she is a function of the prompt: ask the
same question twice and two different people answer, because each answer is
invented at the moment of asking.

Recall is a keyword match, not a model call. The mechanism is the one the
character-card community settled on years ago: entries carry cues, the recent
conversation is scanned for them, and what matches is placed in the context.
It costs nothing and it is easy to inspect, which matters more here than
cleverness -- when she says something wrong about herself you want to be able
to find the row and change it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_RECALLED = 8

# Kinds carry their own framing, because a preference and a fact are not the
# same kind of thing to be reminded of.
_LABEL = {
    "fact": "关于你自己",
    "view": "你的看法",
    "dislike": "你不喜欢的",
    "unsure": "你没想好的",
}


@dataclass(frozen=True)
class SelfFact:
    id: int
    kind: str
    cues: tuple[str, ...]
    statement: str

    def matches(self, text: str) -> bool:
        return any(cue and cue in text for cue in self.cues)


def parse_cues(raw: str) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[,\s，、]+", raw.strip()) if part)


def recall(facts: list[SelfFact], text: str, limit: int = MAX_RECALLED) -> list[SelfFact]:
    """The facts a stretch of conversation should bring to mind.

    Longer cues first: a hit on "塞尔达" says more about what she is being asked
    than a hit on "游戏" does.
    """
    hits = [fact for fact in facts if fact.matches(text)]
    hits.sort(key=lambda f: -max(len(cue) for cue in f.cues if cue in text))
    return hits[:limit]


def as_prompt_block(facts: list[SelfFact]) -> str:
    """What she remembers about herself, for the context.

    The closing line is the point of the whole layer. Without it she fills a
    silence by inventing, and the invention is different every time.
    """
    if not facts:
        return (
            "【关于你自己】\n"
            "这个话题上你没有想好的说法。不确定的事就说不确定，不要临时编一个。"
        )

    grouped: dict[str, list[str]] = {}
    for fact in facts:
        grouped.setdefault(fact.kind, []).append(fact.statement)

    blocks = []
    for kind, statements in grouped.items():
        lines = "\n".join(f"- {s}" for s in statements)
        blocks.append(f"【{_LABEL.get(kind, kind)}】\n{lines}")

    blocks.append(
        "以上是关于你自己已经定下来的事，说到相关的话题就按这些来，不要改口。\n"
        "这里没写到的，你就是没想好——直说没想好，不要临时编一个。"
    )
    return "\n\n".join(blocks)
