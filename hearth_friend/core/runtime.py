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

from hearth_friend.core.perception import Perception, perceive
from hearth_friend.core.prompt import state_note, system_prompt
from hearth_friend.core.state import State, after_perceiving, decayed, hours_since
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
        perceive_enabled: bool = True,
    ):
        self.store = store
        self.provider = provider
        self.persona = persona
        self.user_id = user_id
        self.channel = channel
        self.context_turns = context_turns
        self.temperature = temperature
        self.session_id: int | None = None
        self.perceive_enabled = perceive_enabled

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

    def build_messages(
        self, state: State | None = None, perception: Perception | None = None
    ) -> list[Message]:
        """Stable persona, then history, then how she is right now.

        The ordering is deliberate. Everything before the last block is
        append-only and therefore cacheable, which on this provider is roughly a
        fiftyfold difference in the price of an input token.
        """
        messages: list[Message] = [
            {"role": "system", "content": system_prompt(self.persona)}
        ]
        for turn in self.store.recent_turns(self.user_id, self.context_turns):
            messages.append({"role": turn.role, "content": turn.content})
        if state is not None:
            messages.append(
                {"role": "system", "content": state_note(state, perception, self.persona)}
            )
        return messages

    # ---------------------------------------------------------------- feeling

    def current_state(self) -> State:
        """Where she has drifted to since anything last happened."""
        stored = self.store.load_state(self.user_id)
        if stored is None:
            return State.initial(self.persona)
        state = State(**stored)
        return decayed(state, self.persona, hours=hours_since(state.updated_at))

    def _register(self, turn_id: int, text: str) -> tuple[State, Perception | None]:
        """Read the message, let it move her, and keep both."""
        perception: Perception | None = None
        if self.perceive_enabled:
            recent = [t.content for t in self.store.recent_turns(self.user_id, 5)[:-1]]
            perception = perceive(self.provider, text, recent=recent)
            self.store.save_perception(turn_id, perception)

        state = self.current_state()
        if perception is not None:
            state = after_perceiving(state, perception, self.persona)
        self.store.save_state(self.user_id, {
            "mood_valence": state.mood_valence,
            "mood_arousal": state.mood_arousal,
            "energy": state.energy,
            "engagement": state.engagement,
            "focus": state.focus,
        })
        return state, perception

    # -------------------------------------------------------------- speaking

    def respond(self, user_text: str) -> Iterator[str]:
        """Persist the user's message, then stream a reply and persist that too."""
        if self.session_id is None:
            self.start_session()
        assert self.session_id is not None

        turn_id = self.store.append_turn(self.session_id, "user", user_text)
        # Read context back after the write, so the message just stored is the
        # last thing in the window and there is exactly one path to context.
        state, perception = self._register(turn_id, user_text)
        return self._stream_and_persist(self.build_messages(state, perception))

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
