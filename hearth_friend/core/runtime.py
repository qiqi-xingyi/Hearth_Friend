"""The conversation loop.

Two properties matter here and both are about the turn log:

1. The user's message is persisted *before* the model is called, so a crash or a
   provider failure never loses something the user actually said.
2. Context is read back out of the database rather than held in memory. There is
   no in-process conversation state to lose, which is what makes restarting the
   process resume the conversation rather than reset it.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from hearth_friend.core.prompt import system_prompt
from hearth_friend.persona import Persona
from hearth_friend.providers.base import Message, ModelProvider, ProviderError
from hearth_friend.store import Store


class Runtime:
    def __init__(
        self,
        store: Store,
        provider: ModelProvider,
        persona: Persona,
        *,
        user_id: str,
        channel: str,
        context_turns: int = 40,
        temperature: float | None = None,
    ):
        self.store = store
        self.provider = provider
        self.persona = persona
        self.user_id = user_id
        self.channel = channel
        self.context_turns = context_turns
        self.temperature = temperature
        self.session_id: int | None = None

    # --------------------------------------------------------------- session

    def start_session(self) -> int:
        self.session_id = self.store.open_session(self.user_id, self.channel)
        return self.session_id

    def end_session(self) -> None:
        if self.session_id is not None:
            self.store.close_session(self.session_id)
            self.session_id = None

    def __enter__(self) -> "Runtime":
        self.start_session()
        return self

    def __exit__(self, *exc: object) -> None:
        self.end_session()

    # --------------------------------------------------------------- context

    def build_messages(self) -> list[Message]:
        """System prompt plus the recent turn window, read from the database."""
        messages: list[Message] = [
            {"role": "system", "content": system_prompt(self.persona)}
        ]
        for turn in self.store.recent_turns(self.user_id, self.context_turns):
            messages.append({"role": turn.role, "content": turn.content})
        return messages

    # -------------------------------------------------------------- speaking

    def respond(self, user_text: str) -> Iterator[str]:
        """Persist the user's message, then stream a reply and persist that too."""
        if self.session_id is None:
            self.start_session()
        assert self.session_id is not None

        self.store.append_turn(self.session_id, "user", user_text)
        # Read context back after the write, so the message just stored is the
        # last thing in the window and there is exactly one path to context.
        return self._stream_and_persist(self.build_messages())

    def _stream_and_persist(self, messages: Sequence[Message]) -> Iterator[str]:
        assert self.session_id is not None
        pieces: list[str] = []
        try:
            for piece in self.provider.stream(messages, temperature=self.temperature):
                pieces.append(piece)
                yield piece
        except GeneratorExit:
            # The reader stopped early (Ctrl-C at the prompt). Whatever was
            # already printed was seen, so it is part of the conversation.
            if pieces:
                self.store.append_turn(
                    self.session_id,
                    "assistant",
                    "".join(pieces),
                    meta={"interrupted": True},
                )
            raise
        except ProviderError as exc:
            # A partial reply was still shown to the user, so it happened and is
            # recorded. The turn log describes the conversation, not the
            # intention.
            if pieces:
                self.store.append_turn(
                    self.session_id,
                    "assistant",
                    "".join(pieces),
                    meta={"truncated": True, "error": str(exc)},
                )
            raise
        text = "".join(pieces)
        if text.strip():
            self.store.append_turn(self.session_id, "assistant", text)
