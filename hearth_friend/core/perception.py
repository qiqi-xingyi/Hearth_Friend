"""What she makes of an incoming message, before deciding anything.

This step exists because the previous design had none: a message went straight
into the prompt and out came a reply, so nothing about you was ever registered.
Understanding what you are after and how you sound has to happen somewhere, and
it cannot happen in the same breath as speaking.

One cheap model call, structured output, never prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from hearth_friend.providers.base import Message, ModelProvider, ProviderError

_INSTRUCTION = """你在读一条消息，判断它的意思和分量。只输出 JSON，不要解释。

字段：
  emotion    对方此刻的情绪，一个中文词（如 平静/高兴/疲惫/烦躁/低落/兴奋/试探）
  valence    情绪正负，-1 到 1 的小数
  intensity  情绪强度，0 到 1 的小数
  wants      对方发这条消息实际想要什么，一句话。不是复述内容，是他要的东西
             （如 想被问下去 / 只是随口一句 / 想被安慰 / 在试探你的态度 / 想分享）
  salience   这件事在这段关系里有多大分量，0 到 1
  about_her  这条消息是不是在对你说话或在问你，true/false

注意：
- 大多数日常闲聊的 salience 在 0.1–0.3，不要给什么都打高分
- wants 常常和字面内容不同。"你叫什么" 字面是问名字，实际可能是在拉近距离
"""

_EXAMPLE = '{"emotion":"平静","valence":0.0,"intensity":0.2,"wants":"随口打个招呼",' \
           '"salience":0.1,"about_her":true}'


@dataclass(frozen=True)
class Perception:
    emotion: str = "平静"
    valence: float = 0.0
    emotion_intensity: float = 0.2
    wants: str = ""
    salience: float = 0.2
    about_her: bool = True
    raw: str = ""

    @classmethod
    def neutral(cls) -> "Perception":
        """Used when the read fails. She should carry on, not crash."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "Perception":
        def number(key: str, default: float, low: float, high: float) -> float:
            try:
                return max(low, min(high, float(data.get(key, default))))
            except (TypeError, ValueError):
                return default

        return cls(
            emotion=str(data.get("emotion") or "平静")[:20],
            valence=number("valence", 0.0, -1.0, 1.0),
            emotion_intensity=number("intensity", 0.2, 0.0, 1.0),
            wants=str(data.get("wants") or "")[:200],
            salience=number("salience", 0.2, 0.0, 1.0),
            about_her=bool(data.get("about_her", True)),
            raw=json.dumps(data, ensure_ascii=False),
        )


def perceive(
    provider: ModelProvider, message: str, *, recent: list[str] | None = None
) -> Perception:
    """Read one message. Falls back to neutral rather than failing the turn."""
    context = ""
    if recent:
        context = "刚才聊到的：\n" + "\n".join(recent[-4:]) + "\n\n"

    messages: list[Message] = [
        {"role": "system", "content": _INSTRUCTION + f"\n输出示例：\n{_EXAMPLE}"},
        {"role": "user", "content": f"{context}要判断的这条消息：\n{message}"},
    ]
    try:
        return Perception.from_dict(provider.structured_output(messages, temperature=0.3))
    except (ProviderError, AttributeError):
        return Perception.neutral()
