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


MAX_NEW_CURIOSITY = 2

_CURIOSITY_INSTRUCTION = """下面是一段聊天记录。找出其中让"她"产生好奇、想去弄明白的东西。

产出的必须是**关于世界的问题**，不是关于对方的事：
  好： 量子计算为什么难
  好： 为什么有人熬夜效率反而高
  坏： 他的论文卡在哪                （关于对方）
  坏： 面试搞砸了是什么感觉            （搬运原话）
  坏： 字节跳动待遇怎么样              （对方的具体处境）

想知道对方的事，直接问他就好，不用去查。所以这里只要"换个人来看也成立"的问题。

每条给出：
  question  一句话，不超过 20 个字，不含人名、公司名、数字、链接
  cues      会让人想起这个问题的词，空格分隔

宁可一条都不给，也不要为了凑数把对方的事写成问题。
只输出 JSON：{"curious":[{"question":"...","cues":"..."}]}"""


def extract_curiosity(
    provider: ModelProvider, transcript: list[str], known: list[str]
) -> list[dict]:
    """What in this conversation left her wanting to understand something.

    Separate from the self-fact call rather than folded into it: that one reads
    only what she said, this one reads both sides, and mixing the inputs made
    things the other person said come back as facts about her.
    """
    if not transcript:
        return []

    known_block = "\n".join(f"- {k}" for k in known) or "（还没有）"
    messages: list[Message] = [
        {"role": "system", "content": _CURIOSITY_INSTRUCTION},
        {
            "role": "user",
            "content": (
                f"【她已经在想的问题】\n{known_block}\n\n"
                "【这段聊天】\n" + "\n".join(transcript)
            ),
        },
    ]
    try:
        data = provider.structured_output(messages, temperature=0.3)
    except (ProviderError, AttributeError):
        return []

    out: list[dict] = []
    for entry in data.get("curious") or []:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question", "")).strip()
        cues = str(entry.get("cues", "")).strip()
        if not question or not cues:
            continue
        out.append({"question": question[:200], "cues": cues[:200]})
        if len(out) >= MAX_NEW_CURIOSITY:
            break
    return out


MAX_NEW_MEMORIES = 5

_MEMORY_INSTRUCTION = """下面是一段聊天记录。把其中值得记住的东西挑出来，分两类。

**about_you** —— 关于他的、以后一直成立的事。
**一律用第三人称写「他……」**，因为这些是你记在自己本子上的、关于他的事，
写成「你……」你以后会读成是在说自己：
  名字、称呼、养的宠物、在做什么、住哪、习惯、明确的喜好和讨厌
  kind 用 fact（事实）／preference（偏好）／situation（当前处境）

**episodes** —— 具体发生过的事，用你的第一人称记下来：
  「他上周三面试搞砸了，准备了两周」这种
  importance 0 到 1：日常寒暄 0.1–0.2，他在意的事 0.5 以上

  formative true/false —— 这件事是不是**构成他这个人的一部分**，永远不该淡忘：
    是：父母家人、重大变故、失去、疾病、重要的分别、人生转折、
        真正的成就、他明确说过对他很重要的事
    否：其余一切。今天很累、这周论文卡住、喜欢什么口味——
        这些重要归重要，但不是他之所以是他
    宁可标 false。标错成 true 的东西会永远留着

两类都要给 cues：会让人想起这条的词，空格分隔，**要短、要具体**
（写「QB 猫 宠物」，不要写「他的宠物情况」；一两个字的词也要写上）

聊天记录里「他：」是对方说的，「你：」是你自己说的。

不要记：
  - 「你：」那些行里的内容——那是你自己，不是他
  - 只在这一刻成立的（「他现在在改论文」这种，除非改论文这件事本身重要）
  - 已经在「你已经知道的」里的

宁可少，不要凑。只输出 JSON：
{"about_you":[{"kind":"...","cues":"...","statement":"..."}],
 "episodes":[{"cues":"...","content":"...","importance":0.5}]}"""


def extract_memories(
    provider: ModelProvider, transcript: list[str], known: list[str]
) -> dict:
    """One call at the end of a session, over both sides of it."""
    if not transcript:
        return {"about_you": [], "episodes": []}

    known_block = "\n".join(f"- {k}" for k in known) or "（还没有）"
    messages: list[Message] = [
        {"role": "system", "content": _MEMORY_INSTRUCTION},
        {
            "role": "user",
            "content": (
                f"【你已经知道的】\n{known_block}\n\n"
                "【这段聊天】\n" + "\n".join(transcript)
            ),
        },
    ]
    try:
        data = provider.structured_output(messages, temperature=0.2)
    except (ProviderError, AttributeError):
        return {"about_you": [], "episodes": []}

    facts = []
    for entry in data.get("about_you") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).strip()
        cues = str(entry.get("cues", "")).strip()
        statement = str(entry.get("statement", "")).strip()
        if kind not in ("fact", "preference", "situation") or not cues or not statement:
            continue
        facts.append({"kind": kind, "cues": cues[:200], "statement": statement[:300]})

    episodes = []
    for entry in data.get("episodes") or []:
        if not isinstance(entry, dict):
            continue
        cues = str(entry.get("cues", "")).strip()
        content = str(entry.get("content", "")).strip()
        if not cues or not content:
            continue
        try:
            importance = max(0.0, min(1.0, float(entry.get("importance", 0.3))))
        except (TypeError, ValueError):
            importance = 0.3
        episodes.append({
            "cues": cues[:200],
            "content": content[:500],
            "importance": importance,
            "formative": bool(entry.get("formative", False)),
        })
        if len(episodes) >= MAX_NEW_MEMORIES:
            break

    return {"about_you": facts, "episodes": episodes}


_PATTERN_INSTRUCTION = """下面是同一个话题下发生过的几件事。看看它们合起来是不是说明了什么。

只有当这几件事**指向同一个稳定的模式**时才给结论。多数时候它们只是碰巧沾了同一个词，
那就返回空——这很正常，不要为了给答案而硬凑。

如果给，结论要：
  - 关于他的、比较稳的倾向或习惯
  - **留有余地**。你只看到了这几次，不是全部。用「好像」「多半」这种说法，
    不要写成定论
  - 一句话，不超过 30 字

绝对不要下这类结论：
  - 关于他对你的态度（「他不想理我」这种）——你手上的证据不足以支撑，而且错了代价很大
  - 给他贴性格标签（「他是个冷淡的人」）

只输出 JSON：{"pattern": "……"} 或 {"pattern": null}"""


def extract_pattern(provider: ModelProvider, cue: str, episodes: list[str]) -> str | None:
    """Whether several occasions add up to something.

    Deliberately reluctant. This is the edge of attribution, where being wrong
    stops being annoying: three tired evenings become "he does not want to talk
    to me", and everything after is built on it.
    """
    if len(episodes) < 3:
        return None

    messages: list[Message] = [
        {"role": "system", "content": _PATTERN_INSTRUCTION},
        {
            "role": "user",
            "content": f"【话题】{cue}\n\n【发生过的事】\n"
            + "\n".join(f"- {e}" for e in episodes),
        },
    ]
    try:
        data = provider.structured_output(messages, temperature=0.2)
    except (ProviderError, AttributeError):
        return None

    pattern = data.get("pattern")
    if not isinstance(pattern, str):
        return None
    pattern = pattern.strip()
    return pattern[:120] if 4 <= len(pattern) <= 120 else None
