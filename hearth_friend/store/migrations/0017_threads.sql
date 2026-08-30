-- Things of his that are not finished.
--
-- Neither a standing fact nor a past event: "我下周三面试" is something pending,
-- with a time by which it will have happened. Most of what makes someone feel
-- attended to is that this gets carried -- and asked about afterwards, which is
-- not something either of the other two tables can produce.
--
-- Asking is recorded separately from closing, because a friend asks once and
-- then waits. Asking again every day is not attention.

CREATE TABLE thread (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    what           TEXT NOT NULL,   -- what is pending, in her words
    cues           TEXT NOT NULL,
    opened_at      TEXT NOT NULL,
    due_at         TEXT,            -- when it will have happened
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'asked', 'closed', 'dropped')),
    asked_at       TEXT,
    closed_at      TEXT,
    outcome        TEXT,
    source_turn_id INTEGER REFERENCES turn (id),
    created_at     TEXT NOT NULL
);

CREATE INDEX idx_thread_live ON thread (status, due_at);
