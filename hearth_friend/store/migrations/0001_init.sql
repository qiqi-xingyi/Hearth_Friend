-- M0 schema.
--
-- `turn` is the single source of truth for everything this system will ever
-- derive: memories, state, relationship, personality. Those are all caches and
-- may be rebuilt. This table may not be rewritten, so append-only is enforced
-- here rather than left to the discipline of callers.

CREATE TABLE session (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    channel    TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);

CREATE INDEX idx_session_user ON session (user_id, id);

CREATE TABLE turn (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES session (id),
    role           TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    channel_msg_id TEXT,
    meta_json      TEXT
);

CREATE INDEX idx_turn_session ON turn (session_id, id);
CREATE INDEX idx_turn_created ON turn (created_at);

CREATE TRIGGER turn_is_append_only_update
BEFORE UPDATE ON turn
BEGIN
    SELECT RAISE(ABORT, 'turn is append-only: it is the source of truth');
END;

CREATE TRIGGER turn_is_append_only_delete
BEFORE DELETE ON turn
BEGIN
    SELECT RAISE(ABORT, 'turn is append-only: it is the source of truth');
END;
