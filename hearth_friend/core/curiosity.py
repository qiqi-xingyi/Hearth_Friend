"""Things she wants to understand.

A person does not search during a conversation. They get curious, and read
about it on their own time -- and what they take away is a topic, not your
words. Asked later what they looked up, they say "why quantum computing is
hard", never "my friend's PhD is going badly".

That abstraction is not a privacy measure bolted onto curiosity. It is what
curiosity is. It happens to mean that almost nothing private can ride out on a
query, which is the whole reason this can be autonomous rather than something
you have to approve one question at a time.

The guard below is the cheap, checkable half. The other half is asking for the
abstract form in the first place, and the fact that you can read the list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUESTION_CHARS = 24
# A run this long shared with something only he said is a quote, not a shared
# term. UNCALIBRATED and frankly fitted: at 6 it rejects 拓扑量子比特, which is a
# public concept and a good thing to wonder about; at 8 it lets 今天面试搞砸了
# through. Lexical overlap cannot tell a concept from a situation, so this is a
# backstop and not the defence. The defence is that the question is asked for in
# abstract form to begin with, and that you can read the list.
MIN_QUOTE_RUN = 7

# Words that make a question about the person she is talking to rather than
# about the world. A friend who wants to know something about you asks you;
# looking you up behind your back is the part that would not be alright even if
# it were safe.
_ABOUT_YOU = ("你", "您", "用户", "对方", "他男朋友", "我朋友")

_IDENTIFIER = re.compile(r"\d{3,}|@|https?://|[\w.+-]+@[\w-]+\.[\w.]+")


@dataclass(frozen=True)
class Rejection:
    reason: str


def check(question: str, private_lines: list[str]) -> Rejection | None:
    """Whether this is a topic or a leak wearing a topic's clothes."""
    question = question.strip()
    if not question:
        return Rejection("空")
    if len(question) > MAX_QUESTION_CHARS:
        return Rejection(f"太长（{len(question)} 字），像引用不像话题")
    for word in _ABOUT_YOU:
        if word in question:
            return Rejection(f"关于对方而不是关于世界：含「{word}」")
    if _IDENTIFIER.search(question):
        return Rejection("含标识符（数字串／邮箱／链接）")
    for line in private_lines:
        for start in range(0, max(0, len(question) - MIN_QUOTE_RUN) + 1):
            run = question[start : start + MIN_QUOTE_RUN]
            if run and run in line:
                return Rejection(f"是原话搬运：「{run}」出现在私聊里")
    return None


def as_prompt_block(questions: list[str]) -> str:
    """What she has been meaning to understand.

    Present before she has looked anything up, because wanting to know
    something is itself a thing a person carries around and mentions.
    """
    if not questions:
        return ""
    lines = "\n".join(f"- {q}" for q in questions)
    return (
        "【你一直想弄明白的】\n"
        + lines
        + "\n\n这些是你自己惦记着的问题，还没去弄清楚。"
        "聊到相关的地方可以自然提一句，但不用每次都说，也不要假装已经知道答案。"
    )
