"""QQ, over OneBot v11.

QQ has no usable API of its own, so a protocol implementation -- NapCat or
Lagrange -- signs in and speaks OneBot on its behalf. This connects to that as
a client, which means nothing here needs to be reachable from outside: no
public address, no inbound port, no certificate.

Single user by design. Every message that is not from the one configured
account is dropped without being read, because a friend is not a service and
this one belongs to somebody.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable

RECONNECT_DELAY_SECONDS = 5.0
MAX_MESSAGE_CHARS = 900


class OneBotChannel:
    """Sending, over the same socket the events arrive on."""

    def __init__(self, send_json: Callable[[dict], None], user_id: int):
        self.send_json = send_json
        self.user_id = user_id
        self._echo = 0

    def send(self, text: str) -> None:
        if not text.strip():
            return
        self._echo += 1
        self.send_json({
            "action": "send_private_msg",
            "params": {"user_id": self.user_id, "message": text[:MAX_MESSAGE_CHARS]},
            "echo": f"hearth-{self._echo}",
        })


# QQ's built-in emoticons arrive as an id. They are part of the sentence, not
# decoration around it -- 「行吧[撇嘴]」 means something different from 「行吧」 --
# so they are rendered inline where the id is known.
QQ_FACES = {
    "0": "惊讶", "1": "撇嘴", "2": "色", "3": "发呆", "4": "得意", "5": "流泪",
    "6": "害羞", "7": "闭嘴", "8": "睡", "9": "大哭", "10": "尴尬", "11": "发怒",
    "12": "调皮", "13": "呲牙", "14": "微笑", "15": "难过", "16": "酷", "18": "抓狂",
    "19": "吐", "20": "偷笑", "21": "可爱", "22": "白眼", "23": "傲慢", "24": "饥饿",
    "25": "困", "26": "惊恐", "27": "流汗", "28": "憨笑", "29": "悠闲", "30": "奋斗",
    "32": "疑问", "33": "嘘", "34": "晕", "38": "敲打", "39": "再见", "49": "拥抱",
    "53": "蛋糕", "60": "咖啡", "63": "玫瑰", "66": "爱心", "74": "太阳", "76": "赞",
    "77": "踩", "78": "握手", "79": "胜利", "97": "擦汗", "98": "抠鼻", "99": "鼓掌",
    "104": "衰", "106": "委屈", "109": "左亲亲", "110": "尖叫", "111": "可怜",
    "144": "喝彩", "146": "爆筋", "169": "手枪", "171": "茶", "172": "眨眼睛",
    "173": "泪奔", "174": "无奈", "175": "卖萌", "176": "小纠结", "177": "喷血",
    "178": "斜眼笑", "179": "doge", "182": "笑哭", "183": "我最美", "185": "羊驼",
    "187": "幽灵", "201": "点赞", "212": "托腮", "214": "啵啵", "222": "抱抱",
    "232": "佛系", "244": "翻白眼", "277": "汪汪", "281": "无眼笑", "289": "问号脸",
    "307": "喵喵", "311": "打call", "312": "变形", "318": "贴贴", "424": "属实",
}


def read_message(event: dict, describe: Callable[[str], str | None] | None = None) -> str:
    """What arrived, as something she can read.

    Four kinds of thing come down this wire and they are not the same:

    Text and unicode emoji she reads directly. A built-in emoticon is part of
    the sentence and is rendered inline. A sticker usually carries a label --
    「[开心]」, 「[流汗]」 -- and that label is genuinely what it says, so it is
    kept. A photograph is none of those: she cannot see it, and the honest
    record is that one arrived.

    Dropping the last two silently was the previous behaviour, and it meant he
    could send a picture and be met with nothing at all -- which is worse than
    saying she cannot see it.
    """
    message = event.get("message")
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, list):
        return ""

    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        kind = segment.get("type")
        data = segment.get("data") or {}

        if kind == "text":
            parts.append(str(data.get("text", "")))
        elif kind == "face":
            name = QQ_FACES.get(str(data.get("id", "")))
            parts.append(f"[{name}]" if name else "[表情]")
        elif kind == "image":
            # Stickers carry their own label; photographs do not.
            summary = str(data.get("summary") or "").strip().strip("[]")
            url = str(data.get("url") or data.get("file") or "")
            if summary:
                parts.append(f"[表情包：{summary}]")
            elif str(data.get("sub_type") or "") not in ("0", ""):
                parts.append("[表情包]")
            else:
                seen = describe(url) if (describe and url) else None
                parts.append(
                    f"[他发了张图：{seen}]" if seen
                    else "[他发了一张图片，你看不到内容]"
                )
        elif kind in ("record", "video"):
            parts.append(f"[他发了一段{'语音' if kind == 'record' else '视频'}，你听不到／看不到]")

    return "".join(parts).strip()


# Kept under the old name so nothing that imports it breaks.
extract_text = read_message


class QQAdapter:
    name = "qq"

    def __init__(
        self,
        conversation,
        ws_url: str,
        user_id: int,
        token: str = "",
        describe: Callable[[str], str | None] | None = None,
    ):
        self.conversation = conversation
        self.describe = describe
        self.ws_url = ws_url
        self.user_id = int(user_id)
        self.token = token
        self._stop = threading.Event()
        self._ws = None

    def _handle(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if event.get("post_type") != "message":
            return
        if event.get("message_type") != "private":
            return
        # Only him. Anyone else is not read at all.
        if int(event.get("user_id", 0)) != self.user_id:
            return
        text = read_message(event, self.describe)
        if text:
            self.conversation.heard(text)

    def run(self) -> None:
        import websocket

        headers = [f"Authorization: Bearer {self.token}"] if self.token else []
        while not self._stop.is_set():
            try:
                self._ws = websocket.create_connection(
                    self.ws_url, header=headers, timeout=30
                )
                self.conversation.channel.send_json = lambda payload: self._ws.send(
                    json.dumps(payload, ensure_ascii=False)
                )
                while not self._stop.is_set():
                    try:
                        self._handle(self._ws.recv())
                    except websocket.WebSocketTimeoutException:
                        continue
            except Exception:
                # A protocol implementation restarting is normal and not an
                # error worth stopping for.
                if self._stop.is_set():
                    break
                time.sleep(RECONNECT_DELAY_SECONDS)
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
