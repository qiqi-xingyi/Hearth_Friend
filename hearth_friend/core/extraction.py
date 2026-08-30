"""Folding what she said back into what is true about her.

Seeded facts hold, but everything outside the persona file is still invented
fresh each time: asked about ice cream in four separate sessions she was
indifferent, enthusiastic, undemanding, and fussy, the last two flatly
contradicting each other. Whatever she settles in conversation has to become
hers, or the persona file is the only part of her that is real and I am the one
writing all of it.

One cheap call per session, over what she said. Not on the path of any reply.
"""

from __future__ import annotations

import json

from hearth_friend.providers.base import Message, ModelProvider, ProviderError

MAX_NEW_PER_SESSION = 6

_INSTRUCTION = """下面是她在一次聊天里说过的话。挑出其中关于她自己的、以后应该一直保持一致的说法。

要的是：
- 关于她自己的事实：有没有某样东西、住哪、习惯、经历过什么
- 她表达出的看法、偏好、口味
- 她明确说不喜欢的东西

不要：
- 对对方的评价或关心
- 只在这一刻成立的话（"我现在有点困""刚画完稿子"）
- 客套话、附和的话
- 已经在"她已经确定的事"里的内容，或与之矛盾的内容

每条给出：
  kind  fact / view / dislike
  cues  会让人想起这条的词，空格分隔，要具体（写"塞尔达 NS 游戏机"，不要只写"游戏"）
  say   用她的第一人称，一句话，压缩成能长期复用的说法

宁可少，不要凑数。没有就返回空列表。
只输出 JSON：{"facts":[{"kind":"...","cues":"...","say":"..."}]}"""


def extract_self_facts(
    provider: ModelProvider, said: list[str], known: list[str]
) -> list[dict]:
    """Read a session's worth of her own messages for anything that should stick."""
    if not said:
        return []

    known_block = "\n".join(f"- {k}" for k in known) or "（还没有）"
    messages: list[Message] = [
        {"role": "system", "content": _INSTRUCTION},
        {
            "role": "user",
            "content": (
                f"【她已经确定的事】\n{known_block}\n\n"
                "【她这次说过的话】\n" + "\n".join(said)
            ),
        },
    ]
    try:
        data = provider.structured_output(messages, temperature=0.2)
    except (ProviderError, AttributeError):
        return []

    out: list[dict] = []
    for entry in data.get("facts") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).strip()
        cues = str(entry.get("cues", "")).strip()
        say = str(entry.get("say", "")).strip()
        if kind not in ("fact", "view", "dislike") or not cues or not say:
            continue
        out.append({"kind": kind, "cues": cues[:200], "say": say[:200]})
        if len(out) >= MAX_NEW_PER_SESSION:
            break
    return out
