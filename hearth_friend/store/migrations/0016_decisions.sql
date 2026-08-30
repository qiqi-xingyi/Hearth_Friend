-- Every decision, with what it was made from and what happened after.
--
-- The weights that produce these are the personality, and they are currently a
-- prior someone wrote down. This is the record they would be learned from: the
-- features that went in, the choice that came out, and -- filled in afterwards
-- -- how he responded to it. How long he took to reply and how much he wrote
-- are already in the turn log; nothing new has to be asked of him.

CREATE TABLE decision_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id        INTEGER REFERENCES turn (id),
    features_json  TEXT NOT NULL,
    decision_json  TEXT NOT NULL,
    scores_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    -- outcome, written when he answers
    reply_delay_s  REAL,
    reply_length   INTEGER
);

CREATE INDEX idx_decision_turn ON decision_log (turn_id);
