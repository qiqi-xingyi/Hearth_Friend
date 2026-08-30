"""Where a conversation happens.

A messaging platform is an interface, not the thing. The QQ account can be
lost, Telegram can be blocked, a terminal can be closed -- none of that is her.
Identity, memory and everything derived from them live in one file that does
not know which of these is in use.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ChatAdapter(Protocol):
    name: str

    def run(self) -> None:
        """Connect, and keep the conversation going until stopped."""
        ...

    def stop(self) -> None: ...
