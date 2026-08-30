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


def extract_text(event: dict) -> str:
    """The words out of a OneBot message.

    Messages arrive either as a string or as segments. Anything that is not
    text -- an image, a sticker, a forwarded card -- is skipped rather than
    described, because she cannot see it and saying she can would be a lie.
    """
    message = event.get("message")
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, list):
        return ""
    parts = []
    for segment in message:
        if isinstance(segment, dict) and segment.get("type") == "text":
            parts.append(str((segment.get("data") or {}).get("text", "")))
    return "".join(parts).strip()


class QQAdapter:
    name = "qq"

    def __init__(self, conversation, ws_url: str, user_id: int, token: str = ""):
        self.conversation = conversation
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
        text = extract_text(event)
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
