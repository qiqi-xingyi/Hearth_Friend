-- Her interior.
--
-- `state` is what persists between turns: it is changed by what you say and it
-- changes what she does next. Without it every reply is manufactured from
-- scratch and nothing that happens to her leaves a trace.
--
-- `perception` is what she made of each incoming message. It is derived from
-- `turn` and can be recomputed, so it carries no authority of its own — but it
-- is kept, because it is the evidence behind every state change.

CREATE TABLE state (
    user_id      TEXT PRIMARY KEY,
    mood_valence REAL NOT NULL,   -- -1 low .. +1 high
    mood_arousal REAL NOT NULL,   --  0 flat .. 1 keyed up
    energy       REAL NOT NULL,   --  0 spent .. 1 fresh
    engagement   REAL NOT NULL,   --  0 going through the motions .. 1 leaning in
    focus        TEXT,            -- what she is currently on, in her words
    updated_at   TEXT NOT NULL
);

CREATE TABLE perception (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id           INTEGER NOT NULL REFERENCES turn (id),
    user_emotion      TEXT,
    emotion_intensity REAL,
    wants             TEXT,       -- what the message is actually after
    salience          REAL,       -- how much this matters to her
    about_her         INTEGER,    -- 0/1: is this addressed to her, or about her
    raw_json          TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX idx_perception_turn ON perception (turn_id);
