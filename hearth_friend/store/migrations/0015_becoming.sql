-- Changing, and the record of having changed.
--
-- Not a brake. A friend who cannot drift is not a friend, and the possibility
-- of drifting apart is what makes not having done so mean anything.
--
-- The log exists because two things look identical from outside: she has grown
-- distant because there were two months of silence, and she has grown distant
-- because an update rule is wrong or an extraction attributed someone else's
-- words to him. The first should stand. The second should be undone. Without
-- the evidence written down beside the change there is no telling which.

CREATE TABLE state_change_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    target        TEXT NOT NULL,     -- 'trait' | 'relationship'
    key           TEXT NOT NULL,
    old_value     REAL NOT NULL,
    new_value     REAL NOT NULL,
    reason        TEXT NOT NULL,     -- in words, for a person to read
    evidence_json TEXT,              -- what it was drawn from
    job           TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_state_change_when ON state_change_log (created_at DESC);
CREATE INDEX idx_state_change_key ON state_change_log (target, key, id);

-- How she is with him, as opposed to how she is. This moves in weeks, where
-- personality moves in months: warmth toward one person is not the same thing
-- as being a warm person, and conflating them is how a quiet fortnight would
-- have rewritten her character.
CREATE TABLE relationship (
    user_id     TEXT PRIMARY KEY,
    closeness   REAL NOT NULL DEFAULT 0.3,   -- how near she feels to him
    ease        REAL NOT NULL DEFAULT 0.4,   -- how unguarded she is
    updated_at  TEXT NOT NULL
);
