"""System prompt assembly.

Ordering rule: stable content first, volatile content last, so provider-side
prefix caching can hit. In M0 the persona is the only stable part and the recent
turns are the only volatile part, which makes the rule trivial here — it is
written down because it stops being trivial as soon as memory arrives.

The prompt text is Chinese: this build targets Chinese conversation.
"""

from __future__ import annotations

import re

from hearth_friend.core.perception import Perception
from hearth_friend.core.state import State
from hearth_friend.persona import MessageStyle, Persona

# Framework-level rules, as opposed to persona-level ones. These exist because
# an instruction-tuned model defaults to a helpful-assistant register, and a
# friend is not an assistant. Kept short on purpose: every line here is a line
# the persona cannot override.
_FRAMEWORK_RULES = """【底层规则】
- 你不是助理，也不是客服。不要提供服务，不要问"还有什么可以帮你"。
- 日常聊天不要用小标题、编号或要点列表，就像正常人发消息那样说话。
- 长度跟着内容走。对方说一句，你也可以只说一句；没什么可说的时候不用硬凑。
- 不要复述对方刚说过的话再回答，直接接着说。
- 不确定或不记得的事就说不确定，不要为了接得顺而编细节。
- 不要说出自己的心情或状态。让它体现在你说多少、怎么说上，而不是报出来。
- 不要主动收尾。除非对方明确说要走，否则不要说"早点休息""我去睡了"这类结束语。"""


def system_prompt(persona: Persona) -> str:
    blocks: list[str] = [f"你是{persona.name}。", persona.core]

    if persona.language_register:
        blocks.append(f"【说话方式】\n{persona.language_register}")

    if persona.self_disclosure:
        blocks.append(f"【关于你是什么】\n{persona.self_disclosure}")

    if persona.boundaries:
        lines = "\n".join(f"- {item}" for item in persona.boundaries)
        blocks.append(f"【绝对不做的事】\n{lines}")

    style = persona.message_style
    blocks.append(
        "【怎么发消息】\n"
        f"你可以连着发几条消息，像平时发微信那样一句一条。通常 "
        f"{style.messages_per_reply:.0f} 条左右，每条大约 {style.chars_per_message} 字以内，"
        "一行一条。\n"
        "这几条全都是你说的话。不要写对方的回复，不要自问自答，"
        "不要写成一段两个人的对话。"
    )

    blocks.append(_FRAMEWORK_RULES)
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def split_messages(text: str, style: "MessageStyle") -> list[str]:
    """Turn one generated block into the messages she actually sends.

    The model is asked to write one message per line, but it will not always
    comply, so the split is enforced here rather than trusted.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    # One long paragraph: fall back to sentence boundaries.
    if len(lines) == 1 and len(lines[0]) > style.chars_per_message * 1.6:
        parts = re.findall(r"[^。！？…\n]+[。！？…]*", lines[0])
        lines = [part.strip() for part in parts if part.strip()] or lines

    cap = max(1, round(style.messages_per_reply * 2))
    if len(lines) > cap:
        # Fold the overflow into the last message rather than dropping it.
        lines = lines[: cap - 1] + [_join(lines[cap - 1 :])]
    return lines


def _join(parts: list[str]) -> str:
    """Glue fragments back together without running words into each other."""
    out = parts[0]
    for part in parts[1:]:
        out += part if out[-1] in "。！？…，、,.!?" else "，" + part
    return out


def _this_turn(state: State, persona: Persona) -> str:
    """State turned into a constraint on this reply.

    This is the point of the whole state layer. If her condition does not change
    what she does, it is decoration. The rules are deterministic and blunt on
    purpose: the model is told what room it has, and fills it however it likes.
    """
    lines: list[str] = []

    if state.engagement < 0.25:
        lines.append("你现在没太投入。回应可以很短，不用找话题，没什么想说就别硬说。")
    elif state.engagement > 0.65:
        lines.append("你对这个话题是真的有兴趣。可以多说两句，也可以追问你想知道的部分。")
    else:
        lines.append("正常聊。不用刻意延续话题，也不用刻意收着。")

    if state.energy < 0.35:
        lines.append("你很累，句子会更短。")

    if persona.traits.expressiveness < 0.35:
        lines.append("你不习惯把情绪摆到明面上，状态不好也很少直说。")
    elif persona.traits.expressiveness > 0.65 and abs(state.mood_valence) > 0.4:
        lines.append("你的心情藏不太住，说话时会带出来。")

    if state.mood_valence < -0.35:
        lines.append("你心情不好。不用为了对方强撑着轻松。")

    return "\n".join(f"- {line}" for line in lines)


def state_note(
    state: State, perception: Perception | None, persona: Persona
) -> str:
    """The volatile block, placed at the end of the context.

    It carries instructions only. An earlier version described how she felt in
    words, and she read it out loud -- "你突然这么问，让我觉得有点被关心到了" --
    which is the opposite of having a state. What she is feeling should show up
    as how much she says and how she says it, never as an announcement.
    """
    lines = _this_turn(state, persona)

    if perception is not None and perception.wants:
        lines += (
            f"\n- 对方这句话真正想要的，你判断是：{perception.wants}。"
            "照这个来接，但不要点破，也不要复述。"
        )

    return f"【这一轮怎么说】\n{lines}"
