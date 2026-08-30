"""Things of his that are not finished.

The single most friend-shaped behaviour there is: he mentions something on
Tuesday that will have happened by Thursday, and on Friday she asks how it
went. Nothing else in this project produces that. Facts about him are standing
and do not come due; memories are things that already happened.

Asking is separate from closing on purpose. A friend asks once and then waits
for an answer -- asking every day is not attention, it is pressure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# How long after something was due she still thinks of it as worth asking
# about. Past this it is stale: bringing up a fortnight-old interview is not
# attentive, it is odd.
STALE_AFTER_DAYS = 14.0

# She waits this long for an answer before letting a thread go.
GIVE_UP_AFTER_DAYS = 21.0


@dataclass(frozen=True)
class Thread:
    id: int
    what: str
    cues: str
    due_at: str | None
    status: str


def due_now(thread_due_at: str | None, *, now: datetime | None = None) -> bool:
    """Whether the time it was going to happen has passed, and not long ago."""
    if not thread_due_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        due = datetime.fromisoformat(thread_due_at)
    except ValueError:
        return False
    if due > now:
        return False
    return now - due <= timedelta(days=STALE_AFTER_DAYS)


def overdue(thread_due_at: str | None, *, now: datetime | None = None) -> bool:
    """Past the point where asking would still make sense."""
    if not thread_due_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        due = datetime.fromisoformat(thread_due_at)
    except ValueError:
        return False
    return now - due > timedelta(days=STALE_AFTER_DAYS)


def as_prompt_block(threads: list[Thread]) -> str:
    """What is worth asking about, and what to leave alone.

    Split so that she asks about what has come due and does not interrogate him
    about everything he ever mentioned.
    """
    ready = [t for t in threads if t.status == "open" and due_now(t.due_at)]
    # Not simply "everything else": something a month past its date is stale,
    # and bringing it up is odd rather than attentive.
    waiting = [
        t for t in threads
        if t.status == "open" and not due_now(t.due_at) and not overdue(t.due_at)
    ]

    blocks: list[str] = []
    if ready:
        lines = "\n".join(f"- {t.what}" for t in ready)
        blocks.append(
            "【他有件事该有结果了】\n"
            + lines
            + "\n**主动问一句后来怎么样**，不用等他提起——他不说不代表不在意，"
            "多半只是没想到你还记着。\n"
            "找个自然的地方问，他要是正说着别的要紧事就先接住他的。\n"
            "问过一次就够了，他没答就别再追。"
        )
    if waiting:
        lines = "\n".join(f"- {t.what}" for t in waiting)
        blocks.append(
            "【他提过、还没到时候的事】\n" + lines + "\n先记着，不用现在问。"
        )
    return "\n\n".join(blocks)
