"""The loop, independent of where the messages come from.

Waiting for him to finish, deciding, sending a run of messages with pauses
between them -- none of that is about terminals or about QQ. It lived in the
CLI because the CLI was the only way in; it lives here because it is about to
stop being.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Protocol


class Channel(Protocol):
    """Somewhere to say something."""

    def send(self, text: str) -> None: ...


class Conversation:
    def __init__(
        self,
        runtime,
        channel: Channel,
        *,
        settle_seconds: float = 2.0,
        pause_seconds: float = 1.4,
        on_error: Callable[[str], None] | None = None,
    ):
        self.runtime = runtime
        self.channel = channel
        self.settle_seconds = settle_seconds
        self.pause_seconds = pause_seconds
        self.on_error = on_error or (lambda message: None)
        self._last_input = time.monotonic()
        self._last_spoke = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- incoming

    def heard(self, text: str) -> None:
        """He said something. Recorded now; answered when he stops."""
        self.runtime.ingest(text)
        self._last_input = time.monotonic()

    # -------------------------------------------------------------- speaking

    def _ready(self) -> bool:
        if not self.runtime.unanswered():
            return False
        # Both: he may still be typing, and if she has only just finished she
        # does not launch into another block. Without the second, anything sent
        # while she was composing finds the window already elapsed and lands
        # stacked on top of what she just said.
        quiet_since = max(self._last_input, self._last_spoke)
        return time.monotonic() - quiet_since >= self.settle_seconds

    def speak_once(self) -> int:
        said = 0
        try:
            for index, message in enumerate(self.runtime.reply()):
                if index:
                    time.sleep(self.pause_seconds)
                self.channel.send(message)
                said += 1
        except Exception as exc:  # keep the conversation alive
            self.on_error(str(exc))
        finally:
            self._last_spoke = time.monotonic()
        return said

    def _loop(self) -> None:
        while not self._stop.wait(0.2):
            if self._ready():
                self.speak_once()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="speaking", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
