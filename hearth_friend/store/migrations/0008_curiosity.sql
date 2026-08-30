-- Things she wants to understand.
--
-- Not a search queue. A person does not look things up mid-conversation; they
-- get curious about a topic and read about it later, and what they carry away
-- is the topic, not what you said. The delay is the point -- "I went and looked
-- that up afterwards" is a thing a friend says, and an instant lookup is a
-- thing a tool does.
--
-- Rejected entries are kept with their reason rather than dropped, because a
-- guard you cannot see the effect of is a guard you cannot trust.

CREATE TABLE curiosity (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question        TEXT NOT NULL,
    cues            TEXT NOT NULL,
    source_turn_id  INTEGER REFERENCES turn (id),
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    rejected_reason TEXT
);

CREATE INDEX idx_curiosity_open ON curiosity (resolved_at, rejected_reason, id);
