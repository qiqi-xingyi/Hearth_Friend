"""The conversation loop.

Not request-response. Messages arrive on a shared timeline: you can send three
in a row without waiting, and what she says back is a run of messages rather
than one block of text. A reply answers everything that is currently unanswered,
not the single line that triggered it.

Two properties are about the turn log:

1. What you say is persisted the moment it arrives, before any model is called,
   so a provider failure or a crash never loses it.
2. Context is read back out of the database rather than held in memory, so
   restarting resumes the conversation instead of resetting it.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from hearth_friend.core.curiosity import check as curiosity_check
from hearth_friend.core.curiosity import (
    as_prompt_block as curiosity_block,
)
from hearth_friend.core.extraction import (
    extract_curiosity,
    extract_memories,
    extract_pattern,
    extract_self_facts,
)
from hearth_friend.core.memory import Memory, cues_present
from hearth_friend.core.memory import as_prompt_block as memory_block
from hearth_friend.core.perception import Perception, perceive
from hearth_friend.core.prompt import (
    reading_block,
    split_messages,
    state_note,
    system_prompt,
)
from hearth_friend.core.selfhood import (
    SelfFact,
    as_prompt_block,
    parse_cues,
    recall,
)
from hearth_friend.core.attention import attend, temperature_for
from hearth_friend.core.state import State, after_perceiving, decayed, hours_since
from hearth_friend.providers.embedding import pack, unpack
from hearth_friend.providers.base import Message, ModelProvider, ProviderError
from hearth_friend.store import Store, Turn
from hearth_friend.world import Source, fetch_source


# How much has to have happened before she comes away wanting to understand
# something. Accumulated rather than scheduled, so a session where little was
# said produces nothing. UNCALIBRATED.
CURIOSITY_THRESHOLD = 1.2


class Runtime:
    def __init__(
        self,
        store: Store,
        provider: ModelProvider,
        persona,
        *,
        user_id: str,
        channel: str,
        context_turns: int = 40,
        context_chars: int = 6000,
        temperature: float | None = None,
        perceive_enabled: bool = True,
        embedding=None,
    ):
        self.store = store
        self.provider = provider
        self.persona = persona
        self.user_id = user_id
        self.channel = channel
        self.context_turns = context_turns
        self.context_chars = context_chars
        self.temperature = temperature
        self.perceive_enabled = perceive_enabled
        self.embedding = embedding
        self.session_id: int | None = None

    # --------------------------------------------------------------- session

    def start_session(self) -> int:
        self.session_id = self.store.open_session(self.user_id, self.channel)
        self.seed_self()
        return self.session_id

    def seed_self(self) -> int:
        """Put what the persona file declares about her into the database.

        Idempotent by statement, so adding a line to the persona file later
        takes effect, and nothing she has worked out since is overwritten.
        """
        added = 0
        for entry in getattr(self.persona, "self_facts", ()):
            if not self.store.has_self_statement(entry["statement"]):
                self.store.add_self_fact(
                    entry["kind"],
                    entry["cues"],
                    entry["statement"],
                    always_on=entry.get("always_on", False),
                )
                added += 1
        return added

    def end_session(self) -> None:
        if self.session_id is not None:
            finished, self.session_id = self.session_id, None
            self.store.close_session(finished)

    def extract_session(self, session_id: int) -> int:
        """Fold what she said in one session into what is true about her.

        Runs off the reply path, once per session. Marked done either way, so a
        session that yielded nothing is not reconsidered forever.
        """
        said = self.store.assistant_turns(session_id)
        # By volume, not by message count: her replies split into one to three
        # messages depending on the persona, so counting them skipped whole
        # sessions that had plenty in them.
        # UNCALIBRATED, deliberately low: a call costs a fraction of a cent and
        # what it catches is a thing about her that would otherwise drift. Only
        # pure noise is worth skipping.
        if sum(len(t.content) for t in said) < 15:
            self.store.mark_extracted(session_id)
            return 0

        known = [row["statement"] for row in self.store.self_facts()]
        found = extract_self_facts(self.provider, [t.content for t in said], known)

        added = 0
        for entry in found:
            if not self.store.has_self_statement(entry["say"]):
                self.store.add_self_fact(
                    entry["kind"],
                    entry["cues"],
                    entry["say"],
                    source_turn_id=said[-1].id,
                )
                added += 1
        self._extract_memories(session_id)
        self._extract_curiosity(session_id)
        self.store.mark_extracted(session_id)
        return added

    def _extract_curiosity(self, session_id: int) -> int:
        """What she came away wanting to understand.

        Fires on accumulated weight, not on every session: perception already
        scores how much each thing mattered, so a conversation that was mostly
        pleasantries leaves her with nothing to look into, which is right.
        """
        if self.store.session_salience(session_id) < CURIOSITY_THRESHOLD:
            return 0

        turns = self.store.session_turns(session_id)
        transcript = [
            f"{'他' if t.role == 'user' else '你'}：{t.content}" for t in turns
        ]
        private = [t.content for t in turns if t.role == "user"]
        known = [row["question"] for row in self.store.open_curiosity(limit=20)]

        kept = 0
        for entry in extract_curiosity(self.provider, transcript, known):
            if self.store.has_curiosity(entry["question"]):
                continue
            rejection = curiosity_check(entry["question"], private)
            self.store.add_curiosity(
                entry["question"],
                entry["cues"],
                source_turn_id=turns[-1].id if turns else None,
                rejected_reason=rejection.reason if rejection else None,
            )
            kept += 0 if rejection else 1
        return kept

    def catch_up_extraction(self, limit: int = 3) -> int:
        """Sessions that ended without being read, because the process died.

        Bounded: after a long gap you want her caught up, not a queue of calls
        between you and saying hello.
        """
        pending = [
            sid
            for sid in self.store.unextracted_sessions(self.user_id)
            if sid != self.session_id
        ]
        return sum(self.extract_session(sid) for sid in pending[-limit:])

    def __enter__(self) -> "Runtime":
        self.start_session()
        return self

    def __exit__(self, *exc: object) -> None:
        self.end_session()

    # --------------------------------------------------------------- context

    def remembered_self(self, text: str) -> list[SelfFact]:
        """What this stretch of conversation should bring to her mind."""
        facts = [
            SelfFact(
                row["id"],
                row["kind"],
                parse_cues(row["cues"]),
                row["statement"],
                bool(row["always_on"]),
            )
            for row in self.store.self_facts()
        ]
        return recall(facts, text)

    def build_messages(
        self,
        state: State | None = None,
        perception: Perception | None = None,
        remembered: list[SelfFact] | None = None,
        cue_text: str | None = None,
    ) -> list[Message]:
        """Stable persona, then history, then what she may do this turn.

        The ordering is deliberate. Everything before the last block is
        append-only and therefore cacheable, which on this provider is roughly a
        fiftyfold difference in the price of an input token.
        """
        messages: list[Message] = [
            {"role": "system", "content": system_prompt(self.persona)}
        ]
        # Placed before the history rather than after it: what she has read
        # changes daily, not per turn, so it stays part of the cacheable prefix
        # for the whole of a conversation.
        reading = reading_block(
            self.attended_reading(cue_text, state)
            if state is not None and cue_text is not None
            else self.store.recent_reading()
        )
        if reading:
            messages.append({"role": "system", "content": reading})
        wondering = curiosity_block(
            [row["question"] for row in self.store.open_curiosity()]
        )
        if wondering:
            messages.append({"role": "system", "content": wondering})
        for turn in self.recent_within_budget():
            messages.append({"role": turn.role, "content": turn.content})
        if remembered is not None:
            messages.append({"role": "system", "content": as_prompt_block(remembered)})
        if state is not None and cue_text is not None:
            messages.append({
                "role": "system",
                "content": memory_block(
                    self.recall(cue_text, state), self.store.about_you()
                ),
            })
        if state is not None:
            messages.append(
                {"role": "system", "content": state_note(state, perception, self.persona)}
            )
        return messages

    # ---------------------------------------------------------------- taking in

    def ingest(self, text: str) -> int:
        """Record something you said. Does not reply, and does not block.

        Separating this from replying is what lets you keep talking while she is
        still deciding what to say.
        """
        if self.session_id is None:
            self.start_session()
        assert self.session_id is not None
        return self.store.append_turn(self.session_id, "user", text)

    def unanswered(self) -> list[Turn]:
        """Your messages she has not answered yet.

        Not "everything since she last spoke": a message sent while she is
        composing lands before her reply does, and she never saw it.
        """
        return self.store.unanswered_turns(self.user_id, self.context_turns)

    # --------------------------------------------------------------- reading

    def refresh_reading(self, max_age_hours: float = 6.0) -> int:
        """Read the sources, if it has been a while. Returns items newly seen.

        Failures are silent and bounded: a source being down means she has not
        read it, which is a true statement, not an error to raise at you.
        """
        sources = getattr(self.persona, "reads", ())
        if not sources:
            return 0
        # Explicitly, because "never" is not "just now": hours_since returns 0
        # for a missing timestamp, which is right for state that has not drifted
        # yet and exactly wrong here -- it meant she never read anything at all.
        last = self.store.last_read_at()
        if last is not None and hours_since(last) < max_age_hours:
            return 0

        seen = 0
        for entry in sources:
            source = Source(entry["name"], entry.get("url", ""), entry.get("kind", "rss"))
            for item in fetch_source(source):
                if self.store.add_reading(
                    entry["name"], item.url, item.title, item.summary, item.published
                ):
                    seen += 1
        return seen

    def recent_within_budget(self) -> list[Turn]:
        """The tail of the conversation, under both limits.

        Filled newest-first and reversed, so what survives is the most recent
        rather than an arbitrary prefix.
        """
        turns = self.store.recent_turns(self.user_id, self.context_turns)
        kept: list[Turn] = []
        used = 0
        for turn in reversed(turns):
            used += len(turn.content)
            if kept and used > self.context_chars:
                break
            kept.append(turn)
        return list(reversed(kept))

    # ---------------------------------------------------------------- memory

    def recall(self, cue_text: str, state: State, k: int = 6) -> list[Memory]:
        """Two stages, so that what this costs does not depend on how much has
        ever happened.

        First an indexed shortlist -- reminded of it, recent, or it mattered.
        Then attention over that shortlist alone, which is a few hundred
        kilobytes of vectors whether the table holds a thousand rows or a
        million.
        """
        cues = cues_present(self.store.cue_vocabulary(), cue_text)
        # Something she had let go of can come back when the cue is direct
        # enough. People do this, and there is no reason she should be the one
        # who cannot.
        self.store.revive_memories(self.store.forgotten_matching(cues))
        candidates = self.store.memory_candidates(cues)
        if not candidates:
            return []

        model = self.embedding.model_id if self.embedding else None
        usable = [
            row
            for row in candidates
            if row["embedding"] and row["embedding_model"] == model
        ]

        if self.embedding is None or len(usable) < 2:
            picked = sorted(
                candidates, key=lambda r: -(r["importance"] + r["strength"])
            )[:k]
        else:
            query = self.embedding.embed([cue_text])[0]
            order = attend(
                query,
                [unpack(row["embedding"]) for row in usable],
                k=k,
                temperature=temperature_for(state.engagement, state.energy),
            )
            picked = [usable[i] for i in order]

        # What is formative is always in reach, not competing for a slot. These
        # are not remembered harder than other things; they are held
        # differently.
        held = self.store.formative_memories()
        picked = [row for row in held] + [
            row for row in picked if row["id"] not in {h["id"] for h in held}
        ]
        self.store.touch_memories([row["id"] for row in picked])
        return [
            Memory(
                row["id"],
                row["content"],
                row["cues"],
                row.get("event_time"),
                row.get("importance", 1.0),
                row.get("strength", 1.0),
                row.get("embedding"),
                row.get("embedding_model"),
            )
            for row in picked
        ]

    def generalise(self, minimum: int = 3) -> str | None:
        """Draw at most one understanding from things that keep recurring.

        One per pass on purpose. A conclusion about someone should accumulate at
        the speed evidence does, not at the speed a loop runs.
        """
        import json

        covered: set[int] = set()
        for row in self.store.patterns():
            covered.update(json.loads(row["source_json"] or "[]"))

        for cue, memory_ids in self.store.recurring_cues(minimum):
            fresh = [i for i in memory_ids if i not in covered]
            if len(fresh) < minimum:
                continue
            episodes = [row["content"] for row in self.store.memories_by_id(fresh)]
            pattern = extract_pattern(self.provider, cue, episodes)
            if not pattern:
                continue
            self.store.add_about_you(
                "pattern", cue, pattern, source_memory_ids=fresh
            )
            return pattern
        return None

    def let_time_pass(self) -> tuple[int, int]:
        """Decay, applied. Off the reply path, once per attach."""
        return self.store.forget_pass()

    def _extract_memories(self, session_id: int) -> int:
        turns = self.store.session_turns(session_id)
        if sum(len(t.content) for t in turns) < 30:
            return 0

        # Labelled in the language of the instruction. With "user:" and
        # "assistant:" against a Chinese prompt she read her own lines as his,
        # and came away believing he draws for a living and gets lost in Zelda.
        transcript = [
            f"{'他' if t.role == 'user' else '你'}：{t.content}" for t in turns
        ]
        known = [row["statement"] for row in self.store.about_you()]
        found = extract_memories(self.provider, transcript, known)

        added = 0
        for entry in found["about_you"]:
            if not self.store.has_about_you(entry["statement"]):
                self.store.add_about_you(
                    entry["kind"],
                    entry["cues"],
                    entry["statement"],
                    source_turn_id=turns[-1].id,
                )
                added += 1
        for entry in found["episodes"]:
            if not self.store.has_memory(entry["content"]):
                self.store.add_memory(
                    entry["content"],
                    entry["cues"],
                    importance=entry["importance"],
                    source_turn_ids=[t.id for t in turns],
                    formative=entry.get("formative", False),
                )
                added += 1
        return added

    # ------------------------------------------------------------- attention

    def catch_up_embeddings(self, limit: int = 200) -> int:
        """Vectorise anything new. Off the reply path; loading the model alone
        takes tens of seconds."""
        if self.embedding is None:
            return 0
        model = self.embedding.model_id
        done = 0
        for table in ("reading", "curiosity", "memory"):
            rows = self.store.rows_needing_embedding(table, model, limit)
            if not rows:
                continue
            vectors = self.embedding.embed([row["text"] for row in rows])
            for row, vector in zip(rows, vectors):
                self.store.set_embedding(table, row["id"], pack(vector), model)
                done += 1
        return done

    def attended_reading(self, cue_text: str, state: State, k: int = 10) -> list[dict]:
        """What of her reading this moment brings to mind.

        Falls back to an even sample across sources when there is no embedding
        model, which is a working system rather than a degraded one.
        """
        if self.embedding is None or not cue_text.strip():
            return self.store.recent_reading(limit=k)

        candidates = self.store.embedded_reading(self.embedding.model_id)
        if len(candidates) < 2:
            return self.store.recent_reading(limit=k)

        wondering = " ".join(
            row["question"] for row in self.store.open_curiosity(limit=4)
        )
        # Her own open questions bias what she notices, which is the loop: what
        # she attends to becomes what she wonders about, and what she wonders
        # about changes what she attends to.
        query_text = cue_text if not wondering else f"{cue_text}\n{wondering}"
        query = self.embedding.embed([query_text])[0]

        picked = attend(
            query,
            [unpack(row["embedding"]) for row in candidates],
            k=k,
            temperature=temperature_for(state.engagement, state.energy),
        )
        return [candidates[i] for i in picked]

    # ---------------------------------------------------------------- feeling

    def current_state(self) -> State:
        """Where she has drifted to since anything last happened."""
        stored = self.store.load_state(self.user_id)
        if stored is None:
            return State.initial(self.persona)
        state = State(**stored)
        return decayed(state, self.persona, hours=hours_since(state.updated_at))

    def _register(self, turns: Sequence[Turn]) -> tuple[State, Perception | None]:
        """Read the whole burst at once and let it move her.

        One read per burst rather than per message: it is cheaper, and a run of
        messages usually only means one thing.
        """
        perception: Perception | None = None
        if self.perceive_enabled and turns:
            burst = "\n".join(t.content for t in turns)
            earlier = [
                t.content
                for t in self.store.recent_turns(self.user_id, self.context_turns)
                if t.id < turns[0].id
            ][-4:]
            perception = perceive(self.provider, burst, recent=earlier)
            self.store.save_perception(turns[-1].id, perception)

        state = self.current_state()
        if perception is not None:
            state = after_perceiving(state, perception, self.persona)
        self.store.save_state(
            self.user_id,
            {
                "mood_valence": state.mood_valence,
                "mood_arousal": state.mood_arousal,
                "energy": state.energy,
                "engagement": state.engagement,
                "focus": state.focus,
            },
        )
        return state, perception

    # -------------------------------------------------------------- speaking

    def reply(self) -> Iterator[str]:
        """Answer everything unanswered, as a run of messages.

        Not streamed. A person sends whole messages, not a character at a time,
        and the whole text is needed before it can be split the way she splits
        things.
        """
        pending = self.unanswered()
        if not pending:
            return
        if self.session_id is None:
            self.start_session()
        assert self.session_id is not None

        state, perception = self._register(pending)
        # Recall is keyed on what is actually being talked about: the messages
        # she is answering plus a little of what came before them.
        cue_text = "\n".join(
            [t.content for t in self.store.recent_turns(self.user_id, 6)]
            + [t.content for t in pending]
        )
        remembered = self.remembered_self(cue_text)
        try:
            text = self.provider.generate(
                self.build_messages(state, perception, remembered, cue_text),
                temperature=self.temperature,
            )
        except ProviderError:
            raise

        answers_through = pending[-1].id
        for message in split_messages(text, self.persona.message_style):
            self.store.append_turn(
                self.session_id, "assistant", message, answers_through=answers_through
            )
            yield message

    def respond(self, text: str) -> Iterator[str]:
        """Say one thing and get the answer. A convenience over ingest + reply."""
        self.ingest(text)
        return self.reply()
