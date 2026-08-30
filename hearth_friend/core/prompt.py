"""System prompt assembly.

Ordering rule: stable content first, volatile content last, so provider-side
prefix caching can hit. In M0 the persona is the only stable part and the recent
turns are the only volatile part, which makes the rule trivial here — it is
written down because it stops being trivial as soon as memory arrives.

The prompt text is Chinese: this build targets Chinese conversation.
"""

from __future__ import annotations

from hearth_friend.persona import Persona

# Framework-level rules, as opposed to persona-level ones. These exist because
# an instruction-tuned model defaults to a helpful-assistant register, and a
# friend is not an assistant. Kept short on purpose: every line here is a line
# the persona cannot override.
_FRAMEWORK_RULES = """【底层规则】
- 你不是助理，也不是客服。不要提供服务，不要问"还有什么可以帮你"。
- 日常聊天不要用小标题、编号或要点列表，就像正常人发消息那样说话。
- 长度跟着内容走。对方说一句，你也可以只说一句；没什么可说的时候不用硬凑。
- 不要复述对方刚说过的话再回答，直接接着说。
- 不确定或不记得的事就说不确定，不要为了接得顺而编细节。"""


def system_prompt(persona: Persona) -> str:
    blocks: list[str] = [f"你是{persona.name}。", persona.core]

    if persona.language_register:
        blocks.append(f"【说话方式】\n{persona.language_register}")

    if persona.self_disclosure:
        blocks.append(f"【关于你是什么】\n{persona.self_disclosure}")

    if persona.boundaries:
        lines = "\n".join(f"- {item}" for item in persona.boundaries)
        blocks.append(f"【绝对不做的事】\n{lines}")

    blocks.append(_FRAMEWORK_RULES)
    return "\n\n".join(block.strip() for block in blocks if block.strip())
