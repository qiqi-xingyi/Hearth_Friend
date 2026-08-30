-- What happened between you, and what is true about him.
--
-- Split for the same reason her own facts are split from her reading: they are
-- recalled differently. Asked his name she must not have to be reminded of it
-- by association -- she answered "章鱼小丸子" and said she remembered him
-- saying so -- while what happened last Tuesday should come to mind the way
-- things come to mind, or not.
--
-- No FTS5 here. Its trigram tokenizer indexes three-character sequences, so in
-- Chinese it cannot match 猫, QB, 量子 or 洛 at all; explicit cues, written at
-- extraction time, do the first-stage filtering instead.

CREATE TABLE about_you (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'situation')),
    cues            TEXT NOT NULL,
    statement       TEXT NOT NULL,
    source_turn_id  INTEGER REFERENCES turn (id),
    superseded_by   INTEGER REFERENCES about_you (id),
    retired_at      TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_about_you_live ON about_you (superseded_by, retired_at, id);

CREATE TABLE memory (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    content          TEXT NOT NULL,   -- her own account, first person
    cues             TEXT NOT NULL,
    event_time       TEXT,            -- when it happened, not when it was written
    importance       REAL NOT NULL,
    -- Forgetting is decay, not deletion: strength falls with time, rises when
    -- something is recalled, and a row that drops out of reach stays in the
    -- table. Present from the first migration because adding it later means
    -- every existing row has no history to decay from.
    strength         REAL NOT NULL,
    last_recalled_at TEXT,
    recall_count     INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'consolidated', 'superseded', 'forgotten')),
    superseded_by    INTEGER REFERENCES memory (id),
    source_json      TEXT NOT NULL,   -- which turns produced this
    created_at       TEXT NOT NULL,
    embedding        BLOB,
    embedding_model  TEXT
);

CREATE INDEX idx_memory_live ON memory (status, id DESC);
CREATE INDEX idx_memory_importance ON memory (status, importance DESC);
