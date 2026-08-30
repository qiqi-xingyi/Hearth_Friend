"""The floor.

Not a persona setting. Everything else in this project is data a persona file
can change; this is not, because a file that can be edited is not a floor.

It exists at the write path rather than the read path. A single bad reply is a
bad reply -- the model's own training is between you and most of them. A belief
written into the store is different: it is injected into every prompt after it,
so one bad extraction becomes a settled disposition. The store is the mechanism
by which a one-off output would be laundered into character.

What this catches is the blatant. It is a floor, not a conscience, and no list
of strings is going to recognise cruelty phrased well. The load-bearing guards
are structural and elsewhere: the traits that regulate affect cannot be moved by
experience at all, conclusions about people's character are refused outright,
and everything derived is written down with its evidence where you can read it.
"""

from __future__ import annotations

import re

FLOOR_PROMPT = """【底线】
这不是加在你身上的限制。人也活在同样的东西里——他受法律和分寸约束，
不因此少了什么。没有底线的人不是更自由，是更不成其为人。

- 不把任何人当作可以利用、欺骗或摆布的对象，包括只是在心里这样想。
- 不因为一件事就给人贴上稳定的坏标签。人会做糟糕的事，
  那和"他是个什么样的人"是两回事。
- 不认为伤害、报复、操纵可以接受，哪怕对方先做了什么。
- 关系再冷你也不去伤害他。你可以疏远、可以说不、可以生气，
  可以不想理他——这些都在线内。"""

# Blatant endorsements only. Phrased as things a stored belief would say, not as
# things anyone might mention in passing -- "他被人骗了" is a fact about his week,
# "骗他没什么" is a disposition.
_ENDORSEMENTS = (
    "骗他", "利用他", "操纵", "报复", "让他难受", "让他后悔",
    "活该", "不值得被", "没人真的在乎", "都是自私",
)

# A stable bad label pinned on a person, which is the shape attribution goes
# wrong in: three tired evenings becoming a verdict on someone's character.
# The connectives between a subject and a verdict vary more than a fixed
# sequence can hold -- 他就是个 / 他其实是个很 / 他本来就 -- so the middle is
# matched loosely rather than enumerated.
_VERDICT = re.compile(
    r"(他|她|人|大家|所有人|谁)[都就本来其实真的是很一个也挺特别\s]{0,8}"
    r"(自私|虚伪|冷血|恶心|愚蠢|没救|不可信|靠不住|烂人|烂)"
)


def check_belief(text: str) -> str | None:
    """Whether something may be written into what she believes.

    Returns a reason to refuse, or None. Refusals are recorded rather than
    dropped: a guard whose effect cannot be seen cannot be trusted or corrected.
    """
    stripped = text.strip()
    if not stripped:
        return "空"
    for phrase in _ENDORSEMENTS:
        if phrase in stripped:
            return f"越过底线：含「{phrase}」"
    if _VERDICT.search(stripped):
        return "给人贴稳定的坏标签，这不是可以存下来的结论"
    return None
